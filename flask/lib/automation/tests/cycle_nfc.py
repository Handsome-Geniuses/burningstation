from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect

MIN_NFC_DELAY = 7.0


def test_cycle_nfc(meter: SSHMeter, shared: SharedState, **kwargs):
    """ Toggle ON/OFF NFC Reader N times. Stops early if shared.stop_event is set. """
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    delay = max(float(kwargs.get("delay", 7.0)), MIN_NFC_DELAY)
    subtest = bool(kwargs.get("subtest", False))

    shared.set_allowed(set(), reason="NFC navigation in progress")
    time.sleep(1)
    
    meter.goto_nfc()

    shared.set_allowed({"nfc"}, reason="NFC page ready; arm monitor")
    time.sleep(1)

    for i in range(job_count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'nfc', cycle_num, job_count)

        meter.press('plus')
        time.sleep(delay)
        meter.press('minus')
        time.sleep(delay)
        check_stop_event(shared)

    time.sleep(1)
    shared.set_allowed(set(), reason="NFC cleanup")
    time.sleep(1)
    meter.force_diagnostics()

