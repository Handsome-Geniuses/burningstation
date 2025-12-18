import time
import inspect

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import StopAutomation
from lib.automation.tests.test_solar import test_solar
from lib.automation.tests.test_robot_coin_shutter import test_robot_coin_shutter
from lib.automation.tests.test_robot_nfc_read import test_robot_nfc_read
from lib.automation.tests.test_robot_keypad import test_robot_keypad
from lib.robot.robot_client import RobotClient


PHYSICAL_DEVICES = [
    ("solar",          test_solar, {}),
    ("coin_shutter",   test_robot_coin_shutter, {}),
    ("nfc",            test_robot_nfc_read,     {}),
    ("robot_keypad",   test_robot_keypad,       {
        "buttons": ["1","2","3"],
        "inactivity_timeout_s": 40.0,
        "per_button_timeout_s": 25.0,
    }),
]

    
def run_and_retrieve_charuco(robot: RobotClient, meter: SSHMeter, wait_timeout):
    robot.wait_until_ready(wait_timeout)

    meter.set_ui_mode("charuco")
    job_id = robot.run_program("run_find_meter", args={"meter_type": meter.meter_type, "meter_id": meter.hostname})

    robot.wait_for_event("program_done", job_id=job_id, timeout=20)

    data = robot.send_command("get_charuco_frame")
    charuco_frame = data.get("charuco_frame", None)
    print(f"charuco_frame to use for runs: {charuco_frame}")
    return charuco_frame


#! need to clean this up but im too lazy rn
def physical_cycle_all(
    meter: SSHMeter,
    shared: SharedState = None,
    **kwargs
):
    """
    Main entry point — registered as "physical_cycle_all" in PROGRAM_REGISTRY
    """
    func_name = inspect.currentframe().f_code.co_name
    burn_count = int(kwargs.get("numBurnCycles", 1))
    burn_delay = int(kwargs.get("numBurnDelay", 5))
    robot_ready_timeout = float(kwargs.get("robot_ready_timeout", 30.0))

    # print(f"\n{'='*60}")
    # print(f"STARTING PHYSICAL CYCLE ALL @ {meter.host}")
    # print(f"  → burn_count: {burn_count} | burn_delay: {burn_delay}s")
    # print(f"  → kwargs keys: {list(kwargs.keys())}")
    # if "monitors" in kwargs:
    #     print(f"  → monitors override: {[dev for dev,_ in kwargs['monitors']]}")
    # print(f"{'='*60}\n")

    # Initialize results
    if shared:
        shared.device_results.update({name: "pending" for name, _, _ in PHYSICAL_DEVICES})
        # print(f"[INIT] device_results initialized: {list(shared.device_results.keys())}")

    robot = RobotClient()
    charuco_frame = run_and_retrieve_charuco(robot, meter, robot_ready_timeout)

    for cycle in range(burn_count):
        print(f"{meter.host} {func_name} — Cycle {cycle + 1}/{burn_count}")
        if shared:
            shared.broadcast_progress(meter.host, "physical_cycle", cycle + 1, burn_count)

        for device_name, test_func, default_cfg in PHYSICAL_DEVICES:
            if shared and shared.stop_event.is_set():
                # print(f"STOP EVENT DETECTED — ABORTING CYCLE")
                return

            # Config resolution
            cfg = kwargs.get(device_name, {})
            if isinstance(cfg, dict):
                enabled = cfg.get("enabled", True)
                custom_cfg = {k: v for k, v in cfg.items() if k != "enabled"}
            else:
                enabled = bool(cfg)
                custom_cfg = {}

            print(f"\n→ Processing device: {device_name}")
            print(f"   enabled: {enabled} | config: {custom_cfg or default_cfg}")

            if not enabled:
                print(f"   → SKIPPED (disabled)")
                if shared:
                    shared.device_results[device_name] = "n/a"
                continue

            # Hardware presence check
            missing = False
            if device_name == "coin_shutter" and not meter.device_firmware("coin shutter"):
                # print(f"   → MISSING HARDWARE (coin shutter)")
                missing = True
            if device_name == "nfc" and not meter.device_firmware("nfc"):
                # print(f"   → MISSING HARDWARE (nfc)")
                missing = True

            if missing:
                if shared:
                    shared.device_results[device_name] = "missing"
                continue

            robot.wait_until_ready(robot_ready_timeout)

            if shared:
                shared.current_device = device_name
                shared.device_results[device_name] = "running"
                print(f"   → STATUS: running | current_device = {device_name}")

                if device_name in {"nfc", "robot_keypad"}:
                    shared.set_allowed({device_name}, reason=f"Running {device_name}")
                    # print(f"   → set_allowed({{'{device_name}'}}) — monitor active")
                else:
                    shared.set_allowed(set(), reason=f"No monitor for {device_name}")
                    # print(f"   → set_allowed(set()) — no monitor")

            try:
                final_kwargs = {**default_cfg, **custom_cfg}
                final_kwargs["subtest"] = True
                final_kwargs["charuco_frame"] = charuco_frame

                print(f"   → Calling {test_func.__name__}() with kwargs:")
                for k, v in final_kwargs.items():
                    print(f"       • {k}: {v}")

                test_func(meter, shared=shared, **final_kwargs)

                if shared and not shared.stop_event.is_set():
                    shared.device_results[device_name] = "pass"
                    print(f"   → PASSED")

            except StopAutomation:
                print(f"   → FAIL (StopAutomation)")
                if shared:
                    shared.device_results[device_name] = "fail"
                raise
            except Exception as e:
                print(f"   → FAIL: {e}")
                if shared:
                    shared.device_results[device_name] = "fail"
                    shared.last_error = str(e)
                raise
            finally:
                if shared:
                    shared.current_device = None
                    shared.set_allowed(set(), reason="Subtest complete")
                    print(f"   → Monitor reset (set_allowed empty)")

        # print(f"\nCYCLE {cycle + 1} COMPLETE — waiting {burn_delay}s...")
        time.sleep(burn_delay)

    print(f"\n{'='*60}")
    print(f"PHYSICAL CYCLE ALL FINISHED @ {meter.host}")
    print(f"Final results: {shared.device_results if shared else 'N/A'}")
    print(f"{'='*60}\n")

    if not meter.in_diagnostics():
        meter.press("diagnostics")
