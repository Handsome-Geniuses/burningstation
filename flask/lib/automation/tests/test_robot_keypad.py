import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient


def test_robot_keypad(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """
    Navigate to the keypad diagnostics page and wait for the keypad monitor
    to mark success (all required keys pressed) or a fault to stop the run.
    """
    func_name = inspect.currentframe().f_code.co_name
    buttons = kwargs.get("buttons")
    max_duration_s = int(kwargs.get("max_duration_s", 300))

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_button_press", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "test": True})
    # job_id = robot.run_program("temp_button_press", {"buttons": buttons, "meter_type": meter.meter_type, "meter_id": meter.hostname})

    if meter.in_diagnostics():
        meter.press('diagnostics'); meter.press('diagnostics')
    else:
        meter.press('diagnostics')

    meter.press('minus'); meter.press('ok')
    meter.press('minus'); meter.press('minus'); meter.press('minus'); meter.press('minus'); meter.press('minus'); meter.press('minus'); meter.press('ok')
    if meter.meter_type == 'msx':
        meter.press('minus'); meter.press('minus'); meter.press('ok')
    else:
        for i in range(8):
            meter.press('plus')
        meter.press('ok')
    time.sleep(0.5)

    #! double check that we made it to the right page

    start = time.time()
    poll = 0.5
    while True:
        if shared.stop_event.is_set():
            return

        # Success when monitor emits MarkSuccess
        if getattr(shared, "success_event", None) and shared.success_event.is_set():
            return

        if time.time() - start > max_duration_s:
            # timeout: let jobs.py classify as FAIL (stop_event triggers)
            shared.stop_event.set()
            return
        
        #! check if the page has changed and navigate back to keypad test page?

        check_stop_event(shared)
        time.sleep(poll)


