import json
import re
import shlex
import time
import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter

# TODO: Add operator-facing touchscreen-test visuals, either as targets and
# completed regions on the meter or as instructions and progress feedback in
# the burningstation UI

JOURNAL_UNIT = "MS3_Platform.service"
JOURNAL_MAX_LINES = 1000
LOGICAL_TOUCH_WIDTH = 800
LOGICAL_TOUCH_HEIGHT = 480
PROGRESS_PROGRAM = "touchscreen"
TOUCH_RE = re.compile(
    r"Meter:sProcessWebKitMessage(?::\d+)?:\s*"
    r"Got touch:\s*at\s*\[\s*"
    r"(?P<x>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"(?P<y>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\]",
    re.IGNORECASE,
)


@dataclass
class OperatorTouchscreenRunState:
    expected_touch_count: int
    start_monotonic_s: float
    framebuffer_resolution: str = ""
    initial_journal_cursor: str = ""
    current_journal_cursor: str = ""
    touches: List[Dict[str, Any]] = field(default_factory=list)
    journal_poll_count: int = 0
    journal_entries_processed: int = 0
    success: bool = False
    final_error: str = ""


def _journal_message(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        try:
            return bytes(value).decode(errors="replace")
        except (TypeError, ValueError):
            pass
    return "" if value is None else str(value)


def _journal_timestamp_text(value: Any) -> str:
    try:
        epoch_us = int(value)
        return datetime.fromtimestamp(epoch_us / 1_000_000).isoformat(
            timespec="milliseconds"
        )
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value or "")


def _parse_journal_json_batch(text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for line_number, raw_line in enumerate((text or "").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid journal JSON on output line {line_number}: {exc.msg}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                f"journal JSON on output line {line_number} is not an object"
            )

        cursor = payload.get("__CURSOR")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError(
                f"journal JSON on output line {line_number} has no __CURSOR"
            )

        entries.append(
            {
                "cursor": cursor,
                "timestamp": _journal_timestamp_text(
                    payload.get("__REALTIME_TIMESTAMP")
                ),
                "message": _journal_message(payload.get("MESSAGE")),
            }
        )
    return entries


def _initial_journal_cursor(meter: SSHMeter) -> str:
    command = f"journalctl -u {JOURNAL_UNIT} -n 1 --no-pager -o json"
    try:
        code, output, error = meter.exec_parse(command)
    except Exception as exc:
        raise RuntimeError(f"initial journal cursor command failed: {exc}") from exc
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"initial journal cursor command failed: {detail}")

    entries = _parse_journal_json_batch(output)
    if not entries:
        raise RuntimeError(
            f"no entries found for {JOURNAL_UNIT}; cannot establish a safe journal cursor"
        )
    return entries[-1]["cursor"]


def _journal_after_cursor_command(cursor: str) -> str:
    return (
        f"journalctl -u {JOURNAL_UNIT} --after-cursor={shlex.quote(cursor)} "
        f"--lines={JOURNAL_MAX_LINES} --no-pager -o json"
    )


def _framebuffer_resolution(meter: SSHMeter) -> str:
    command = "fbset -s | grep mode | awk -F'\"' '{print $2}' | cut -d- -f1"
    try:
        return str(meter.cli(command) or "").strip()
    except Exception as exc:
        return f"unavailable ({exc})"


def _physical_touch_coordinates(
    logical_x: float,
    logical_y: float,
    meter_type: str,
) -> tuple[float, float]:
    """Map the meter's 800x480 touch space into physical screen coordinates."""
    if str(meter_type or "").strip().lower() == "msx":
        return (
            logical_y / LOGICAL_TOUCH_HEIGHT,
            1.0 - (logical_x / LOGICAL_TOUCH_WIDTH),
        )
    return (
        logical_x / LOGICAL_TOUCH_WIDTH,
        logical_y / LOGICAL_TOUCH_HEIGHT,
    )


def _poll_touchscreen_presses(
    meter: SSHMeter,
    state: OperatorTouchscreenRunState,
) -> List[Dict[str, Any]]:
    state.journal_poll_count += 1
    command = _journal_after_cursor_command(state.current_journal_cursor)
    try:
        code, output, error = meter.exec_parse(command)
    except Exception as exc:
        raise RuntimeError(f"touchscreen journal poll failed: {exc}") from exc
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"touchscreen journal poll failed: {detail}")

    entries = _parse_journal_json_batch(output)
    if not entries:
        return []

    new_touches: List[Dict[str, Any]] = []
    meter_type = str(getattr(meter, "meter_type", "") or "")
    for entry in entries:
        match = TOUCH_RE.search(entry["message"])
        if not match:
            continue
        logical_x = float(match.group("x"))
        logical_y = float(match.group("y"))
        physical_x, physical_y = _physical_touch_coordinates(
            logical_x,
            logical_y,
            meter_type,
        )
        new_touches.append(
            {
                "x": logical_x,
                "y": logical_y,
                "physical_x": physical_x,
                "physical_y": physical_y,
                "cursor": entry["cursor"],
                "timestamp": entry["timestamp"],
                "message": entry["message"],
            }
        )

    # Advance only after the entire JSON batch parses successfully.
    state.current_journal_cursor = entries[-1]["cursor"]
    state.journal_entries_processed += len(entries)
    return new_touches


def _fail_touchscreen(
    shared: SharedState,
    state: OperatorTouchscreenRunState,
    message: str,
) -> None:
    state.final_error = message
    shared.last_error = message
    device = getattr(shared, "current_device", None) or "touchscreen"
    shared.device_results[device] = "fail"
    shared.log(message)
    shared.stop_event.set()
    raise StopAutomation(message)


