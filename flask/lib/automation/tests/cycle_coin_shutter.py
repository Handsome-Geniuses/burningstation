from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect


def test_cycle_coin_shutter(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """Open/close coin shutter N times. Stops early if shared.stop_event is set."""
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    delay = float(kwargs.get("delay", 0.1))
    subtest = bool(kwargs.get("subtest", False))

    for i in range(count):
        print(f"{meter.host} {func_name} {i+1}/{count}")
        if shared and not subtest:
            shared.broadcast_progress(meter.host, 'coin shutter', i+1, count)

        meter.coin_shutter_pulse(1,0.1,0.1)
        time.sleep(delay)
        check_stop_event(shared)
    check_stop_event(shared)
    





