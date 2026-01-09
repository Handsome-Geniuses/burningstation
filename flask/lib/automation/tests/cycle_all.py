from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.tests.cycle_coin_shutter import test_cycle_coin_shutter
from lib.automation.tests.cycle_nfc import test_cycle_nfc
from lib.automation.tests.cycle_modem import test_cycle_modem
from lib.automation.tests.cycle_print import test_cycle_print
from lib.automation.tests.cycle_meter_ui import test_cycle_meter_ui
from lib.automation.helpers import StopAutomation
import time
import inspect


DEVICES = [
    ("coin shutter", test_cycle_coin_shutter),
    ("nfc", test_cycle_nfc),
    ("modem", test_cycle_modem),
    ("printer", test_cycle_print),
    ("screen test", test_cycle_meter_ui),
]


def _run_device(meter: SSHMeter, shared: SharedState, device: str, fn, count):
    if count == 0:
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
        fn(meter, shared=shared, count=count, subtest=True)
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

    shared.device_results.update({name: "pending" for name, _ in DEVICES})

    for i in range(burn_count):
        shared.log(f"{meter.host} {func_name} {i+1}/{burn_count}")
        shared.broadcast_progress(meter.host, "burn-in", i + 1, burn_count)

        for name, fn in DEVICES:
            if shared.stop_event.is_set():
                # leave remaining devices as 'pending' (or 'n/a')
                return

            count = kwargs.get(name, 0)
            _run_device(meter, shared, name, fn, count)
            time.sleep(0.5)

        time.sleep(burn_delay)

    time.sleep(0.5)
    if not meter.in_diagnostics():
        meter.press("diagnostics")
