import time
import inspect
import requests

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient

KEYPAD_PAGE = "Service:Utilities:Peripherals:Keyboard"

def is_on_keypad_page(meter: SSHMeter, shared: SharedState, timeout: float = 3.0) -> bool:
    url = f"http://{meter.host}:8005/UIPage.php"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        shared.log(f"Failed to fetch UI page, assuming NOT on keyboard page | Error: {e}")
        return False
    
    return KEYPAD_PAGE in resp.text


def test_robot_keypad(meter: SSHMeter, shared: SharedState, **kwargs):
    """
    Navigate to the keypad diagnostics page and wait for the keypad monitor
    to mark success (all required keys pressed) or a fault to stop the run.
    """
    func_name = inspect.currentframe().f_code.co_name
    buttons = kwargs.get("buttons")
    max_duration_s = int(kwargs.get("max_duration_s", 300))
    subtest = bool(kwargs.get("subtest", False))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 1, 1)

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_button_press", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "buttons": buttons, "charuco_frame": kwargs.get("charuco_frame"), "test": False})
    # job_id = robot.run_program("temp_button_press", {"buttons": buttons, "meter_type": meter.meter_type, "meter_id": meter.hostname})

    meter.goto_keypad()
    if not is_on_keypad_page(meter, shared):
        shared.log(f"warning: did NOT make it to the keypad page")

    start = time.time()
    poll = 0.5
    while True:
        if shared.stop_event.is_set():
            return

        # Success when monitor emits MarkSuccess
        if getattr(shared, "success_event", None) and shared.success_event.is_set():
            return

        if time.time() - start > max_duration_s:
            shared.log(f"max_duration_s ({max_duration_s} sec) timeout reached, setting shared.stop_event")
            # timeout: let jobs.py classify as FAIL (stop_event triggers)
            shared.last_error = 'max duration exceeded'
            shared.stop_event.set()
            return
        
        found, data = robot.try_get_event("program_done", job_id=job_id, consume=False)
        if found:
            shared.log(f"received program_done event with data: {data}...")
            raise StopAutomation(f"received program_done event earlier than expected. data={data}...")
        
        if not is_on_keypad_page(meter):
            shared.log(f"No longer on keypad page... re-navigating to keypad page")
            meter.goto_keypad()


        check_stop_event(shared)
        time.sleep(poll)


