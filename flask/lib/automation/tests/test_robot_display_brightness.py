import inspect

from lib.automation.helpers import check_stop_event, StopAutomation
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter
from lib.robot.robot_client import RobotClient


# TODO: Would be nice to pass the shared.logfile name and current func_name with every robot run program call. For easier alignment of system logs
# TODO: Could also optimize the back and forth waiting with better and more direct actions/handoffs rather than just blindly waiting


_BRIGHTNESS_VALUES = {
    "ms2.5": {"low": 1, "high": 99},
    "ms3": {"low": 1, "high": 99},
    "msx": {"low": 99, "high": 1},
}
_MIN_CONFIDENCE = 0.8


def _get_display_brightness(meter: SSHMeter, level: str) -> int:
    """Return the meter-specific setting for a low or high display level."""
    normalized_level = str(level).strip().lower()
    if normalized_level not in ("low", "high"):
        raise ValueError("Display brightness level must be 'low' or 'high'")

    meter_type = str(meter.meter_type).strip().lower()
    try:
        return _BRIGHTNESS_VALUES[meter_type][normalized_level]
    except KeyError:
        raise ValueError(
            f"Unsupported meter type for display brightness test: {meter.meter_type}"
        ) from None


def _get_display_brightness_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("display_brightness", {})


def _get_result_verdict(data) -> tuple[str, str]:
    """Return a verdict and explanation for a low-to-high image comparison."""
    if not isinstance(data, dict):
        return "fail", "robot did not return display brightness result data"

    brightness_change = data.get("brightness_change")
    confidence = data.get("confidence")
    reasons = []

    if brightness_change != "increased":
        reasons.append(
            f"brightness_change was {brightness_change!r}, expected 'increased'"
        )

    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        reasons.append(f"confidence was missing or invalid ({confidence!r})")
    elif confidence <= _MIN_CONFIDENCE:
        reasons.append(
            f"confidence {confidence:.3f} was not greater than {_MIN_CONFIDENCE:.1f}"
        )

    if reasons:
        return "fail", "; ".join(reasons)

    return "pass", (
        f"display brightness increased with {confidence:.3f} confidence"
    )


def test_robot_display_brightness(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
):
    """Verify a low-to-high display brightness change using the robot camera."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    job_count = int(kwargs.get("job_count", 1))
    robot = RobotClient()

    if kwargs.get("charuco_frame") is None:
        meter.set_ui_mode("charuco")
    else:
        meter.set_ui_mode("banner")

    stored_brightness = meter.get_brightness()
    display_brightness_meta = _get_display_brightness_meta(shared)
    display_brightness_meta.clear()
    display_brightness_meta.update(
        {
            "status": "running",
            "error": None,
            "cycles": {},
        }
    )
    current_cycle_meta = None
    test_error = None

    try:
        for i in range(job_count):
            cycle_num = i + 1
            shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
            if not subtest:
                shared.broadcast_progress(
                    meter.host, "display_brightness", cycle_num, job_count
                )

            low_brightness = _get_display_brightness(meter, "low")
            high_brightness = _get_display_brightness(meter, "high")
            current_cycle_meta = {
                "status": "running",
                "brightness_change": None,
                "confidence": None,
            }
            display_brightness_meta["cycles"][cycle_num] = current_cycle_meta

            meter.set_brightness(low_brightness)
            job_id = robot.run_program(
                "run_display_brightness",
                {
                    "meter_type": meter.meter_type,
                    "meter_id": meter.hostname,
                    "charuco_frame": kwargs.get("charuco_frame"),
                },
            )

            robot.wait_for_event(
                "low_brightness_pic_captured", job_id=job_id, timeout=40
            )
            meter.set_brightness(high_brightness)

            data = robot.wait_for_event(
                "display_brightness_results", job_id=job_id, timeout=20
            )
            verdict, verdict_reason = _get_result_verdict(data)
            warnings = data.get("warnings") if isinstance(data, dict) else None
            current_cycle_meta.update(
                {
                    "status": verdict,
                    "brightness_change": (
                        data.get("brightness_change")
                        if isinstance(data, dict)
                        else None
                    ),
                    "confidence": (
                        data.get("confidence") if isinstance(data, dict) else None
                    ),
                }
            )
            if warnings:
                current_cycle_meta["warnings"] = warnings
            shared.log(
                "Display brightness results data (%d/%d): %s"
                % (cycle_num, job_count, data)
            )

            robot.wait_for_event("program_done", job_id=job_id, timeout=10)

            if verdict == "fail":
                display_brightness_meta.update(
                    {
                        "status": "fail",
                        "error": verdict_reason,
                    }
                )
                raise StopAutomation(
                    f"Display brightness test failed ({cycle_num}/{job_count}): "
                    f"{verdict_reason}"
                )

            check_stop_event(shared)

        display_brightness_meta.update(
            {
                "status": "pass",
                "error": None,
            }
        )
    except Exception as exc:
        test_error = exc
        if current_cycle_meta is not None and current_cycle_meta["status"] == "running":
            current_cycle_meta["status"] = "error"
        if display_brightness_meta["status"] == "running":
            display_brightness_meta.update(
                {
                    "status": "error",
                    "error": str(exc),
                }
            )
        shared.log(f"{meter.host} {func_name} stopped: {exc}")
        raise
    finally:
        try:
            meter.set_brightness(stored_brightness)
            shared.log(
                f"{meter.host} {func_name} restored display brightness to "
                f"{stored_brightness}"
            )
        except Exception as restore_error:
            shared.log(
                f"{meter.host} {func_name} could not restore display brightness "
                f"to {stored_brightness}: {restore_error}"
            )
            restore_message = f"failed to restore brightness: {restore_error}"
            existing_error = display_brightness_meta.get("error")
            display_brightness_meta["error"] = (
                f"{existing_error}; {restore_message}"
                if existing_error
                else restore_message
            )
            if display_brightness_meta["status"] == "pass":
                display_brightness_meta["status"] = "error"
            shared.log(
                f"{meter.host} {func_name} final metadata: "
                f"{display_brightness_meta}"
            )
            if test_error is None:
                raise
        else:
            shared.log(
                f"{meter.host} {func_name} final metadata: "
                f"{display_brightness_meta}"
            )
