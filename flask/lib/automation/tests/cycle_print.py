from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import inspect

MIN_PRINT_RESULT_DELAY = 8.0


def test_cycle_print(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """Run a print test N times with delay. Stops early if shared.stop_event is set."""
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    delay = max(float(kwargs.get("delay", 8.0)), MIN_PRINT_RESULT_DELAY)
    subtest = bool(kwargs.get("subtest", False))

    for i in range(count):
        print(f"{meter.host} {func_name} {i+1}/{count}")
        if shared and not subtest:
            shared.broadcast_progress(meter.host, 'printer', i+1, count)
        
        meter.printer_test()
        time.sleep(delay)
        check_stop_event(shared)
    
    time.sleep(delay)  # Final wait to ensure any last print operations complete
    check_stop_event(shared)


if __name__ == "__main__":
    test_cycle_print(SSHMeter("192.168.137.157"), count=1, delay=5)