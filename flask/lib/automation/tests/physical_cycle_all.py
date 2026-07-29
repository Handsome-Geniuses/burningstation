import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import StopAutomation
from lib.automation.tests.test_solar import test_solar
from lib.automation.tests.test_robot_coin_shutter import test_robot_coin_shutter
from lib.automation.tests.cycle_meter_ui import test_cycle_meter_ui
from lib.automation.tests.test_robot_keypad import test_robot_keypad
from lib.robot.robot_client import RobotClient


PHYSICAL_DEVICES = [
    ("solar",          test_solar, {}),
    ("coin_shutter",   test_robot_coin_shutter, {}),
    ### ("nfc",            test_robot_nfc_read,     {}),
    ("nfc_gui",        test_cycle_meter_ui,     {"payment_type": "robot_contactless"}),
    ("robot_keypad",   test_robot_keypad,       {
        "buttons": ["1","2","3"],
        "per_button_timeout_s": 5.0,
    }),
]

PHYSICAL_CYCLE_GLOBAL_KEYS = {
    "numBurnCycles",
    "numBurnDelay",
    "monitors",
    "broadcast_job",
    "robot_ready_timeout",
}


def _device_key_variants(device: str):
    return tuple(dict.fromkeys((device, device.replace("_", " "), device.replace(" ", "_"))))


def _physical_cycle_shared_kwargs(kwargs):
    reserved = set(PHYSICAL_CYCLE_GLOBAL_KEYS)
    for device_name, _, _ in PHYSICAL_DEVICES:
        reserved.update(_device_key_variants(device_name))

    return {k: v for k, v in kwargs.items() if k not in reserved}


def _coerce_job_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is not a valid job_count")


def _resolve_subtest_kwargs(device: str, kwargs, default_cfg=None):
    shared_kwargs = _physical_cycle_shared_kwargs(kwargs)
    default_cfg = dict(default_cfg or {})

    cfg = None
    for key in _device_key_variants(device):
        if key in kwargs:
            cfg = kwargs[key]
            break

    if cfg is None:
        raise KeyError(f"Missing subtest config for {device!r}")
    if not isinstance(cfg, dict):
        raise TypeError(f"Subtest config for {device!r} must be a dict, got {type(cfg).__name__}")
    if "job_count" not in cfg:
        raise KeyError(f"Subtest config for {device!r} is missing job_count")

    job_count = _coerce_job_count(cfg["job_count"])
    if job_count <= 0:
        return False, {}

    custom_cfg = {k: v for k, v in cfg.items() if k != "job_count"}
    return True, {
        **shared_kwargs,
        **default_cfg,
        **custom_cfg,
        "job_count": job_count,
    }


def run_and_retrieve_charuco(robot: RobotClient, meter: SSHMeter, shared: SharedState, wait_timeout):
    robot.wait_until_ready(wait_timeout)

    meter.set_ui_mode("charuco")
    job_id = robot.run_program("run_find_meter", args={"meter_type": meter.meter_type, "meter_id": meter.hostname})

    robot.wait_for_event("program_done", job_id=job_id, timeout=20)

    data = robot.send_command("get_charuco_frame")
    charuco_frame = data.get("charuco_frame", None)
    shared.log(f"charuco_frame to use for runs: {charuco_frame}")

    if charuco_frame is not None:
        meter.set_ui_mode("banner")

    # job_id = robot.run_program("run_button_pic", args={"meter_type": meter.meter_type, "button_name": "i", "charuco_frame": charuco_frame})
    # robot.wait_for_event("program_done", job_id=job_id, timeout=20)
    return charuco_frame


def physical_cycle_all(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs
):
    """
    Main entry point — registered as "physical_cycle_all" in PROGRAM_REGISTRY
    """
    func_name = inspect.currentframe().f_code.co_name
    burn_count = int(kwargs.get("numBurnCycles", 1))
    burn_delay = int(kwargs.get("numBurnDelay", 5))
    robot_ready_timeout = float(kwargs.get("robot_ready_timeout", 30.0))

    # if "monitors" in kwargs:
    #     shared.log(f"monitors override: {[dev for dev,_ in kwargs['monitors']]}")

    # Initialize results
    shared.device_results.update({name: "pending" for name, _, _ in PHYSICAL_DEVICES})

    robot = RobotClient()
    charuco_frame = run_and_retrieve_charuco(robot, meter, shared, robot_ready_timeout)

    for cycle in range(burn_count):
        cycle_num = cycle + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{burn_count}")
        shared.broadcast_progress(meter.host, "physical_cycle", cycle_num, burn_count)

        for device_name, test_func, default_cfg in PHYSICAL_DEVICES:
            if shared.stop_event.is_set():
                return

            should_run, final_kwargs = _resolve_subtest_kwargs(device_name, kwargs, default_cfg=default_cfg)
            if not should_run:
                shared.log(f"skipping {device_name} subtest: job_count <= 0")
                shared.device_results[device_name] = "n/a"
                continue

            # Hardware presence check #
            missing = False
            if device_name == "coin_shutter" and not meter.device_firmware("coin shutter"):
                missing = True
            elif device_name == "nfc_gui":
                payment_type = str(final_kwargs.get("payment_type", "")).strip().lower()
                if payment_type == "robot_contactless" and not meter.device_firmware("nfc"):
                    missing = True

            if missing:
                shared.log(f"skipping {device_name} subtest: missing hardware")
                shared.device_results[device_name] = "missing"
                continue

            robot.wait_until_ready(robot_ready_timeout)

            shared.current_device = device_name
            shared.device_results[device_name] = "running"
            shared.set_allowed(set(), reason=f"No monitor for {device_name}")

            try:
                final_kwargs["subtest"] = True
                final_kwargs["charuco_frame"] = charuco_frame

                test_func(meter, shared=shared, **final_kwargs)

                if not shared.stop_event.is_set():
                    shared.device_results[device_name] = "pass"

            except StopAutomation as e:
                shared.log(f"{device_name} subtest fail due to StopAutomation")
                shared.device_results[device_name] = "fail"
                shared.last_error = str(e)

                try:
                    robot.send_command("abort_program")
                    shared.log("Robot program aborted due to subtest failure")
                except Exception as abort_e:
                    shared.log(f"Failed to abort robot program: {abort_e}")

                raise e
            
            except Exception as e:
                shared.log(f"{device_name} subtest fail due to {e}")
                shared.device_results[device_name] = "fail"
                shared.last_error = str(e)

                try:
                    robot.send_command("abort_program")
                    shared.log("Robot program aborted due to subtest failure")
                except Exception as abort_e:
                    shared.log(f"Failed to abort robot program: {abort_e}")

                raise e

            finally:
                shared.current_device = None
                shared.set_allowed(set(), reason="Subtest complete")

        time.sleep(burn_delay)

    # shared.log(f"Final results: {shared.device_results}")
    if not meter.in_diagnostics():
        meter.press("diagnostics")
