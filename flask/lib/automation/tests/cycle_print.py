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
    job_count = int(kwargs.get("job_count", 3))
    delay = max(float(kwargs.get("delay", 8.0)), MIN_PRINT_RESULT_DELAY)
    subtest = bool(kwargs.get("subtest", False))

    for i in range(job_count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'printer', cycle_num, job_count)

        if meter.meter_type == "ms3":
            shared.log("Toggle printer OFF and back ON to avoid a jam")
            meter.reboot_printer()
        
        meter.printer_test()
        time.sleep(delay)
        check_stop_event(shared)
    
    time.sleep(delay)  # Final wait to ensure any last print operations complete
    check_stop_event(shared)
