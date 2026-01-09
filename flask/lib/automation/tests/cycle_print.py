# from lib.meter.ssh_metert SSHMeter
from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect

MIN_PRINT_RESULT_DELAY = 8.0


def test_cycle_print(meter: SSHMeter, shared: SharedState, **kwargs):
    """Run a print test N times with delay. Stops early if shared.stop_event is set."""
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    delay = max(float(kwargs.get("delay", 8.0)), MIN_PRINT_RESULT_DELAY)
    subtest = bool(kwargs.get("subtest", False))

    for i in range(count):
        shared.log(f"{meter.host} {func_name} {i+1}/{count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'printer', i+1, count)
        
        meter.printer_test()
        time.sleep(delay)
        check_stop_event(shared)
    
    time.sleep(delay)  # Final wait to ensure any last print operations complete
    check_stop_event(shared)
