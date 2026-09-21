import inspect
import json
import re
import shlex
import time
import requests

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter
from lib.sse.sse_queue_manager import SSEQM

# TODO: Add keypad press visuals on burningstation UI. Potentially require buttons to be pressed in a specific order

# Keep flask/lib/docs/meter/test_operator_keypad.md in sync when changing this test.
KEYPAD_PAGE = "Service:Utilities:Peripherals:Keyboard"
JOURNAL_UNIT = "MS3_Platform.service"
ALLOWED_KEYPAD_SOURCES = {"KEY_PAD_2", "KBD_CONTROLLER"}
KBD_CONTROLLER_BUTTON_REMAP = {
    # Current meters report the outer KBD-controller buttons opposite the
    # physical legends: raw HELP is the left globe/MAX key, raw MAX is help.
    "HELP": "MAX",
    "MAX": "HELP",
}
KEY_PRESSED_RE = re.compile(
    r"KEY_PRESSED:\s*(?P<key>[^,]+),\s*isAutoRepeat=(?P<auto_repeat>true|false),\s*from\s+(?P<source>\S+)",
    re.IGNORECASE,
)


@dataclass
class OperatorKeypadRunState:
    expected_buttons: List[str]
    required_per_button: int
    start_epoch_s: float
    start_monotonic_s: float
    initial_journal_cursor: str = ""
    current_journal_cursor: str = ""
    confirmed_counts: Dict[str, int] = field(default_factory=dict)
    accepted_presses: List[Dict[str, Any]] = field(default_factory=list)
    ignored_presses: List[Dict[str, Any]] = field(default_factory=list)
    ignored_presses_dropped: int = 0
    journal_poll_count: int = 0
    journal_entries_processed: int = 0
    journal_read_error_count: int = 0
    journal_consecutive_read_errors: int = 0
    journal_last_error: str = ""
    success: bool = False
    final_error: str = ""

    def __post_init__(self) -> None:
        self.confirmed_counts = {button: 0 for button in self.expected_buttons}


def _normalize_button(value: Any) -> str:
    return str(value or "").strip().upper()


