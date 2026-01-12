import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient


def test_robot_coin_shutter(meter: SSHMeter, shared: SharedState, **kwargs):
    """Enable coin shutter for robot visual inspection"""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 1, 1)

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_coin_shutter", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "charuco_frame": kwargs.get("charuco_frame")})

    robot.wait_for_event("taking_enabled_picture", job_id=job_id, timeout=40)
    meter.coin_shutter_hold_open(10)
    
    data = robot.wait_for_event("coin_shutter_results", job_id=job_id, timeout=20)
    shared.log("Coin shutter analysis data: %s" % data)
    shared.device_meta["coin_shutter"] = data # or: shared.device_meta.update(data)
    opened = data.get("opened")
    confidence = data.get("confidence")

    robot.wait_for_event("program_done", job_id=job_id, timeout=10)

    if opened is True:
        pass
    elif opened is False:
        raise StopAutomation(f"Coin shutter did not open: {data}")
    elif opened is None:
        raise StopAutomation(f"Coin shutter results are inconclusive: {data}")







