from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.tests.cycle_coin_shutter import test_cycle_coin_shutter
from lib.automation.tests.cycle_nfc import test_cycle_nfc
from lib.automation.tests.cycle_modem import test_cycle_modem
from lib.automation.tests.cycle_print import test_cycle_print
from lib.automation.tests.cycle_meter_ui import test_cycle_meter_ui
from lib.automation.tests.cycle_call_in import test_cycle_call_in
from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.recovery import run_subtest
from lib.meter.lifecycle import MeterInterrupted
import time
import inspect


DEVICES = [
    ("coin shutter", test_cycle_coin_shutter, {}),
    ("nfc", test_cycle_nfc, {}),
    ("modem", test_cycle_modem, {}),
    ("printer", test_cycle_print, {}),
    ("screen test", test_cycle_meter_ui, {}),
    ("call in", test_cycle_call_in, {}),
]

CYCLE_ALL_GLOBAL_KEYS = {"numBurnCycles", "numBurnDelay", "stop_on_fail", "monitors", "broadcast_job"}


def _device_key_variants(device: str):
    return (device, device.replace(" ", "_"))


def _cycle_all_shared_kwargs(kwargs):
    reserved = set(CYCLE_ALL_GLOBAL_KEYS)
    for device_name, _, _ in DEVICES:
        reserved.update(_device_key_variants(device_name))

    return {k: v for k, v in kwargs.items() if k not in reserved}


def _coerce_job_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is not a valid job_count")


def _resolve_subtest_kwargs(device: str, kwargs, default_cfg=None):
    shared_kwargs = _cycle_all_shared_kwargs(kwargs)
    default_cfg = dict(default_cfg or {})

    cfg = None
    for key in _device_key_variants(device):
        if key in kwargs:
            cfg = kwargs[key]
            break

    if cfg is None:
        raise KeyError(f"Missing subtest config for {device!r}")
    if not isinstance(cfg, dict):
        raise TypeError(f"Subtest config for {device!r} must be a dict, got {type(cfg).__name__}")
    if "job_count" not in cfg:
        raise KeyError(f"Subtest config for {device!r} is missing job_count")

    job_count = _coerce_job_count(cfg["job_count"])
    if job_count <= 0:
        return False, {}

    custom_cfg = {k: v for k, v in cfg.items() if k != "job_count"}
    return True, {
        **shared_kwargs,
        **default_cfg,
        **custom_cfg,
        "job_count": job_count,
    }


def _run_device(meter: SSHMeter, shared: SharedState, device: str, fn, subtest_kwargs=None):
    subtest_kwargs = dict(subtest_kwargs or {})
    count = int(subtest_kwargs.get("job_count", 1))

    if count <= 0:
        shared.device_results[device] = "n/a"
        return

    shared.current_device = device
    shared.log(f"Running {device} subtest")

    if not meter.device_firmware(device):
        shared.device_results[device] = "missing"
        shared.current_device = None
        shared.log(f"{device} missing; skipping subtest")
        return

    shared.device_results[device] = "running"

    try:
        banner_text = f"(Running {device.replace('_', ' ')})"
        subtest_kwargs["subtest"] = True
        subtest_kwargs["banner_text"] = banner_text
        meter.set_ui_mode("banner", banner_text)
        if getattr(meter, "is_mock", False):
            from lib.automation.mock_meter import run_virtual_passive_test
            run_virtual_passive_test(meter, shared, device, subtest_kwargs)
        else:
            fn(meter, shared=shared, **subtest_kwargs)
        if not shared.stop_event.is_set():
            shared.device_results[device] = "pass"
    except MeterInterrupted:
        shared.device_results[device] = "interrupted"
        raise
    except StopAutomation:
        shared.device_results[device] = "fail"
        raise
    except Exception:
        shared.device_results[device] = "fail"
        raise
    finally:
        shared.current_device = None
        shared.log(f"Finished {device} subtest")


def _cycle_wait(shared, seconds):
    remaining = max(0.0, float(seconds))
    while remaining > 0:
        if shared.meter_session is not None:
            shared.attempt_epoch = shared.meter_session.wait_ready(shared)
            shared.disruption_event.clear()
        check_stop_event(shared)
        step = min(0.1, remaining)
        time.sleep(step)
        remaining -= step
    check_stop_event(shared)


def test_cycle_all(meter: SSHMeter, shared: SharedState, **kwargs):
    func_name = inspect.currentframe().f_code.co_name
    burn_count = kwargs.get("numBurnCycles", 1)
    burn_delay = kwargs.get("numBurnDelay", 10)
    stop_on_fail = kwargs.get("stop_on_fail", True)
    failed_devices = set()

    shared.device_results.update({name: "pending" for name, _, _ in DEVICES})

    for i in range(burn_count):
        shared.log(f"{meter.host} {func_name} {i+1}/{burn_count}")
        shared.broadcast_progress(meter.host, "burn-in", i + 1, burn_count)

        for name, fn, default_cfg in DEVICES:
            if shared.stop_event.is_set():
                # leave remaining devices as 'pending' (or 'n/a')
                return

            should_run, subtest_kwargs = _resolve_subtest_kwargs(name, kwargs, default_cfg=default_cfg)
            if not should_run:
                shared.device_results[name] = "n/a"
                continue

            try:
                run_subtest(meter, shared, name,
                            lambda: _run_device(meter, shared, name, fn, subtest_kwargs=subtest_kwargs))
                if shared.device_results.get(name) == "fail" or shared.stop_event.is_set():
                    failed_devices.add(name)
                    if shared.stop_event.is_set() and not shared.abort_event.is_set():
                        shared.continue_after_failure(stop_on_fail)
            except MeterInterrupted:
                raise
            except Exception as exc:
                failed_devices.add(name)
                shared.last_error = str(exc)
                if not shared.continue_after_failure(stop_on_fail):
                    raise
            finally:
                if name in failed_devices:
                    shared.device_results[name] = "fail"
            _cycle_wait(shared, 0.5)

        _cycle_wait(shared, burn_delay)

    _cycle_wait(shared, 0.5)
    from lib.automation.recovery import await_meter
    await_meter(meter, shared)
    if not meter.in_diagnostics():
        meter.press("diagnostics", delay=0.4)
