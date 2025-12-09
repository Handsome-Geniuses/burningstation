import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient


def test_robot_coin_shutter(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """Enable coin shutter for robot visual inspection"""
    func_name = inspect.currentframe().f_code.co_name

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_coin_shutter", {"meter_type": meter.meter_type, "meter_id": meter.hostname})
    # print(f"robot._event_queue: {robot._event_queue}")

    robot.wait_for_event("taking_enabled_picture", job_id=job_id, timeout=40)
    meter.coin_shutter_hold_open(10)
    
    event_data = robot.wait_for_event("coin_shutter_results", job_id=job_id, timeout=20)
    print("Coin shutter analysis results: %s" % event_data)

    event_data = robot.wait_for_event("program_done", job_id=job_id, timeout=10)
    # print("Program done: %s" % event_data)

    # print(f"robot._event_queue: {robot._event_queue}")






