import inspect
import time

from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.operator_feedback import (
    consume_operator_feedback_response,
    publish_operator_feedback,
)
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


# Repeat the endpoints only after walking smoothly through every intermediate
# brightness level in the opposite direction.
BRIGHTNESS_RAMP = (1, 33, 66, 99, 66, 33)
BRIGHTNESS_STEP_S = 0.5


def test_operator_display_brightness(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
):
    """Alternate display brightness until the operator confirms the change."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    max_duration_s = float(kwargs.get("max_duration_s", 60.0))

    if max_duration_s <= 0:
        raise ValueError("max_duration_s must be greater than zero")

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, 'display_brightness', 0, 1)

    stored_brightness = None
    success = False
    final_error = ""
    started_s = time.monotonic()
    brightness_step = 0

    try:
        check_stop_event(shared)
        stored_brightness = meter.get_brightness()
        shared.log(
            f"operator display brightness ready; stored brightness={stored_brightness!r}; "
            f"cycling smoothly through {list(BRIGHTNESS_RAMP)} while awaiting operator confirmation"
        )
        publish_operator_feedback(
            meter, shared,
            test="display_brightness",
            title="Display brightness test",
            instruction="Is the display brightness gradually changing from dim to bright and back?",
            status="awaiting_response",
            current=0, total=1,
            details={
                "low": 1,
                "high": 99,
                "ramp": list(BRIGHTNESS_RAMP),
                "stored_brightness": stored_brightness,
            },
        )

        while True:
            check_stop_event(shared)
            if time.monotonic() - started_s >= max_duration_s:
                raise StopAutomation(
                    f"display brightness confirmation timed out after {max_duration_s:.1f}s"
                )

            received, answer = consume_operator_feedback_response(
                shared, "display_brightness"
            )
            if received:
                if not answer:
                    raise StopAutomation(
                        "operator reported that the display brightness did not change"
                    )
                success = True
                shared.log("operator confirmed display brightness changes")
                if not subtest:
                    shared.broadcast_progress(meter.host, "display_brightness", 1, 1)
                break

            meter.set_brightness(BRIGHTNESS_RAMP[brightness_step])
            brightness_step = (brightness_step + 1) % len(BRIGHTNESS_RAMP)
            time.sleep(BRIGHTNESS_STEP_S)

    except Exception as exc:
        final_error = str(exc)
        shared.last_error = final_error
        device = getattr(shared, "current_device", None) or "display_brightness"
        shared.device_results[device] = "fail"
        raise
    finally:
        if stored_brightness is not None:
            try:
                meter.set_brightness(stored_brightness)
                shared.log(
                    f"operator display brightness restored to {stored_brightness!r}"
                )
            except Exception as exc:
                restore_error = f"failed to restore brightness: {exc}"
                final_error = "; ".join(part for part in (final_error, restore_error) if part)
                shared.last_error = final_error
                success = False
                shared.log(restore_error)

        device = getattr(shared, "current_device", None) or "display_brightness"
        shared.device_results[device] = "pass" if success else "fail"
        shared.device_meta["display_brightness"] = {
            "status": "pass" if success else "fail",
            "error": final_error,
            "duration_s": round(max(0.0, time.monotonic() - started_s), 3),
            "stored_brightness": stored_brightness,
        }
        publish_operator_feedback(
            meter, shared,
            test="display_brightness",
            title="Display brightness test",
            instruction="Display brightness has been restored.",
            status="pass" if success else "fail",
            current=1 if success else 0, total=1,
            details={"stored_brightness": stored_brightness},
            active=False,
            error=final_error,
        )

    if not success:
        raise StopAutomation(final_error or "display brightness test failed")
