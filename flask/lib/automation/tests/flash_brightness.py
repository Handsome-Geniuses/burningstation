from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time


def flash_brightness(meter: SSHMeter, shared: SharedState = None, count: int = 10, delay: float = 0):
    meter.connect()
    brightness = meter.get_brightness()

    for i in range(count):
        meter.set_brightness(0)
        meter.beep(1)
        time.sleep(0.2)
        check_stop_event(shared)
        meter.set_brightness(50)
        meter.beep(1)
        time.sleep(0.2)
        check_stop_event(shared)

    meter.set_brightness(brightness)
    meter.close()
    check_stop_event(shared)
        



