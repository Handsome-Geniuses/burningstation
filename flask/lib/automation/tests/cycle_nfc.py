from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect

MIN_NFC_DELAY = 7.0


def test_cycle_nfc(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """ Toggle ON/OFF NFC Reader N times. Stops early if shared.stop_event is set. """
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    delay = max(float(kwargs.get("delay", 7.0)), MIN_NFC_DELAY)
    subtest = bool(kwargs.get("subtest", False))
    
    if meter.in_diagnostics():
        meter.press('diagnostics'); meter.press('diagnostics')
    else:
        meter.press('diagnostics')

    meter.press('minus')
    meter.press('ok')

    for i in range(8):
        meter.press('plus')
    meter.press('ok')

    meter.press('plus'); meter.press('plus'); meter.press('plus')
    meter.press('ok')

    for i in range(count):
        print(f"{meter.host} {func_name} {i+1}/{count}")
        if shared and not subtest:
            shared.broadcast_progress(meter.host, 'nfc', i+1, count)
        
        meter.press('plus')
        time.sleep(delay)
        meter.press('minus')
        time.sleep(delay)
        check_stop_event(shared)

    time.sleep(1)
    if meter.in_diagnostics():
        meter.press('diagnostics'); meter.press('diagnostics')
    else:
        meter.press('diagnostics')


