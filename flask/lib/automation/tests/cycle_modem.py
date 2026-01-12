from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect

MIN_MODEM_ON_DELAY = 30
MIN_MODEM_OFF_DELAY = 25


def test_cycle_modem(meter: SSHMeter, shared: SharedState, **kwargs):
    """ Toggle ON/OFF Modem N times. Stops early if shared.stop_event is set. """
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    delay_on = max(float(kwargs.get("delay_on", 30.0)), MIN_MODEM_ON_DELAY)
    delay_off = max(float(kwargs.get("delay_off", 25.0)), MIN_MODEM_OFF_DELAY)
    subtest = bool(kwargs.get("subtest", False))

    for i in range(count):
        shared.log(f"{meter.host} {func_name} {i+1}/{count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'modem', i+1, count)
        
        meter.toggle_modem(True)
        time.sleep(delay_on)
        meter.toggle_modem(False)
        time.sleep(delay_off)
        check_stop_event(shared)


