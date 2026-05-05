from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect


def test_cycle_coin_shutter(meter: SSHMeter, shared: SharedState, **kwargs):
    """Open/close coin shutter N times. Stops early if shared.stop_event is set."""
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    delay = float(kwargs.get("delay", 0.1))
    subtest = bool(kwargs.get("subtest", False))

    for i in range(job_count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'coin shutter', cycle_num, job_count)

        meter.coin_shutter_pulse(1,0.1,0.1)
        time.sleep(delay)
        check_stop_event(shared)
    check_stop_event(shared)
    





