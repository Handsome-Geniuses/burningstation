import inspect
import time

from lib.automation.helpers import StopAutomation
from lib.automation.shared_state import SharedState
from lib.automation.tests.cycle_meter_ui import test_cycle_meter_ui
from lib.automation.tests.test_operator_card_reader import test_operator_card_reader
from lib.automation.tests.test_operator_coins import test_operator_coins
from lib.automation.tests.test_operator_keypad import test_operator_keypad
from lib.automation.tests.test_operator_nfc_tap import test_operator_nfc_tap
from lib.automation.tests.test_operator_touchscreen import test_operator_touchscreen
from lib.automation.tests.test_operator_display_brightness import test_operator_display_brightness
from lib.meter.ssh_meter import SSHMeter


OPERATOR_TESTS = [
    ("screen_test", test_cycle_meter_ui, {"payment_type": "coins", "debug_ui": 0}),
    (
        "coins",
        test_operator_coins,
        {
            "max_duration_s": 60.0,
            "allow_rejected": True,
        },
    ),
    ("touchscreen", test_operator_touchscreen, {"max_duration_s": 60.0}),
    ("display_brightness", test_operator_display_brightness, {"max_duration_s": 60.0}),
    ("keypad", test_operator_keypad, {}),
    (
        "contactless",
        test_operator_nfc_tap,
        {"max_duration_s": 60.0, "poll_s": 0.75},
    ),
    (
        "card_reader",
        test_operator_card_reader,
        {
            "max_duration_s": 90.0,
            "poll_s": 0.5,
            "require_card_accepted": False,
        },
    ),
]

OPERATOR_CYCLE_GLOBAL_KEYS = {
    "numBurnCycles",
    "numBurnDelay",
    "monitors",
    "broadcast_job",
}


def _operator_cycle_shared_kwargs(kwargs):
    reserved = set(OPERATOR_CYCLE_GLOBAL_KEYS)
    reserved.update(name for name, _, _ in OPERATOR_TESTS)
    return {key: value for key, value in kwargs.items() if key not in reserved}


def _resolve_subtest_kwargs(device, kwargs, default_cfg=None):
    cfg = kwargs.get(device)
    if cfg is None:
        raise KeyError(f"Missing subtest config for {device!r}")
    if not isinstance(cfg, dict):
        raise TypeError(
            f"Subtest config for {device!r} must be a dict, got {type(cfg).__name__}"
        )
    if "job_count" not in cfg:
        raise KeyError(f"Subtest config for {device!r} is missing job_count")

    try:
        job_count = int(cfg["job_count"])
    except (TypeError, ValueError):
        raise ValueError(f"{cfg['job_count']!r} is not a valid job_count")

    if job_count <= 0:
        return False, {}

    custom_cfg = {key: value for key, value in cfg.items() if key != "job_count"}
    return True, {
        **_operator_cycle_shared_kwargs(kwargs),
        **dict(default_cfg or {}),
        **custom_cfg,
        "job_count": job_count,
    }


def _run_operator_test(meter, shared, device, test_func, subtest_kwargs):
    shared.current_device = device
    shared.device_results[device] = "running"
    shared.set_allowed(set(), reason=f"Running monitor-free {device} subtest")

    try:
        subtest_kwargs = dict(subtest_kwargs)
        subtest_kwargs["subtest"] = True
        test_func(meter, shared=shared, **subtest_kwargs)
        if not shared.stop_event.is_set():
            shared.device_results[device] = "pass"
    except StopAutomation:
        shared.device_results[device] = "fail"
        raise
    except Exception:
        shared.device_results[device] = "fail"
        raise
    finally:
        shared.current_device = None
        shared.set_allowed(set(), reason=f"Finished {device} subtest")


def operator_cycle_all(meter: SSHMeter, shared: SharedState, **kwargs):
    """Run the operator-assisted QC tests without robot or monitor dependencies."""
    func_name = inspect.currentframe().f_code.co_name
    cycle_count = int(kwargs.get("numBurnCycles", 1))
    cycle_delay = float(kwargs.get("numBurnDelay", 1))

    shared.device_results.update({name: "pending" for name, _, _ in OPERATOR_TESTS})

    for cycle in range(cycle_count):
        cycle_num = cycle + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{cycle_count}")
        shared.broadcast_progress(meter.host, "operator_cycle", cycle_num, cycle_count)

        for device, test_func, default_cfg in OPERATOR_TESTS:
            if shared.stop_event.is_set():
                return

            should_run, subtest_kwargs = _resolve_subtest_kwargs(
                device, kwargs, default_cfg=default_cfg
            )
            if not should_run:
                shared.device_results[device] = "n/a"
                continue

            _run_operator_test(
                meter, shared, device, test_func, subtest_kwargs=subtest_kwargs
            )
            time.sleep(0.5)

        if cycle_num < cycle_count:
            time.sleep(cycle_delay)

    if not meter.in_diagnostics():
        meter.press("diagnostics")
