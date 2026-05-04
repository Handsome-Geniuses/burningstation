from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.tests.cycle_coin_shutter import test_cycle_coin_shutter
from lib.automation.tests.cycle_nfc import test_cycle_nfc
from lib.automation.tests.cycle_modem import test_cycle_modem
from lib.automation.tests.cycle_print import test_cycle_print
from lib.automation.tests.cycle_meter_ui import test_cycle_meter_ui
from lib.automation.tests.cycle_call_in import test_cycle_call_in
from lib.automation.helpers import StopAutomation
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

CYCLE_ALL_GLOBAL_KEYS = {"numBurnCycles", "numBurnDelay", "monitors", "broadcast_job"}


def _device_key_variants(device: str):
    return (device, device.replace(" ", "_"))


def _cycle_all_shared_kwargs(kwargs):
    reserved = set(CYCLE_ALL_GLOBAL_KEYS)
    for device_name, _, _ in DEVICES:
        reserved.update(_device_key_variants(device_name))

    return {k: v for k, v in kwargs.items() if k not in reserved}


def _resolve_subtest_kwargs(device: str, kwargs, default_cfg=None):
    shared_kwargs = _cycle_all_shared_kwargs(kwargs)
    default_cfg = dict(default_cfg or {})

    for key in _device_key_variants(device):
        cfg = kwargs.get(key)
        if isinstance(cfg, dict):
            enabled = cfg.get("enabled", True)
            custom_cfg = {k: v for k, v in cfg.items() if k != "enabled"}
            return bool(enabled), {**shared_kwargs, **default_cfg, **custom_cfg}

    raw_value = 0
    for key in _device_key_variants(device):
        if key in kwargs:
            raw_value = kwargs[key]
            break

    enabled = bool(raw_value)
    if not enabled:
        return False, {}

    final_kwargs = {**shared_kwargs, **default_cfg}
    if isinstance(raw_value, bool):
        final_kwargs.setdefault("count", 1)
    elif isinstance(raw_value, (int, float)):
        final_kwargs["count"] = int(raw_value)
    else:
        final_kwargs.setdefault("count", 1)

    return True, final_kwargs


def _run_device(meter: SSHMeter, shared: SharedState, device: str, fn, subtest_kwargs=None):
    subtest_kwargs = dict(subtest_kwargs or {})
    count = int(subtest_kwargs.get("count", 1))

    if count <= 0:
        shared.device_results[device] = "n/a"
        return

    shared.current_device = device
    if device in {"printer", "coin shutter", "nfc", "modem"}:
        shared.set_allowed({device}, reason=f"Running {device} subtest")
    else:
        shared.set_allowed(set(), reason=f"Running {device} (no monitors expected)")

    if not meter.device_firmware(device):
        shared.device_results[device] = "missing"
        shared.current_device = None
        shared.set_allowed(set(), reason=f"{device} missing, monitors reset")
        return

    shared.device_results[device] = "running"

    try:
        subtest_kwargs["subtest"] = True
        fn(meter, shared=shared, **subtest_kwargs)
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


def test_cycle_all(meter: SSHMeter, shared: SharedState, **kwargs):
    func_name = inspect.currentframe().f_code.co_name
    burn_count = kwargs.get("numBurnCycles", 1)
    burn_delay = kwargs.get("numBurnDelay", 10)

    shared.device_results.update({name: "pending" for name, _, _ in DEVICES})

    for i in range(burn_count):
        shared.log(f"{meter.host} {func_name} {i+1}/{burn_count}")
        shared.broadcast_progress(meter.host, "burn-in", i + 1, burn_count)

        for name, fn, default_cfg in DEVICES:
            if shared.stop_event.is_set():
                # leave remaining devices as 'pending' (or 'n/a')
                return

            enabled, subtest_kwargs = _resolve_subtest_kwargs(name, kwargs, default_cfg=default_cfg)
            if not enabled:
                shared.device_results[name] = "n/a"
                continue

            _run_device(meter, shared, name, fn, subtest_kwargs=subtest_kwargs)
            time.sleep(0.5)

        time.sleep(burn_delay)

    time.sleep(0.5)
    if not meter.in_diagnostics():
        meter.press("diagnostics")