def _write_touchscreen_metadata(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorTouchscreenRunState,
) -> None:
    elapsed_s = max(0.0, time.monotonic() - state.start_monotonic_s)
    meta = shared.device_meta.setdefault("touchscreen", {})
    meta.clear()
    meta.update(
        {
            "status": "pass" if state.success else "fail",
            "error": state.final_error or shared.last_error or "",
            "expected_touch_count": state.expected_touch_count,
            "touch_count": len(state.touches),
            "duration_s": round(elapsed_s, 3),
        }
    )


def test_operator_touchscreen(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
) -> None:
    """Collect five touchscreen presses and record logical and physical coordinates."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    max_duration_s = float(kwargs.get("max_duration_s", 60.0))
    poll_s = float(kwargs.get("poll_s", 0.5))
    job_count = int(kwargs.get("job_count", 1))
    expected_touch_count = int(
        kwargs.get("expected_touch_count", 5 * max(job_count, 1))
    )

    if max_duration_s <= 0:
        raise ValueError(
            "test_operator_touchscreen requires max_duration_s to be greater than zero"
        )
    if poll_s <= 0:
        raise ValueError("test_operator_touchscreen requires poll_s to be greater than zero")
    if expected_touch_count <= 0:
        raise ValueError(
            "test_operator_touchscreen requires expected_touch_count to be greater than zero"
        )

    state = OperatorTouchscreenRunState(
        expected_touch_count=expected_touch_count,
        start_monotonic_s=time.monotonic(),
    )

    shared.log(f"{meter.host} {func_name} 1/1")
    shared.log(
        f"{meter.host} test_operator_touchscreen | "
        f"expected_touch_count={expected_touch_count} | "
        f"max_duration_s={max_duration_s:.1f} | poll_s={poll_s:.2f}"
    )
    if not subtest:
        shared.broadcast_progress(
            meter.host,
            PROGRESS_PROGRAM,
            0,
            expected_touch_count,
        )

    try:
        check_stop_event(shared)
        meter.force_diagnostics()
        check_stop_event(shared)

        cursor = _initial_journal_cursor(meter)
        state.initial_journal_cursor = cursor
        state.current_journal_cursor = cursor
        state.framebuffer_resolution = _framebuffer_resolution(meter)
        shared.log(
            f"operator touchscreen initialized | meter_type={meter.meter_type} | "
            f"framebuffer={state.framebuffer_resolution} | "
            f"logical_touch_space={LOGICAL_TOUCH_WIDTH}x{LOGICAL_TOUCH_HEIGHT} | "
            f"journal_max_lines={JOURNAL_MAX_LINES} | "
            f"cursor={cursor}"
        )

        while True:
            check_stop_event(shared)
            elapsed_s = time.monotonic() - state.start_monotonic_s
            if elapsed_s >= max_duration_s:
                _fail_touchscreen(
                    shared,
                    state,
                    f"max duration exceeded ({max_duration_s:.1f}s); "
                    f"captured {len(state.touches)}/{expected_touch_count} touches",
                )

            new_touches = _poll_touchscreen_presses(meter, state)
            for touch in new_touches:
                state.touches.append(touch)
                touch_number = len(state.touches)
                shared.log(
                    f"[operator touchscreen] touch {touch_number}/"
                    f"{expected_touch_count}: x={touch['x']:.6f}, "
                    f"y={touch['y']:.6f} | "
                    f"physical_x={touch['physical_x']:.6f}, "
                    f"physical_y={touch['physical_y']:.6f} | "
                    f"{touch['timestamp']}"
                )
                if not subtest:
                    shared.broadcast_progress(
                        meter.host,
                        PROGRESS_PROGRAM,
                        min(touch_number, expected_touch_count),
                        expected_touch_count,
                    )

            if len(state.touches) >= expected_touch_count:
                state.success = True
                device = getattr(shared, "current_device", None) or "touchscreen"
                shared.device_results[device] = "pass"
                shared.log(
                    f"operator touchscreen captured {len(state.touches)} "
                    f"touches; coordinate collection complete"
                )
                return

            time.sleep(poll_s)

    except Exception as exc:
        if not state.final_error:
            state.final_error = str(exc)
        if not getattr(shared, "last_error", None):
            shared.last_error = state.final_error
        device = getattr(shared, "current_device", None) or "touchscreen"
        shared.device_results[device] = "fail"
        raise
    finally:
        _write_touchscreen_metadata(meter, shared, state)
        shared.log(
            f"operator touchscreen final summary: success={state.success} | "
            f"error={state.final_error!r} | touches={len(state.touches)}/"
            f"{state.expected_touch_count} | duration_s="
            f"{shared.device_meta['touchscreen']['duration_s']} | "
            f"journal_polls={state.journal_poll_count} | "
            f"journal_entries={state.journal_entries_processed}"
        )
        shared.log(
            f"operator touchscreen final details: meter_type={meter.meter_type} | "
            f"framebuffer={state.framebuffer_resolution} | "
            f"logical_touch_space={LOGICAL_TOUCH_WIDTH}x{LOGICAL_TOUCH_HEIGHT} | "
            f"journal_max_lines={JOURNAL_MAX_LINES} | "
            f"initial_cursor={state.initial_journal_cursor!r} | "
            f"current_cursor={state.current_journal_cursor!r}"
        )
        for index, touch in enumerate(state.touches, start=1):
            shared.log(f"operator touchscreen touch {index}: {touch}")
        if not state.touches:
            shared.log("operator touchscreen touch: none")