def _canonical_keypad_button(button: Any, source: Any) -> str:
    normalized = _normalize_button(button)
    if _normalize_button(source) == "KBD_CONTROLLER":
        return KBD_CONTROLLER_BUTTON_REMAP.get(normalized, normalized)
    return normalized


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
        return datetime.fromtimestamp(epoch_us / 1_000_000).isoformat(timespec="milliseconds")
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
            raise ValueError(f"journal JSON on output line {line_number} is not an object")

        cursor = payload.get("__CURSOR")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError(f"journal JSON on output line {line_number} has no __CURSOR")

        message = _journal_message(payload.get("MESSAGE"))
        entries.append(
            {
                "cursor": cursor,
                "timestamp": _journal_timestamp_text(payload.get("__REALTIME_TIMESTAMP")),
                "message": message,
                "raw": raw_line,
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
        "--no-pager -o json"
    )


def _append_ignored_press(
    state: OperatorKeypadRunState,
    press_data: Dict[str, Any],
    limit: int,
) -> None:
    if len(state.ignored_presses) < limit:
        state.ignored_presses.append(press_data)
    else:
        state.ignored_presses_dropped += 1


def _poll_keypad_presses(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorKeypadRunState,
    *,
    debug_entry_limit: int,
    debug_keypad: bool,
) -> int:
    state.journal_poll_count += 1
    command = _journal_after_cursor_command(state.current_journal_cursor)

    try:
        code, output, error = meter.exec_parse(command)
        if code != 0:
            detail = str(error or output or f"exit code {code}").strip()
            raise RuntimeError(detail)
        entries = _parse_journal_json_batch(output)
    except Exception as exc:
        message = f"journal poll failed: {exc}"
        state.journal_read_error_count += 1
        state.journal_consecutive_read_errors += 1
        if message != state.journal_last_error or state.journal_consecutive_read_errors == 1:
            shared.log(message)
        state.journal_last_error = message
        return 0

    if state.journal_consecutive_read_errors:
        shared.log("operator keypad journal acquisition recovered")
    state.journal_consecutive_read_errors = 0

    if not entries:
        return 0

    accepted = 0
    for entry in entries:
        match = KEY_PRESSED_RE.search(entry["message"])
        if not match:
            continue

        raw_button = _normalize_button(match.group("key"))
        source = _normalize_button(match.group("source"))
        button = _canonical_keypad_button(raw_button, source)
        auto_repeat = match.group("auto_repeat").lower() == "true"
        press_data = {
            "button": button,
            "source": source,
            "auto_repeat": auto_repeat,
            "cursor": entry["cursor"],
            "timestamp": entry["timestamp"],
            "message": entry["message"],
        }
        if raw_button != button:
            press_data["raw_button"] = raw_button

        ignore_reason = ""
        if auto_repeat:
            ignore_reason = "auto-repeat=true"
        elif source not in ALLOWED_KEYPAD_SOURCES:
            ignore_reason = f"unexpected source={source}"
        elif button not in state.confirmed_counts:
            ignore_reason = "button not requested"

        if ignore_reason:
            press_data["reason"] = ignore_reason
            _append_ignored_press(state, press_data, debug_entry_limit)
            if debug_keypad:
                shared.log(f"ignored keypad press: {press_data}")
            continue

        state.confirmed_counts[button] += 1
        press_data["count"] = state.confirmed_counts[button]
        state.accepted_presses.append(press_data)
        accepted += 1
        shared.log(
            f"operator keypad press {button}: "
            f"{state.confirmed_counts[button]}/{state.required_per_button} from {source}"
        )

    # Advance only after the complete output batch has parsed successfully.
    state.current_journal_cursor = entries[-1]["cursor"]
    state.journal_entries_processed += len(entries)
    return accepted


def _is_on_keypad_page(meter: SSHMeter, timeout_s: float) -> bool:
    return KEYPAD_PAGE in meter.get_ui_page_html(timeout=timeout_s)


def _all_buttons_satisfied(state: OperatorKeypadRunState) -> bool:
    return all(
        count >= state.required_per_button
        for count in state.confirmed_counts.values()
    )


def _missing_buttons(state: OperatorKeypadRunState) -> Dict[str, int]:
    return {
        button: state.required_per_button - count
        for button, count in state.confirmed_counts.items()
        if count < state.required_per_button
    }


def _broadcast_keypad_state(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorKeypadRunState,
) -> None:
    completed = sum(
        min(count, state.required_per_button)
        for count in state.confirmed_counts.values()
    )
    total = len(state.expected_buttons) * state.required_per_button
    latest_button = (
        state.accepted_presses[-1]["button"]
        if state.accepted_presses
        else None
    )
    payload = {
        "ip": meter.host,
        "expected_buttons": list(state.expected_buttons),
        "counts": dict(state.confirmed_counts),
        "required_per_button": state.required_per_button,
        "latest_button": latest_button,
        "missing": _missing_buttons(state),
        "current": completed,
        "total": total,
    }
    shared.extras["operator_keypad_state"] = payload
    shared.broadcast_progress(meter.host, "operator_keypad", completed, total)
    SSEQM.broadcast("operator_keypad", payload)


def _fail_keypad(shared: SharedState, state: OperatorKeypadRunState, message: str) -> None:
    state.final_error = message
    shared.last_error = message
    device = getattr(shared, "current_device", None) or "keypad"
    shared.device_results[device] = "fail"
    shared.log(message)
    shared.stop_event.set()
    raise StopAutomation(message)


def _write_keypad_metadata(shared: SharedState, state: OperatorKeypadRunState) -> None:
    elapsed_s = max(0.0, time.monotonic() - state.start_monotonic_s)
    meta = shared.device_meta.setdefault("keypad", {})
    meta.clear()
    meta.update(
        {
            "status": "pass" if state.success else "fail",
            "error": state.final_error or shared.last_error or "",
            "expected_buttons": list(state.expected_buttons),
            "required_per_button": state.required_per_button,
            "confirmed_counts": dict(state.confirmed_counts),
            "missing": _missing_buttons(state),
            "duration_s": round(elapsed_s, 3),
        }
    )


def test_operator_keypad(meter: SSHMeter, shared: SharedState, **kwargs):
    """Validate operator key presses using only the meter's incremental journal."""
    func_name = inspect.currentframe().f_code.co_name
    raw_buttons = list(kwargs.get("buttons") or [])
    max_duration_s = float(kwargs.get("max_duration_s", 300.0))
    subtest = bool(kwargs.get("subtest", False))
    job_count = int(kwargs.get("job_count", 1))
    poll_s = float(kwargs.get("poll_s", 1.0))
    page_timeout_s = float(kwargs.get("page_timeout_s", 3.0))
    debug_keypad = bool(kwargs.get("debug_keypad", False))
    debug_entry_limit = max(0, int(kwargs.get("debug_entry_limit", 500)))

    buttons = list(
        dict.fromkeys(
            normalized
            for button in raw_buttons
            if (normalized := _normalize_button(button))
        )
    )
    if not buttons:
        raise ValueError("test_operator_keypad requires at least one non-empty button name")
    if job_count <= 0:
        raise ValueError("test_operator_keypad requires job_count to be greater than zero")
    if max_duration_s <= 0:
        raise ValueError("test_operator_keypad requires max_duration_s to be greater than zero")
    if poll_s <= 0:
        raise ValueError("test_operator_keypad requires poll_s to be greater than zero")

    state = OperatorKeypadRunState(
        expected_buttons=buttons,
        required_per_button=job_count,
        start_epoch_s=time.time(),
        start_monotonic_s=time.monotonic(),
    )
    shared.log(f"{meter.host} {func_name} 1/1")
    shared.log(
        f"expecting {len(buttons)} button(s) x {job_count} press(es) | "
        f"buttons={buttons} | max_duration_s={max_duration_s:.1f} | poll_s={poll_s:.2f} | "
        f"subtest={subtest}"
    )
    if not subtest:
        shared.broadcast_progress(meter.host, 'keypad', 1, 1)

    try:
        check_stop_event(shared)
        cursor = _initial_journal_cursor(meter)
        state.initial_journal_cursor = cursor
        state.current_journal_cursor = cursor
        shared.log(f"operator keypad initial journal cursor={cursor}")

        meter.goto_keypad()
        if not _is_on_keypad_page(meter, page_timeout_s):
            _fail_keypad(shared, state, "did not reach the keypad diagnostics page")

        _broadcast_keypad_state(meter, shared, state)

        while True:
            check_stop_event(shared)
            elapsed_s = time.monotonic() - state.start_monotonic_s
            if elapsed_s >= max_duration_s:
                if state.journal_consecutive_read_errors:
                    _fail_keypad(
                        shared,
                        state,
                        f"journal acquisition remained unavailable until max duration: {state.journal_last_error}",
                    )
                _fail_keypad(
                    shared,
                    state,
                    f"max duration exceeded ({max_duration_s:.1f}s); missing={_missing_buttons(state)}",
                )

            accepted = _poll_keypad_presses(
                meter,
                shared,
                state,
                debug_entry_limit=debug_entry_limit,
                debug_keypad=debug_keypad,
            )
            if accepted:
                _broadcast_keypad_state(meter, shared, state)

            if _all_buttons_satisfied(state):
                state.success = True
                device = getattr(shared, "current_device", None) or "keypad"
                shared.device_results[device] = "pass"
                shared.log(f"all operator keypad presses satisfied: {state.confirmed_counts}")
                return

            time.sleep(poll_s)

    except Exception as exc:
        if not state.final_error:
            state.final_error = str(exc)
        if not getattr(shared, "last_error", None):
            shared.last_error = state.final_error
        device = getattr(shared, "current_device", None) or "keypad"
        shared.device_results[device] = "fail"
        raise
    finally:
        _write_keypad_metadata(shared, state)
        shared.log(
            f"operator keypad accepted presses ({len(state.accepted_presses)}):"
        )
        for press in state.accepted_presses:
            shared.log(f"operator keypad accepted press: {press}")
        if not state.accepted_presses:
            shared.log("operator keypad accepted press: none")

        shared.log(
            f"operator keypad ignored presses ({len(state.ignored_presses)} retained):"
        )
        for press in state.ignored_presses:
            shared.log(f"operator keypad ignored press: {press}")
        if not state.ignored_presses:
            shared.log("operator keypad ignored press: none")
        if state.ignored_presses_dropped:
            shared.log(
                f"operator keypad ignored presses dropped by debug_entry_limit: "
                f"{state.ignored_presses_dropped}"
            )

        shared.log(
            f"operator keypad final summary: success={state.success} | "
            f"error={state.final_error!r} | counts={state.confirmed_counts} | "
            f"missing={_missing_buttons(state)} | "
            f"duration_s={shared.device_meta['keypad']['duration_s']} | "
            f"journal_polls={state.journal_poll_count} | "
            f"journal_entries={state.journal_entries_processed} | "
            f"journal_read_errors={state.journal_read_error_count}"
        )







