import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient


def _get_coin_shutter_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("coin_shutter", {})


def test_robot_coin_shutter(meter: SSHMeter, shared: SharedState, **kwargs):
    """Enable coin shutter for robot visual inspection"""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    job_count = int(kwargs.get("job_count", 1))
    robot = RobotClient()

    if kwargs.get("charuco_frame") is None:
        meter.set_ui_mode("charuco")
    else:
        meter.set_ui_mode("banner")

    for i in range(job_count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'coin_shutter', cycle_num, job_count)

        job_id = robot.run_program("run_coin_shutter", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "charuco_frame": kwargs.get("charuco_frame")})

        robot.wait_for_event("taking_enabled_picture", job_id=job_id, timeout=40)
        meter.coin_shutter_hold_open(10)

        data = robot.wait_for_event("coin_shutter_results", job_id=job_id, timeout=20)
        shared.log("Coin shutter analysis data (%d/%d): %s" % (cycle_num, job_count, data))
        coin_shutter_meta = _get_coin_shutter_meta(shared)
        coin_shutter_meta[cycle_num] = data
        opened = data.get("opened")
        confidence = data.get("confidence")

        robot.wait_for_event("program_done", job_id=job_id, timeout=10)

        if opened is True:
            pass
        elif opened is False:
            raise StopAutomation(f"Coin shutter did not open ({cycle_num}/{job_count}): {data}")
        elif opened is None:
            raise StopAutomation(f"Coin shutter results are inconclusive ({cycle_num}/{job_count}): {data}")

        check_stop_event(shared)







