import inspect
import json
import math
import queue
import re
import shlex
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

import requests

from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter
from lib.robot.robot_client import RobotClient
from lib.automation.tests.test_solar import test_solar

# Keep flask/lib/docs/meter/test_robot_keypad.md in sync when changing this test.
KEYPAD_PAGE = "Service:Utilities:Peripherals:Keyboard"
KEYPAD_EXIT_PRIME_TEXT = "Press [&#10006;] again to exit this test"
STUCK_TARGET_BUTTONS = {"BACK", "ENTER"}
STUCK_PROBE_BUTTON = "POUND"
PRESS_PLAN_VERSION = 1
KEY_PRESSED_RE = re.compile(
    r"KEY_PRESSED:\s*(?P<key>[^,]+),\s*isAutoRepeat=(?P<ar>true|false),\s*from\s+(?P<src>\S+)",
    re.IGNORECASE,
)
ALLOWED_KEYPAD_SRCS = {"KEY_PAD_2", "KBD_CONTROLLER"}
JOURNAL_UNIT = "MS3_Platform.service"
DEFAULT_JOURNAL_AFTER_BUFFER_S = 3.5
DEFAULT_MAX_DURATION_BASE_S = 50.0
DEFAULT_PER_PLANNED_PRESS_TIMEOUT_S = 6.0
DEFAULT_ROBOT_PROGRAM_DONE_GRACE_S = 6.0
COMBINED_SOLAR_JOIN_POLL_S = 0.25


@dataclass
class KeypadAttempt:
    button_name: str
    raw_button_name: str
    attempt: int
    pressing_epoch_s: float
    pressing_monotonic_s: float
    step_id: str = ""
    group_id: str = ""
    role: str = "standard"
    offset_mm: Tuple[float, float] = (0.0, 0.0)
    job_count_number: int = 1
    group_attempt: int = 1
    logical_index: int = 0
    press_order: int = 0
    pressed_epoch_s: Optional[float] = None
    pressed_monotonic_s: Optional[float] = None
    robot_pressed: Optional[bool] = None
    meter_confirmed: bool = False
    meter_log_timestamp_text: str = ""
    meter_log_message: str = ""
    meter_log_raw_line: str = ""
    meter_log_cursor: str = ""
    retry_requested: bool = False
    retry_replaced: bool = False
    retry_cancelled: bool = False
    retry_response: Dict[str, Any] = field(default_factory=dict)
    result: str = "pressing"
    note: str = ""
    missing_pressed_logged: bool = False


@dataclass
class KeypadRunState:
    expected_buttons: List[str]
    required_per_button: int
    start_epoch_s: float
    start_monotonic_s: float
    initial_journal_cursor: str
    device_name: str = "robot_keypad"
    stop_on_failure: bool = True
    debug_keypad: bool = False
    journal_after_buffer_s: float = DEFAULT_JOURNAL_AFTER_BUFFER_S
    confirmed_counts: Dict[str, int] = field(default_factory=dict)
    robot_attempt_counts: Dict[str, int] = field(default_factory=dict)
    retry_counts: Dict[str, int] = field(default_factory=dict)
    pending_attempts: Dict[str, Deque[KeypadAttempt]] = field(default_factory=dict)
    attempt_history: List[KeypadAttempt] = field(default_factory=list)
    retry_pending_buttons: set[str] = field(default_factory=set)
    used_journal_ids: set[str] = field(default_factory=set)
    journal_matches: List[Dict[str, Any]] = field(default_factory=list)
    ignored_journal_entries: List[Dict[str, Any]] = field(default_factory=list)
    journal_backlog: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    program_done_data: Dict[str, Any] = field(default_factory=dict)
    program_done_seen_monotonic_s: Optional[float] = None
    final_error: str = ""
    success: bool = False
    journal_poll_count: int = 0
    current_journal_cursor: str = ""
    journal_entries_processed: int = 0
    journal_read_error_count: int = 0
    journal_consecutive_read_errors: int = 0
    journal_last_error: str = ""
    journal_last_fetch_ok: bool = True
    journal_last_success_monotonic_s: Optional[float] = None
    press_plan: List[Dict[str, Any]] = field(default_factory=list)
    plan_by_step_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    group_plan: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    attempt_batches: Dict[Tuple[str, int], Dict[str, Any]] = field(default_factory=dict)
    attempt_batch_order: List[Tuple[str, int]] = field(default_factory=list)
    completed_step_ids: set[str] = field(default_factory=set)
    completed_group_ids: set[str] = field(default_factory=set)
    requested_required_counts: Dict[str, int] = field(default_factory=dict)
    group_retry_counts: Dict[str, int] = field(default_factory=dict)
    retry_pending_groups: set[str] = field(default_factory=set)
    physical_attempt_count: int = 0
    progress_current: int = 0
    progress_total: int = 0

    def __post_init__(self) -> None:
        self.confirmed_counts = {button: 0 for button in self.expected_buttons}
        self.robot_attempt_counts = {button: 0 for button in self.expected_buttons}
        self.retry_counts = {button: 0 for button in self.expected_buttons}
        self.pending_attempts = {button: deque() for button in self.expected_buttons}
        self.current_journal_cursor = self.initial_journal_cursor
        if self.press_plan:
            self.plan_by_step_id = {step["step_id"]: step for step in self.press_plan}
            for step in self.press_plan:
                self.group_plan.setdefault(step["group_id"], []).append(step)
                self.group_retry_counts.setdefault(step["group_id"], 0)
            self.progress_total = len(self.press_plan)
            if self.requested_required_counts:
                self.confirmed_counts = {
                    button: 0 for button in self.requested_required_counts
                }


@dataclass(frozen=True)
class JournalFetchResult:
    ok: bool
    new_candidates: int = 0
    entries_processed: int = 0
    error: str = ""


def _norm(value: str) -> str:
    return (value or "").strip().upper()


@dataclass(frozen=True)
class KeypadPageState:
    is_keypad_page: bool
    requires_back_prime: bool = False


def _validate_back_enter_offsets(value: Any) -> List[List[float]]:
    if value is None:
        value = [[0.0, 0.0]]
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("back_enter_offsets_mm must be a non-empty list of [x, y] pairs")

    offsets: List[List[float]] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(
                f"back_enter_offsets_mm[{index}] must contain exactly [x, y]"
            )
        if any(isinstance(component, bool) for component in pair):
            raise ValueError(
                f"back_enter_offsets_mm[{index}] values must be finite numbers"
            )
        try:
            x, y = (float(pair[0]), float(pair[1]))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"back_enter_offsets_mm[{index}] values must be finite numbers"
            ) from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(
                f"back_enter_offsets_mm[{index}] values must be finite numbers"
            )
        if abs(x) >= 12.75:
            raise ValueError(
                f"back_enter_offsets_mm[{index}][0]={x} must satisfy abs(x) < 12.75"
            )
        if abs(y) >= 5.0:
            raise ValueError(
                f"back_enter_offsets_mm[{index}][1]={y} must satisfy abs(y) < 5.0"
            )
        offsets.append([x, y])
    return offsets


def _build_press_plan(
    raw_buttons: List[str],
    *,
    job_count: int,
    verify_stuck: bool,
    back_enter_offsets_mm: Any,
) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, int]]:
    buttons = list(dict.fromkeys(_norm(button) for button in raw_buttons if str(button).strip()))
    if not buttons:
        raise ValueError("test_robot_keypad requires at least one non-empty button name")

    offsets = _validate_back_enter_offsets(back_enter_offsets_mm)
    plan: List[Dict[str, Any]] = []
    required_counts: Dict[str, int] = {button: 0 for button in buttons}

    def add_step(
        *,
        step_id: str,
        group_id: str,
        button_name: str,
        role: str,
        offset_mm: List[float],
        pass_number: int,
    ) -> None:
        plan.append(
            {
                "step_id": step_id,
                "group_id": group_id,
                "button_name": button_name,
                "role": role,
                "offset_mm": list(offset_mm),
                "job_count_number": pass_number,
            }
        )

    for pass_number in range(1, job_count + 1):
        for button_index, button_name in enumerate(buttons, start=1):
            if button_name in STUCK_TARGET_BUTTONS:
                for offset_index, offset_mm in enumerate(offsets, start=1):
                    group_id = f"pass-{pass_number}:button-{button_index}:offset-{offset_index}"
                    add_step(
                        step_id=f"{group_id}:target",
                        group_id=group_id,
                        button_name=button_name,
                        role="target",
                        offset_mm=offset_mm,
                        pass_number=pass_number,
                    )
                    required_counts[button_name] += 1
                    if verify_stuck:
                        add_step(
                            step_id=f"{group_id}:probe",
                            group_id=group_id,
                            button_name=STUCK_PROBE_BUTTON,
                            role="stuck_probe",
                            offset_mm=[0.0, 0.0],
                            pass_number=pass_number,
                        )
            else:
                group_id = f"pass-{pass_number}:button-{button_index}"
                add_step(
                    step_id=f"{group_id}:standard",
                    group_id=group_id,
                    button_name=button_name,
                    role="standard",
                    offset_mm=[0.0, 0.0],
                    pass_number=pass_number,
                )
                required_counts[button_name] += 1

    planned_total = len(plan)
    for logical_index, step in enumerate(plan, start=1):
        step["logical_index"] = logical_index
        step["planned_total"] = planned_total

    return buttons, plan, required_counts


def _keypad_log(shared: SharedState, message: str, *, section: str = "") -> None:
    shared.log(message)


def _keypad_debug(shared: SharedState, state: KeypadRunState, message: str, *, section: str = "") -> None:
    if not state.debug_keypad:
        return
    _keypad_log(shared, message, section=section)


def _journal_after_cursor_command(cursor: str, *, lines: Optional[int] = None) -> str:
    line_arg = f" -n {lines}" if lines is not None else ""
    return (
        f"journalctl -u {JOURNAL_UNIT} --after-cursor={shlex.quote(cursor)}"
        f"{line_arg} --no-pager -o json"
    )


def _journal_message(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        try:
            return bytes(value).decode(errors="replace")
        except (TypeError, ValueError):
            pass
    if value is None:
        return ""
    return str(value)


def _journal_timestamp_text(value: Any) -> str:
    try:
        epoch_us = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    try:
        return datetime.fromtimestamp(epoch_us / 1_000_000).strftime("%Y-%m-%d %H:%M:%S.%f")
    except (OSError, OverflowError, ValueError):
        return str(value or "")


def _journal_display_line(payload: Dict[str, Any], timestamp_text: str, message: str) -> str:
    hostname = str(payload.get("_HOSTNAME") or "").strip()
    identifier = str(payload.get("SYSLOG_IDENTIFIER") or payload.get("_COMM") or "").strip()
    pid = str(payload.get("_PID") or "").strip()
    source = identifier
    if pid:
        source = f"{source}[{pid}]" if source else f"[{pid}]"
    prefix = " ".join(part for part in (timestamp_text, hostname, source) if part)
    return f"{prefix}: {message}" if prefix else message


def _parse_journal_json_batch(text: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for line_number, raw_line in enumerate((text or "").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid journal JSON on output line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"journal JSON on output line {line_number} is not an object")

        cursor = payload.get("__CURSOR")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError(f"journal JSON on output line {line_number} has no __CURSOR")

        message = _journal_message(payload.get("MESSAGE"))
        timestamp_text = _journal_timestamp_text(payload.get("__REALTIME_TIMESTAMP"))
        entries.append(
            {
                "entry_id": cursor,
                "journal_cursor": cursor,
                "timestamp_text": timestamp_text,
                "message": message,
                "raw_line": _journal_display_line(payload, timestamp_text, message),
            }
        )
    return entries


def _get_initial_meter_journal_cursor(meter: SSHMeter) -> tuple[str, str]:
    cmd = f"journalctl -u {JOURNAL_UNIT} -n 1 --no-pager -o json"
    try:
        code, output, error = meter.exec_parse(cmd)
    except Exception as exc:
        return "", f"initial journal cursor command failed: {exc}"
    if code != 0:
        detail = error or output or f"exit code {code}"
        return "", f"initial journal cursor command failed: {detail}"

    try:
        entries = _parse_journal_json_batch(output)
    except ValueError as exc:
        return "", f"unable to parse initial journal cursor: {exc}"
    if not entries:
        return "", f"no entries found for {JOURNAL_UNIT}; cannot establish a safe journal cursor"

    cursor = entries[-1]["journal_cursor"]
    probe_cmd = _journal_after_cursor_command(cursor, lines=0)
    try:
        probe_code, probe_output, probe_error = meter.exec_parse(probe_cmd)
    except Exception as exc:
        return "", f"journal --after-cursor preflight failed: {exc}"
    if probe_code != 0:
        detail = probe_error or probe_output or f"exit code {probe_code}"
        return "", f"journal --after-cursor preflight failed: {detail}"
    return cursor, ""


def _iso_from_epoch(epoch_s: Optional[float]) -> Optional[str]:
    if epoch_s is None:
        return None
    return datetime.fromtimestamp(epoch_s).isoformat(timespec="milliseconds")


def _attempt_to_meta(attempt: KeypadAttempt) -> Dict[str, Any]:
    return {
        "step_id": attempt.step_id,
        "group_id": attempt.group_id,
        "role": attempt.role,
        "offset_mm": list(attempt.offset_mm),
        "job_count_number": attempt.job_count_number,
        "group_attempt": attempt.group_attempt,
        "logical_index": attempt.logical_index,
        "press_order": attempt.press_order,
        "button_name": attempt.button_name,
        "raw_button_name": attempt.raw_button_name,
        "attempt": attempt.attempt,
        "pressing_received_at": _iso_from_epoch(attempt.pressing_epoch_s),
        "pressed_received_at": _iso_from_epoch(attempt.pressed_epoch_s),
        "robot_pressed": attempt.robot_pressed,
        "meter_confirmed": attempt.meter_confirmed,
        "meter_log_timestamp_text": attempt.meter_log_timestamp_text,
        "meter_log_message": attempt.meter_log_message,
        "meter_log_raw_line": attempt.meter_log_raw_line,
        "meter_log_cursor": attempt.meter_log_cursor,
        "retry_requested": attempt.retry_requested,
        "retry_replaced": attempt.retry_replaced,
        "retry_cancelled": attempt.retry_cancelled,
        "retry_response": dict(attempt.retry_response or {}),
        "result": attempt.result,
        "note": attempt.note,
        "missing_pressed_logged": attempt.missing_pressed_logged,
    }


def get_keypad_page_state(
    meter: SSHMeter,
    shared: SharedState,
    timeout: float = 3.0,
) -> KeypadPageState:
    url = f"http://{meter.host}:8005/UIPage.php"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except Exception as exc:
        _keypad_log(
            shared,
            f"Failed to fetch UI page, assuming NOT on keyboard page | Error: {exc}",
            section="ui",
        )
        return KeypadPageState(False, False)

    is_keypad_page = KEYPAD_PAGE in resp.text
    return KeypadPageState(
        is_keypad_page=is_keypad_page,
        requires_back_prime=is_keypad_page and KEYPAD_EXIT_PRIME_TEXT in resp.text,
    )


def is_on_keypad_page(meter: SSHMeter, shared: SharedState, timeout: float = 3.0) -> bool:
    """Compatibility wrapper for callers that only need page presence."""
    return get_keypad_page_state(meter, shared, timeout=timeout).is_keypad_page


def _maintain_keypad_page(meter: SSHMeter, shared: SharedState) -> KeypadPageState:
    page_state = get_keypad_page_state(meter, shared)
    if not page_state.is_keypad_page:
        _keypad_log(
            shared,
            "No longer on keypad page... re-navigating to keypad page",
            section="ui",
        )
        meter.goto_keypad()
    elif page_state.requires_back_prime:
        _keypad_log(
            shared,
            "Keypad page requires the first exit press; sending synthetic BACK",
            section="ui",
        )
        meter.press("BACK")
    return page_state


def _fail_keypad(shared: SharedState, state: KeypadRunState, message: str) -> None:
    state.final_error = message
    state.errors.append(message)
    shared.last_error = message
    shared.device_results[state.device_name] = "fail"
    _keypad_log(shared, message, section="fail")
    if state.stop_on_failure:
        shared.stop_event.set()
    raise StopAutomation(message)


def _all_buttons_satisfied(state: KeypadRunState) -> bool:
    if state.press_plan:
        return len(state.completed_step_ids) >= len(state.press_plan)
    return all(
        state.confirmed_counts.get(button, 0) >= state.required_per_button
        for button in state.expected_buttons
    )


def _button_is_satisfied(state: KeypadRunState, button_name: str) -> bool:
    return state.confirmed_counts.get(button_name, 0) >= state.required_per_button


def _find_pending_attempt(
    state: KeypadRunState,
    button_name: str,
    attempt_num: int,
) -> Optional[KeypadAttempt]:
    for attempt in reversed(state.pending_attempts.get(button_name, ())):
        if attempt.attempt == attempt_num:
            return attempt
    return None


def _find_waiting_press_result(state: KeypadRunState, button_name: str) -> Optional[KeypadAttempt]:
    for attempt in reversed(state.pending_attempts.get(button_name, ())):
        if attempt.robot_pressed is None:
            return attempt
    return None


def _find_oldest_unconfirmed_attempt(state: KeypadRunState, button_name: str) -> Optional[KeypadAttempt]:
    for attempt in state.pending_attempts.get(button_name, ()):
        if not attempt.meter_confirmed and not attempt.retry_replaced:
            return attempt
    return None


def _replace_attempt_with_retry(
    shared: SharedState,
    state: KeypadRunState,
    attempt: KeypadAttempt,
    *,
    retry_result: str,
    reason: str,
) -> None:
    attempt.retry_replaced = True
    attempt.result = retry_result
    attempt.note = reason
    try:
        state.pending_attempts[attempt.button_name].remove(attempt)
    except (KeyError, ValueError):
        pass
    _keypad_debug(
        shared,
        state,
        (
            f"removed '{attempt.raw_button_name}' attempt {attempt.attempt} from pending "
            "matching because a retry will create a replacement attempt"
        ),
        section="retry",
    )


def _collect_robot_button_events(
    robot: RobotClient,
    job_id: str,
    out_queue: "queue.Queue[Dict[str, Any]]",
    stop_event: threading.Event,
    shared: SharedState,
) -> None:
    while not stop_event.is_set():
        if shared.stop_event.is_set() or shared.end_listener.is_set():
            return

        found, data = robot.try_get_event("button_press", job_id=job_id, consume=True)
        if found:
            out_queue.put(
                {
                    "received_epoch_s": time.time(),
                    "received_monotonic_s": time.monotonic(),
                    "data": dict(data or {}),
                }
            )
            continue

        time.sleep(0.05)


def _request_retry(
    robot: RobotClient,
    shared: SharedState,
    state: KeypadRunState,
    attempt: KeypadAttempt,
    *,
    job_id: str,
    max_retries_per_button: int,
    retry_command_timeout_s: float,
    reason: str,
    retry_result: str,
) -> bool:
    button_name = attempt.button_name
    if attempt.retry_requested:
        return True

    if _button_is_satisfied(state, button_name):
        attempt.note = "button already satisfied before retry was needed"
        _keypad_debug(
            shared,
            state,
            f"skip retry for '{attempt.raw_button_name}' attempt {attempt.attempt} because the button is already satisfied",
            section="retry",
        )
        return True

    retries_used = state.retry_counts.get(button_name, 0)
    if retries_used >= max_retries_per_button:
        _keypad_debug(
            shared,
            state,
            f"retry budget exhausted for '{attempt.raw_button_name}' attempt {attempt.attempt}",
            section="retry",
        )
        return False

    _keypad_debug(
        shared,
        state,
        f"requesting retry for '{attempt.raw_button_name}' attempt {attempt.attempt} | reason={reason}",
        section="retry",
    )

    try:
        response = robot.request_button_retry(
            attempt.raw_button_name,
            job_id=job_id,
            reason=reason,
            timeout=retry_command_timeout_s,
        )
    except Exception as exc:
        _keypad_log(
            shared,
            f"Retry request failed for '{attempt.raw_button_name}': {exc}",
            section="retry",
        )
        attempt.note = f"{reason} | retry request failed: {exc}"
        return False

    if response.get("accepted"):
        attempt.retry_requested = True
        attempt.retry_response = dict(response or {})
        state.retry_counts[button_name] = retries_used + 1
        state.retry_pending_buttons.add(button_name)
        _replace_attempt_with_retry(
            shared,
            state,
            attempt,
            retry_result=retry_result,
            reason=reason,
        )
        _keypad_log(
            shared,
            (
                f"queued retry {state.retry_counts[button_name]}/{max_retries_per_button} "
                f"for '{attempt.raw_button_name}' attempt {attempt.attempt} ({reason})"
            ),
            section="retry",
        )
        _keypad_debug(shared, state, f"retry response={response}", section="retry")
        return True

    if response.get("already_queued"):
        attempt.retry_requested = True
        attempt.retry_response = dict(response or {})
        state.retry_pending_buttons.add(button_name)
        _replace_attempt_with_retry(
            shared,
            state,
            attempt,
            retry_result=retry_result,
            reason=f"{reason} | retry already queued",
        )
        _keypad_log(
            shared,
            f"retry already queued for '{attempt.raw_button_name}' ({reason})",
            section="retry",
        )
        _keypad_debug(shared, state, f"retry response={response}", section="retry")
        return True

    attempt.note = f"{reason} | retry rejected: {response.get('message')}"
    _keypad_log(
        shared,
        f"Retry request rejected for '{attempt.raw_button_name}': {response.get('message')}",
        section="retry",
    )
    _keypad_debug(shared, state, f"retry response={response}", section="retry")
    return False


def _cancel_retry_if_pending(
    robot: RobotClient,
    shared: SharedState,
    state: KeypadRunState,
    attempt: KeypadAttempt,
    *,
    job_id: str,
    retry_command_timeout_s: float,
    reason: str,
) -> None:
    button_name = attempt.button_name
    if button_name not in state.retry_pending_buttons:
        return

    state.retry_pending_buttons.discard(button_name)
    _keypad_debug(
        shared,
        state,
        f"attempting to cancel queued retry for '{attempt.raw_button_name}' | reason={reason}",
        section="retry",
    )
    try:
        response = robot.cancel_button_retry(
            attempt.raw_button_name,
            job_id=job_id,
            reason=reason,
            timeout=retry_command_timeout_s,
        )
    except Exception as exc:
        _keypad_log(
            shared,
            f"Cancel retry request failed for '{attempt.raw_button_name}': {exc}",
            section="retry",
        )
        attempt.note = f"{attempt.note} | cancel retry failed: {exc}".strip(" |")
        return

    if response.get("cancelled"):
        attempt.retry_cancelled = True
        _keypad_log(
            shared,
            f"cancelled queued retry for '{attempt.raw_button_name}' because the meter confirmed the press",
            section="retry",
        )
    _keypad_debug(shared, state, f"cancel retry response={response}", section="retry")


def _handle_robot_events(
    robot_events: "queue.Queue[Dict[str, Any]]",
    shared: SharedState,
    state: KeypadRunState,
    *,
    robot: RobotClient,
    job_id: str,
    max_retries_per_button: int,
    retry_command_timeout_s: float,
) -> None:
    while True:
        try:
            event = robot_events.get_nowait()
        except queue.Empty:
            return

        data = dict(event.get("data") or {})
        _keypad_debug(shared, state, f"received robot event {data}", section="robot")
        button_name_raw = data.get("button_name", "")
        button_name = _norm(button_name_raw)
        if button_name not in state.confirmed_counts:
            _keypad_log(
                shared,
                f"ignoring unexpected robot keypad event for '{button_name_raw}'",
                section="robot",
            )
            continue

        attempt_num = int(data.get("attempt") or 0) or (state.robot_attempt_counts[button_name] + 1)
        action = data.get("action")

        if action == "pressing":
            state.retry_pending_buttons.discard(button_name)
            attempt = KeypadAttempt(
                button_name=button_name,
                raw_button_name=button_name_raw or button_name,
                attempt=attempt_num,
                pressing_epoch_s=float(event["received_epoch_s"]),
                pressing_monotonic_s=float(event["received_monotonic_s"]),
            )
            state.robot_attempt_counts[button_name] = max(
                state.robot_attempt_counts.get(button_name, 0),
                attempt_num,
            )
            state.pending_attempts[button_name].append(attempt)
            state.attempt_history.append(attempt)
            _keypad_log(
                shared,
                f"robot STARTED pressing '{attempt.raw_button_name}' attempt {attempt.attempt}",
                section="robot",
            )
            continue

        attempt = _find_pending_attempt(state, button_name, attempt_num)
        if attempt is None:
            attempt = _find_waiting_press_result(state, button_name)

        if attempt is None:
            attempt = KeypadAttempt(
                button_name=button_name,
                raw_button_name=button_name_raw or button_name,
                attempt=attempt_num,
                pressing_epoch_s=float(event["received_epoch_s"]),
                pressing_monotonic_s=float(event["received_monotonic_s"]),
                result="pressed_without_pressing",
                note="received a pressed event before a matching pressing event",
            )
            state.pending_attempts[button_name].append(attempt)
            state.attempt_history.append(attempt)
            _keypad_log(
                shared,
                (
                    f"received robot '{action}' event for '{attempt.raw_button_name}' attempt "
                    f"{attempt.attempt} before a matching pressing event"
                ),
                section="robot",
            )

        attempt.pressed_epoch_s = float(event["received_epoch_s"])
        attempt.pressed_monotonic_s = float(event["received_monotonic_s"])

        if action != "pressed":
            attempt.note = f"unexpected robot action={action!r}"
            _keypad_debug(
                shared,
                state,
                f"leaving attempt {attempt.button_name}#{attempt.attempt} untouched because action={action!r}",
                section="robot",
            )
            continue

        pressed = data.get("pressed", None)
        attempt.robot_pressed = None if pressed is None else bool(pressed)
        if attempt.meter_confirmed:
            attempt.result = "confirmed_before_robot_result"
            attempt.note = "meter log confirmed the press before the robot sent its final result"
            try:
                state.pending_attempts[button_name].remove(attempt)
            except ValueError:
                pass
            _keypad_log(
                shared,
                f"received late robot result for already confirmed '{attempt.raw_button_name}' attempt {attempt.attempt}",
                section="robot",
            )
            continue

        if pressed is False:
            attempt.result = "awaiting_meter_check_after_robot_false"
            attempt.note = (
                f"robot reported pressed=false; waiting {state.journal_after_buffer_s:.1f}s "
                "before checking the meter logs"
            )
            _keypad_log(
                shared,
                (
                    f"robot reports pressed=False on '{attempt.raw_button_name}' attempt "
                    f"{attempt.attempt} - waiting {state.journal_after_buffer_s:.1f}s before "
                    "deciding whether a retry is needed"
                ),
                section="robot",
            )
            continue

        if pressed is True:
            attempt.result = "awaiting_after_buffer"
            attempt.note = (
                f"waiting {state.journal_after_buffer_s:.1f}s after-buffer before meter log matching"
            )
            _keypad_log(
                shared,
                (
                    f"robot reports SUCCESS on '{attempt.raw_button_name}' attempt {attempt.attempt} "
                    f"- waiting {state.journal_after_buffer_s:.1f}s before matching journal logs"
                ),
                section="robot",
            )


def _record_journal_read_error(
    shared: SharedState,
    state: KeypadRunState,
    message: str,
) -> JournalFetchResult:
    previous_error = state.journal_last_error
    state.journal_read_error_count += 1
    state.journal_consecutive_read_errors += 1
    state.journal_last_error = message
    state.journal_last_fetch_ok = False
    if state.journal_consecutive_read_errors == 1 or message != previous_error:
        _keypad_log(shared, f"meter journal acquisition failed: {message}", section="journal")
    else:
        _keypad_debug(shared, state, f"meter journal acquisition still failing: {message}", section="journal")
    return JournalFetchResult(ok=False, error=message)


def _fetch_new_keypad_logs(
    meter: SSHMeter,
    shared: SharedState,
    state: KeypadRunState,
) -> JournalFetchResult:
    cmd = _journal_after_cursor_command(state.current_journal_cursor)
    state.journal_poll_count += 1
    try:
        code, output, error = meter.exec_parse(cmd)
    except Exception as exc:
        return _record_journal_read_error(shared, state, f"journal command failed: {exc}")
    if code != 0:
        detail = error or output or f"exit code {code}"
        return _record_journal_read_error(shared, state, f"journal command failed: {detail}")

    try:
        entries = _parse_journal_json_batch(output)
    except ValueError as exc:
        return _record_journal_read_error(shared, state, str(exc))

    recovered_after_errors = state.journal_consecutive_read_errors > 0
    state.journal_consecutive_read_errors = 0
    state.journal_last_fetch_ok = True
    state.journal_last_success_monotonic_s = time.monotonic()
    if recovered_after_errors:
        _keypad_log(shared, "meter journal acquisition recovered", section="journal")

    if not entries:
        _keypad_debug(shared, state, "journal poll returned no new entries", section="journal")
        return JournalFetchResult(ok=True)

    new_candidates = 0
    for entry in entries:
        message = entry["message"]
        parsed = KEY_PRESSED_RE.search(message)
        if not parsed:
            continue

        entry_id = entry["entry_id"]
        if entry_id in state.used_journal_ids:
            continue

        common_meta = {
            "journal_cursor": entry["journal_cursor"],
            "timestamp_text": entry["timestamp_text"],
            "message": message,
            "raw_line": entry["raw_line"],
        }
        if parsed.group("ar").lower() == "true":
            state.used_journal_ids.add(entry_id)
            state.ignored_journal_entries.append(
                {
                    "button_name": _norm(parsed.group("key")),
                    **common_meta,
                    "reason": "auto-repeat=true",
                }
            )
            _keypad_debug(
                shared,
                state,
                f"ignoring auto-repeat keypad log: {entry['raw_line']}",
                section="journal",
            )
            continue

        button_name = _norm(parsed.group("key"))
        src = _norm(parsed.group("src"))
        if src not in ALLOWED_KEYPAD_SRCS:
            state.used_journal_ids.add(entry_id)
            state.ignored_journal_entries.append(
                {
                    "button_name": button_name,
                    **common_meta,
                    "reason": f"unexpected source={src}",
                }
            )
            _keypad_debug(
                shared,
                state,
                f"ignoring keypad log from unexpected source={src}: {entry['raw_line']}",
                section="journal",
            )
            continue

        state.used_journal_ids.add(entry_id)
        state.journal_backlog.append(
            {
                "entry_id": entry_id,
                "button_name": button_name,
                "src": src,
                **common_meta,
            }
        )
        new_candidates += 1

    # The batch is parsed completely before any state is changed. Only then is
    # the opaque cursor advanced to the final entry, regardless of whether that
    # entry was a keypad message. This prevents non-key traffic from being read
    # repeatedly and makes wall-clock changes irrelevant to acquisition.
    state.current_journal_cursor = entries[-1]["journal_cursor"]
    state.journal_entries_processed += len(entries)

    _keypad_debug(
        shared,
        state,
        (
            f"journal poll #{state.journal_poll_count}: entries={len(entries)}, "
            f"new_candidates={new_candidates}, backlog={len(state.journal_backlog)}, "
            f"cursor={state.current_journal_cursor}"
        ),
        section="journal",
    )
    return JournalFetchResult(
        ok=True,
        new_candidates=new_candidates,
        entries_processed=len(entries),
    )


def _attempt_is_journal_match_eligible(
    attempt: KeypadAttempt,
    state: KeypadRunState,
    now_monotonic_s: float,
    force_attempt_ids: Optional[set[tuple[str, int]]] = None,
) -> bool:
    attempt_id = (attempt.button_name, attempt.attempt)
    if force_attempt_ids and attempt_id in force_attempt_ids:
        return True

    if attempt.retry_replaced:
        return False

    if attempt.robot_pressed is not None and attempt.pressed_monotonic_s is not None:
        return (now_monotonic_s - attempt.pressed_monotonic_s) >= state.journal_after_buffer_s

    return False


def _match_keypad_logs(
    shared: SharedState,
    state: KeypadRunState,
    *,
    robot: RobotClient,
    job_id: str,
    retry_command_timeout_s: float,
    force_attempt_ids: Optional[set[tuple[str, int]]] = None,
) -> None:
    if not state.journal_backlog:
        return

    remaining_backlog: List[Dict[str, Any]] = []
    now_monotonic_s = time.monotonic()

    for entry in state.journal_backlog:
        button_name = entry["button_name"]
        if button_name not in state.confirmed_counts:
            state.ignored_journal_entries.append(
                {
                    "button_name": button_name,
                    "journal_cursor": entry["journal_cursor"],
                    "timestamp_text": entry["timestamp_text"],
                    "message": entry["message"],
                    "raw_line": entry["raw_line"],
                    "reason": "unexpected button",
                }
            )
            continue

        if _button_is_satisfied(state, button_name):
            state.ignored_journal_entries.append(
                {
                    "button_name": button_name,
                    "journal_cursor": entry["journal_cursor"],
                    "timestamp_text": entry["timestamp_text"],
                    "message": entry["message"],
                    "raw_line": entry["raw_line"],
                    "reason": "button already satisfied",
                }
            )
            continue

        attempt = _find_oldest_unconfirmed_attempt(state, button_name)
        if attempt is None:
            state.ignored_journal_entries.append(
                {
                    "button_name": button_name,
                    "journal_cursor": entry["journal_cursor"],
                    "timestamp_text": entry["timestamp_text"],
                    "message": entry["message"],
                    "raw_line": entry["raw_line"],
                    "reason": "no pending robot attempt",
                }
            )
            _keypad_debug(
                shared,
                state,
                f"ignoring journal candidate for '{button_name}' because there is no pending attempt",
                section="journal",
            )
            continue

        if not _attempt_is_journal_match_eligible(
            attempt,
            state,
            now_monotonic_s,
            force_attempt_ids=force_attempt_ids,
        ):
            remaining_backlog.append(entry)
            _keypad_debug(
                shared,
                state,
                (
                    f"keeping journal candidate buffered for '{button_name}' while waiting for "
                    f"attempt {attempt.attempt} to become eligible"
                ),
                section="journal",
            )
            continue

        attempt.meter_confirmed = True
        attempt.meter_log_timestamp_text = entry["timestamp_text"]
        attempt.meter_log_message = entry["message"]
        attempt.meter_log_raw_line = entry["raw_line"]
        attempt.meter_log_cursor = entry["journal_cursor"]

        if attempt.robot_pressed is None:
            attempt.result = "confirmed_without_robot_result"
        elif attempt.robot_pressed is False:
            attempt.result = "confirmed_despite_robot_false"
        else:
            attempt.result = "confirmed"
        attempt.note = "meter log confirmed button press"

        state.confirmed_counts[button_name] += 1
        state.journal_matches.append(
            {
                "button_name": button_name,
                "attempt": attempt.attempt,
                "journal_cursor": entry["journal_cursor"],
                "timestamp_text": entry["timestamp_text"],
                "message": entry["message"],
                "raw_line": entry["raw_line"],
            }
        )

        if attempt.robot_pressed is not None:
            try:
                state.pending_attempts[button_name].remove(attempt)
            except ValueError:
                pass

        _keypad_log(
            shared,
            (
                f"meter confirmed '{attempt.raw_button_name}' attempt {attempt.attempt} -> "
                f"{state.confirmed_counts[button_name]}/{state.required_per_button}"
            ),
            section="journal",
        )
        if attempt.robot_pressed is False:
            _keypad_log(
                shared,
                (
                    f"meter confirmed '{attempt.raw_button_name}' attempt {attempt.attempt} "
                    "even though the robot reported pressed=False"
                ),
                section="journal",
            )
        _keypad_debug(
            shared,
            state,
            f"matched journal line to attempt {attempt.button_name}#{attempt.attempt}: {entry['raw_line']}",
            section="journal",
        )

        _cancel_retry_if_pending(
            robot,
            shared,
            state,
            attempt,
            job_id=job_id,
            retry_command_timeout_s=retry_command_timeout_s,
            reason="meter log observed after retry request",
        )

    state.journal_backlog = remaining_backlog


def _final_journal_recheck(
    meter: SSHMeter,
    shared: SharedState,
    state: KeypadRunState,
    *,
    robot: RobotClient,
    job_id: str,
    retry_command_timeout_s: float,
    force_attempt_ids: Optional[set[tuple[str, int]]] = None,
    reason: str,
) -> bool:
    _keypad_debug(shared, state, f"running final journal recheck | reason={reason}", section="journal")
    fetch_result = _fetch_new_keypad_logs(meter, shared, state)
    if not fetch_result.ok:
        _keypad_debug(
            shared,
            state,
            f"deferring journal absence decision because recheck failed | reason={reason}",
            section="journal",
        )
        return False
    _match_keypad_logs(
        shared,
        state,
        robot=robot,
        job_id=job_id,
        retry_command_timeout_s=retry_command_timeout_s,
        force_attempt_ids=force_attempt_ids,
    )
    return True


def _check_attempt_timeouts(
    meter: SSHMeter,
    shared: SharedState,
    state: KeypadRunState,
    *,
    robot: RobotClient,
    job_id: str,
    per_button_timeout_s: float,
    max_retries_per_button: int,
    retry_command_timeout_s: float,
) -> None:
    now = time.monotonic()

    for button_name, attempts in state.pending_attempts.items():
        if _button_is_satisfied(state, button_name):
            continue

        for attempt in list(attempts):
            if attempt.meter_confirmed or attempt.retry_requested:
                continue

            if attempt.robot_pressed is None:
                age_s = now - attempt.pressing_monotonic_s
                if age_s < per_button_timeout_s:
                    continue

                attempt.result = "pressed_event_missing"
                attempt.note = (
                    f"did not receive robot 'pressed' event within {per_button_timeout_s:.1f}s"
                )
                if not attempt.missing_pressed_logged:
                    _keypad_log(
                        shared,
                        (
                            f"DID NOT RECEIVE ROBOT 'PRESSED' EVENT FOR "
                            f"'{attempt.raw_button_name}' ATTEMPT {attempt.attempt} "
                            f"WITHIN {per_button_timeout_s:.1f}S"
                        ),
                        section="robot",
                    )
                    attempt.missing_pressed_logged = True
                continue

            if attempt.robot_pressed is False and attempt.pressed_monotonic_s is not None:
                age_s = now - attempt.pressed_monotonic_s
                if age_s < state.journal_after_buffer_s:
                    continue

                attempt.result = "robot_false_verifying_meter"
                attempt.note = (
                    f"robot reported pressed=false; verifying meter log after "
                    f"{state.journal_after_buffer_s:.1f}s after-buffer"
                )
                journal_recheck_ok = _final_journal_recheck(
                    meter,
                    shared,
                    state,
                    robot=robot,
                    job_id=job_id,
                    retry_command_timeout_s=retry_command_timeout_s,
                    reason=(
                        f"robot reported pressed=false for '{attempt.raw_button_name}' "
                        f"attempt {attempt.attempt}; verifying meter log before retry"
                    ),
                )
                if attempt.meter_confirmed:
                    continue
                if not journal_recheck_ok:
                    attempt.result = "journal_recheck_pending"
                    attempt.note = (
                        "robot reported pressed=false; journal acquisition failed, "
                        "so retry decision is deferred"
                    )
                    continue

                if _request_retry(
                    robot,
                    shared,
                    state,
                    attempt,
                    job_id=job_id,
                    max_retries_per_button=max_retries_per_button,
                    retry_command_timeout_s=retry_command_timeout_s,
                    reason=(
                        f"robot reported pressed=false and no meter confirmation was found "
                        f"after {state.journal_after_buffer_s:.1f}s"
                    ),
                    retry_result="robot_false_retry_queued",
                ):
                    continue

                _fail_keypad(
                    shared,
                    state,
                    (
                        f"Robot reported pressed=False for '{attempt.raw_button_name}' attempt "
                        f"{attempt.attempt}, the meter logs did not confirm the press after "
                        f"{state.journal_after_buffer_s:.1f}s, and the retry budget is exhausted "
                        f"({max_retries_per_button})"
                    ),
                )

            if attempt.robot_pressed is True and attempt.pressed_monotonic_s is not None:
                age_s = now - attempt.pressed_monotonic_s
                if age_s < per_button_timeout_s:
                    continue

                attempt.result = "meter_log_timeout"
                attempt.note = (
                    f"meter log did not confirm the press within {per_button_timeout_s:.1f}s"
                )
                journal_recheck_ok = _final_journal_recheck(
                    meter,
                    shared,
                    state,
                    robot=robot,
                    job_id=job_id,
                    retry_command_timeout_s=retry_command_timeout_s,
                    reason=f"meter log timeout check for '{attempt.raw_button_name}' attempt {attempt.attempt}",
                )
                if attempt.meter_confirmed:
                    continue
                if not journal_recheck_ok:
                    attempt.result = "journal_recheck_pending"
                    attempt.note = (
                        "meter log timeout reached; journal acquisition failed, "
                        "so retry decision is deferred"
                    )
                    continue

                if _request_retry(
                    robot,
                    shared,
                    state,
                    attempt,
                    job_id=job_id,
                    max_retries_per_button=max_retries_per_button,
                    retry_command_timeout_s=retry_command_timeout_s,
                    reason=f"meter log timeout after {per_button_timeout_s:.1f}s",
                    retry_result="meter_log_timeout_retry_queued",
                ):
                    continue

                _fail_keypad(
                    shared,
                    state,
                    (
                        f"Robot pressing '{attempt.raw_button_name}' attempt {attempt.attempt} was not "
                        f"confirmed by the meter logs within {per_button_timeout_s:.1f}s after "
                        f"{state.retry_counts.get(button_name, 0)} retry request(s)"
                    ),
                )


def _handle_structured_robot_events(
    robot_events: "queue.Queue[Dict[str, Any]]",
    shared: SharedState,
    state: KeypadRunState,
) -> None:
    while True:
        try:
            event = robot_events.get_nowait()
        except queue.Empty:
            return

        data = dict(event.get("data") or {})
        step_id = str(data.get("step_id") or "")
        if step_id not in state.plan_by_step_id:
            _fail_keypad(
                shared,
                state,
                f"Robot returned an unknown or missing structured keypad step_id: {step_id!r}",
            )

        plan_step = state.plan_by_step_id[step_id]
        group_id = str(data.get("group_id") or plan_step["group_id"])
        if group_id != plan_step["group_id"]:
            _fail_keypad(
                shared,
                state,
                f"Robot keypad event group mismatch for {step_id}: {group_id!r}",
            )

        action = str(data.get("action") or "")
        attempt_num = max(1, int(data.get("attempt") or 1))
        group_attempt = max(1, int(data.get("group_attempt") or attempt_num))
        batch_key = (group_id, group_attempt)
        batch = state.attempt_batches.get(batch_key)
        if batch is None:
            batch = {
                "group_id": group_id,
                "group_attempt": group_attempt,
                "attempts": {},
                "resolved": False,
                "retry_requested": False,
                "probe_before_target": False,
            }
            state.attempt_batches[batch_key] = batch
            state.attempt_batch_order.append(batch_key)

        attempt = batch["attempts"].get(step_id)
        if action == "pressing":
            if attempt is not None:
                _keypad_debug(
                    shared,
                    state,
                    f"ignoring duplicate pressing event for {step_id} attempt {attempt_num}",
                    section="robot",
                )
                continue
            state.physical_attempt_count += 1
            attempt = KeypadAttempt(
                button_name=_norm(data.get("button_name") or plan_step["button_name"]),
                raw_button_name=str(data.get("button_name") or plan_step["button_name"]),
                attempt=attempt_num,
                pressing_epoch_s=float(event["received_epoch_s"]),
                pressing_monotonic_s=float(event["received_monotonic_s"]),
                step_id=step_id,
                group_id=group_id,
                role=str(data.get("role") or plan_step["role"]),
                offset_mm=tuple(data.get("offset_mm") or plan_step["offset_mm"]),
                job_count_number=int(data.get("job_count_number") or plan_step["job_count_number"]),
                group_attempt=group_attempt,
                logical_index=int(data.get("logical_index") or plan_step["logical_index"]),
                press_order=state.physical_attempt_count,
            )
            batch["attempts"][step_id] = attempt
            state.attempt_history.append(attempt)
            state.retry_pending_groups.discard(group_id)
            _keypad_log(
                shared,
                (
                    f"robot STARTED step {attempt.logical_index}/{len(state.press_plan)} "
                    f"'{attempt.raw_button_name}' role={attempt.role} offset={list(attempt.offset_mm)} "
                    f"group={group_id} group_attempt={group_attempt}"
                ),
                section="robot",
            )
            continue

        if attempt is None:
            _fail_keypad(
                shared,
                state,
                f"Robot returned {action!r} before pressing for structured step {step_id}",
            )
        if action != "pressed":
            _keypad_debug(
                shared,
                state,
                f"ignoring unexpected robot action={action!r} for {step_id}",
                section="robot",
            )
            continue

        attempt.pressed_epoch_s = float(event["received_epoch_s"])
        attempt.pressed_monotonic_s = float(event["received_monotonic_s"])
        pressed = data.get("pressed")
        attempt.robot_pressed = None if pressed is None else bool(pressed)
        attempt.result = "awaiting_meter_evidence"
        attempt.note = "waiting for ordered meter journal evidence"
        _keypad_log(
            shared,
            (
                f"robot reports pressed={attempt.robot_pressed} for '{attempt.raw_button_name}' "
                f"role={attempt.role} group={group_id} group_attempt={group_attempt}"
            ),
            section="robot",
        )


def _consume_journal_entry(
    shared: SharedState,
    state: KeypadRunState,
    *,
    ignored_reason: Optional[str] = None,
) -> Dict[str, Any]:
    entry = state.journal_backlog.pop(0)
    if ignored_reason:
        state.ignored_journal_entries.append({**entry, "reason": ignored_reason})
        _keypad_debug(
            shared,
            state,
            f"ignoring ordered journal candidate ({ignored_reason}): {entry['raw_line']}",
            section="journal",
        )
    return entry


def _confirm_structured_attempt(
    shared: SharedState,
    state: KeypadRunState,
    attempt: KeypadAttempt,
    entry: Dict[str, Any],
) -> None:
    attempt.meter_confirmed = True
    attempt.meter_log_timestamp_text = entry["timestamp_text"]
    attempt.meter_log_message = entry["message"]
    attempt.meter_log_raw_line = entry["raw_line"]
    attempt.meter_log_cursor = entry["journal_cursor"]
    attempt.result = "confirmed" if attempt.robot_pressed is not False else "confirmed_despite_robot_false"
    attempt.note = "meter log confirmed ordered physical step"
    state.journal_matches.append(
        {
            "step_id": attempt.step_id,
            "group_id": attempt.group_id,
            "group_attempt": attempt.group_attempt,
            "role": attempt.role,
            "button_name": attempt.button_name,
            "offset_mm": list(attempt.offset_mm),
            "journal_cursor": entry["journal_cursor"],
            "timestamp_text": entry["timestamp_text"],
            "message": entry["message"],
            "raw_line": entry["raw_line"],
        }
    )
    _keypad_log(
        shared,
        (
            f"meter confirmed step '{attempt.button_name}' role={attempt.role} "
            f"group={attempt.group_id} group_attempt={attempt.group_attempt}"
        ),
        section="journal",
    )


def _future_unresolved_button_names(
    state: KeypadRunState,
    current_batch_key: Tuple[str, int],
) -> set[str]:
    names: set[str] = set()
    seen_current = False
    for batch_key in state.attempt_batch_order:
        if batch_key == current_batch_key:
            seen_current = True
            continue
        if not seen_current:
            continue
        batch = state.attempt_batches[batch_key]
        if batch.get("resolved"):
            continue
        for step in state.group_plan.get(batch["group_id"], ()):
            names.add(_norm(step["button_name"]))
    return names


def _complete_structured_group(
    shared: SharedState,
    state: KeypadRunState,
    batch: Dict[str, Any],
) -> None:
    group_id = batch["group_id"]
    batch["resolved"] = True
    if group_id in state.completed_group_ids:
        return
    state.completed_group_ids.add(group_id)
    for step in state.group_plan[group_id]:
        state.completed_step_ids.add(step["step_id"])
        if step["role"] != "stuck_probe":
            button_name = _norm(step["button_name"])
            if button_name in state.confirmed_counts:
                state.confirmed_counts[button_name] += 1
    state.progress_current = len(state.completed_step_ids)
    _keypad_log(
        shared,
        f"completed keypad verification group {group_id} -> {state.progress_current}/{state.progress_total}",
        section="progress",
    )


def _request_structured_group_retry(
    robot: RobotClient,
    shared: SharedState,
    state: KeypadRunState,
    batch: Dict[str, Any],
    *,
    job_id: str,
    max_retries_per_group: int,
    retry_command_timeout_s: float,
    reason: str,
) -> None:
    group_id = batch["group_id"]
    retries_used = state.group_retry_counts.get(group_id, 0)
    if retries_used >= max_retries_per_group:
        _fail_keypad(
            shared,
            state,
            (
                f"Keypad verification group {group_id} failed after {retries_used} retry request(s): "
                f"{reason}"
            ),
        )

    first_step = state.group_plan[group_id][0]
    try:
        response = robot.request_button_retry(
            first_step["button_name"],
            job_id=job_id,
            reason=reason,
            step_id=first_step["step_id"],
            group_id=group_id,
            retry_scope="group",
            timeout=retry_command_timeout_s,
        )
    except Exception as exc:
        _fail_keypad(
            shared,
            state,
            f"Retry request failed for keypad group {group_id}: {exc}",
        )

    if not (response.get("accepted") or response.get("already_queued")):
        _fail_keypad(
            shared,
            state,
            f"Retry request rejected for keypad group {group_id}: {response.get('message')}",
        )

    if response.get("accepted"):
        state.group_retry_counts[group_id] = retries_used + 1
    state.retry_pending_groups.add(group_id)
    batch["retry_requested"] = True
    batch["resolved"] = True
    for attempt in batch["attempts"].values():
        attempt.retry_requested = True
        attempt.retry_replaced = True
        attempt.result = "group_retry_queued"
        attempt.note = reason
        attempt.retry_response = dict(response or {})
    _keypad_log(
        shared,
        (
            f"queued whole-group retry {state.group_retry_counts[group_id]}/{max_retries_per_group} "
            f"for {group_id}: {reason}"
        ),
        section="retry",
    )


def _match_structured_batches(
    meter: SSHMeter,
    shared: SharedState,
    state: KeypadRunState,
    *,
    robot: RobotClient,
    job_id: str,
    per_button_timeout_s: float,
    max_retries_per_group: int,
    retry_command_timeout_s: float,
) -> None:
    now = time.monotonic()
    for batch_key in state.attempt_batch_order:
        batch = state.attempt_batches[batch_key]
        if batch.get("resolved"):
            continue

        planned_steps = state.group_plan[batch["group_id"]]
        attempts = batch["attempts"]
        if any(step["step_id"] not in attempts for step in planned_steps):
            return
        if any(attempts[step["step_id"]].robot_pressed is None for step in planned_steps):
            return

        latest_pressed = max(
            attempts[step["step_id"]].pressed_monotonic_s or now
            for step in planned_steps
        )
        age_s = now - latest_pressed
        if age_s < state.journal_after_buffer_s:
            return

        target_step = next((step for step in planned_steps if step["role"] == "target"), None)
        probe_step = next((step for step in planned_steps if step["role"] == "stuck_probe"), None)
        future_names = _future_unresolved_button_names(state, batch_key)

        if target_step is not None and probe_step is not None:
            target = attempts[target_step["step_id"]]
            probe = attempts[probe_step["step_id"]]

            while state.journal_backlog and not target.meter_confirmed and not probe.meter_confirmed:
                entry = state.journal_backlog[0]
                observed = _norm(entry["button_name"])
                if entry.get("src") != "KEY_PAD_2":
                    _consume_journal_entry(shared, state, ignored_reason="stuck verification requires KEY_PAD_2")
                    continue
                if observed == target.button_name:
                    _confirm_structured_attempt(shared, state, target, _consume_journal_entry(shared, state))
                    break
                if observed == STUCK_PROBE_BUTTON:
                    _confirm_structured_attempt(shared, state, probe, _consume_journal_entry(shared, state))
                    batch["probe_before_target"] = True
                    break
                if observed in future_names:
                    break
                _consume_journal_entry(shared, state, ignored_reason="unexpected key before verification target")

            if target.meter_confirmed and not probe.meter_confirmed:
                while state.journal_backlog:
                    entry = state.journal_backlog[0]
                    observed = _norm(entry["button_name"])
                    if entry.get("src") != "KEY_PAD_2":
                        _consume_journal_entry(shared, state, ignored_reason="stuck probe requires KEY_PAD_2")
                        continue
                    if observed == STUCK_PROBE_BUTTON:
                        _confirm_structured_attempt(shared, state, probe, _consume_journal_entry(shared, state))
                        break
                    if observed in STUCK_TARGET_BUTTONS:
                        bad_entry = _consume_journal_entry(shared, state)
                        probe.result = "stuck_key_detected"
                        probe.note = f"POUND probe was reported by the meter as {observed}"
                        probe.meter_log_timestamp_text = bad_entry["timestamp_text"]
                        probe.meter_log_message = bad_entry["message"]
                        probe.meter_log_raw_line = bad_entry["raw_line"]
                        probe.meter_log_cursor = bad_entry["journal_cursor"]
                        _fail_keypad(
                            shared,
                            state,
                            (
                                f"STUCK KEYPAD BUTTON DETECTED: {target.button_name} at offset "
                                f"{list(target.offset_mm)} was followed by a physical POUND probe, "
                                f"but the meter reported {observed}. journal={bad_entry['raw_line']}"
                            ),
                        )
                    if observed in future_names:
                        break
                    _consume_journal_entry(shared, state, ignored_reason="unexpected key during stuck probe")

            if target.meter_confirmed and probe.meter_confirmed and not batch["probe_before_target"]:
                _complete_structured_group(shared, state, batch)
                continue

        else:
            step = planned_steps[0]
            attempt = attempts[step["step_id"]]
            while state.journal_backlog and not attempt.meter_confirmed:
                entry = state.journal_backlog[0]
                observed = _norm(entry["button_name"])
                if observed == attempt.button_name:
                    _confirm_structured_attempt(shared, state, attempt, _consume_journal_entry(shared, state))
                    break
                if observed in future_names:
                    break
                _consume_journal_entry(shared, state, ignored_reason="unexpected key before planned step")
            if attempt.meter_confirmed:
                _complete_structured_group(shared, state, batch)
                continue

        if age_s < per_button_timeout_s:
            return

        missing = [
            f"{attempts[step['step_id']].button_name}/{step['role']}"
            for step in planned_steps
            if not attempts[step["step_id"]].meter_confirmed
        ]
        reason = f"missing ordered meter confirmation for {', '.join(missing)} after {per_button_timeout_s:.1f}s"
        _request_structured_group_retry(
            robot,
            shared,
            state,
            batch,
            job_id=job_id,
            max_retries_per_group=max_retries_per_group,
            retry_command_timeout_s=retry_command_timeout_s,
            reason=reason,
        )


def _write_keypad_meta(shared: SharedState, state: KeypadRunState) -> None:
    meta = shared.device_meta.setdefault("keypad", {})
    meta.clear()
    meta.update(
        {
            "status": "pass" if state.success else "fail",
            "error": state.final_error or shared.last_error or "",
            "confirmed_counts": dict(state.confirmed_counts),
            "requested_required_counts": dict(state.requested_required_counts),
            "progress": {
                "current": state.progress_current,
                "total": state.progress_total,
            },
            "planned_steps": [dict(step) for step in state.press_plan],
            "completed_step_ids": sorted(state.completed_step_ids),
            "completed_group_ids": sorted(state.completed_group_ids),
            "group_retry_counts": dict(state.group_retry_counts),
            "physical_attempt_count": state.physical_attempt_count,
            "attempts": [_attempt_to_meta(attempt) for attempt in state.attempt_history],
            "program_done_data": dict(state.program_done_data or {}),
            "errors": list(state.errors),
            "journal": {
                "initial_cursor": state.initial_journal_cursor,
                "current_cursor": state.current_journal_cursor,
                "poll_count": state.journal_poll_count,
                "entries_processed": state.journal_entries_processed,
                "read_error_count": state.journal_read_error_count,
                "consecutive_read_errors": state.journal_consecutive_read_errors,
                "last_error": state.journal_last_error,
            },
            "duration_s": round(max(0.0, time.monotonic() - state.start_monotonic_s), 3),
        }
    )


def test_robot_keypad(meter: SSHMeter, shared: SharedState, **kwargs):
    """
    Navigate to the keypad diagnostics page, run the robot keypad program, and
    validate each press directly from robot events plus meter journal evidence.
    """
    func_name = inspect.currentframe().f_code.co_name
    raw_buttons = list(kwargs.get("buttons") or [])
    if not raw_buttons:
        raise ValueError("test_robot_keypad requires a non-empty buttons list")

    per_button_timeout_s = float(kwargs.get("per_button_timeout_s", 5.0))
    max_retries_per_group = max(
        0,
        int(kwargs.get("max_retries_per_group", kwargs.get("max_retries_per_button", 1))),
    )
    retry_command_timeout_s = float(kwargs.get("retry_command_timeout_s", 3.0))
    subtest = bool(kwargs.get("subtest", False))
    device_name = str(kwargs.get("device_name") or "robot_keypad")
    stop_on_failure = bool(kwargs.get("stop_on_failure", True))
    job_count = max(1, int(kwargs.get("job_count", 1)))
    verify_stuck = bool(kwargs.get("verify_stuck", True))
    back_enter_offsets_mm = kwargs.get("back_enter_offsets_mm", [[0.0, 0.0]])
    buttons, press_plan, requested_required_counts = _build_press_plan(
        raw_buttons,
        job_count=job_count,
        verify_stuck=verify_stuck,
        back_enter_offsets_mm=back_enter_offsets_mm,
    )
    planned_press_count = len(press_plan)
    retry_allowance = planned_press_count * max_retries_per_group
    max_duration_s = (
        float(kwargs["max_duration_s"])
        if kwargs.get("max_duration_s") is not None
        else (
            DEFAULT_MAX_DURATION_BASE_S
            + (DEFAULT_PER_PLANNED_PRESS_TIMEOUT_S * (planned_press_count + retry_allowance))
        )
    )
    robot_program_done_grace_s = float(kwargs.get("robot_program_done_grace_s", DEFAULT_ROBOT_PROGRAM_DONE_GRACE_S))
    poll_s = float(kwargs.get("poll_s", 0.5))
    debug_keypad = bool(kwargs.get("debug_keypad", False))
    journal_after_buffer_s = float(
        kwargs.get("journal_after_buffer_s", DEFAULT_JOURNAL_AFTER_BUFFER_S)
    )
    start_epoch_s = time.time()
    start_monotonic_s = time.monotonic()
    _keypad_log(shared, f"{meter.host} {func_name} 1/1")
    _keypad_log(
        shared,
        (
            f"expecting {planned_press_count} planned physical step(s) from "
            f"{len(buttons)} requested button(s) x {job_count} pass(es) | "
            f"verify_stuck={verify_stuck} | offsets={back_enter_offsets_mm} | "
            f"max_duration_s={max_duration_s:.1f} | "
            f"per_button_timeout_s={per_button_timeout_s:.1f} | "
            f"journal_after_buffer_s={journal_after_buffer_s:.1f} | "
            f"robot_program_done_grace_s={robot_program_done_grace_s:.1f} | "
            f"max_retries_per_group={max_retries_per_group}"
        ),
    )
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 0, planned_press_count)

    # Do not begin UI navigation or a journal read after an operator/monitor
    # has already cancelled the paired physical test.
    check_stop_event(shared)

    charuco_frame = kwargs.get("charuco_frame")
    if charuco_frame is None:
        raise ValueError("'charuco_frame' argument is required for the robot keypad test")

    meter.goto_keypad()
    initial_page_state = _maintain_keypad_page(meter, shared)
    if not initial_page_state.is_keypad_page:
        _keypad_log(shared, "warning: did NOT make it to the keypad page", section="ui")

    initial_journal_cursor, initial_journal_error = _get_initial_meter_journal_cursor(meter)
    state = KeypadRunState(
        expected_buttons=buttons,
        required_per_button=job_count,
        start_epoch_s=start_epoch_s,
        start_monotonic_s=start_monotonic_s,
        initial_journal_cursor=initial_journal_cursor,
        device_name=device_name,
        stop_on_failure=stop_on_failure,
        debug_keypad=debug_keypad,
        journal_after_buffer_s=journal_after_buffer_s,
        press_plan=press_plan,
        requested_required_counts=requested_required_counts,
    )
    _keypad_debug(
        shared,
        state,
        (
            f"startup kwargs: buttons={raw_buttons}, press_plan={press_plan}, poll_s={poll_s}, "
            f"max_duration_s={max_duration_s}, retry_command_timeout_s={retry_command_timeout_s}"
        ),
        section="init",
    )
    if initial_journal_error:
        state.journal_read_error_count = 1
        state.journal_consecutive_read_errors = 1
        state.journal_last_error = initial_journal_error
        state.journal_last_fetch_ok = False
        try:
            _fail_keypad(
                shared,
                state,
                f"Unable to initialize meter journal acquisition: {initial_journal_error}",
            )
        finally:
            shared.log(f"KeypadRunState = {state}")
            _write_keypad_meta(shared, state)
    _keypad_debug(
        shared,
        state,
        (
            f"initial meter journal cursor captured after keypad navigation | "
            f"cursor={state.initial_journal_cursor}"
        ),
        section="journal",
    )

    robot = RobotClient()
    robot.flush_event_queue()
    _keypad_debug(shared, state, "flushed any stale robot events before starting the test", section="robot")

    job_id = robot.run_program(
        "run_button_press",
        {
            "meter_type": meter.meter_type,
            "meter_id": meter.hostname,
            "press_plan_version": PRESS_PLAN_VERSION,
            "press_plan": press_plan,
            "charuco_frame": charuco_frame,
            "test": False,
            "burningstation_logfile_path": shared.logfile_path,
        },
    )
    _keypad_log(shared, f"started robot keypad job_id={job_id}", section="robot")

    button_events: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    collector_stop = threading.Event()
    collector_thread = threading.Thread(
        target=_collect_robot_button_events,
        args=(robot, job_id, button_events, collector_stop, shared),
        daemon=True,
    )
    collector_thread.start()
    _keypad_debug(shared, state, "started background robot event collector thread", section="robot")

    try:
        last_broadcast_progress = -1
        while True:
            check_stop_event(shared)

            _handle_structured_robot_events(
                button_events,
                shared,
                state,
            )

            _fetch_new_keypad_logs(meter, shared, state)
            _match_structured_batches(
                meter,
                shared,
                state,
                robot=robot,
                job_id=job_id,
                per_button_timeout_s=per_button_timeout_s,
                max_retries_per_group=max_retries_per_group,
                retry_command_timeout_s=retry_command_timeout_s,
            )

            if not subtest and state.progress_current != last_broadcast_progress:
                shared.broadcast_progress(
                    meter.host,
                    func_name,
                    state.progress_current,
                    state.progress_total,
                )
                last_broadcast_progress = state.progress_current

            if _all_buttons_satisfied(state):
                state.success = True
                state.final_error = ""
                shared.device_results[state.device_name] = "pass"
                _keypad_log(shared, "All keypad buttons were confirmed by the meter logs")
                try:
                    robot.finish_button_retries(
                        job_id=job_id,
                        reason="client confirmed final button registered",
                        timeout=retry_command_timeout_s,
                    )
                except Exception as exc:
                    _keypad_log(
                        shared,
                        f"finish_button_retries command failed after keypad success: {exc}",
                        section="robot",
                    )
                return

            found, data = robot.try_get_event("program_done", job_id=job_id, consume=False)
            if found:
                if state.program_done_seen_monotonic_s is None:
                    state.program_done_seen_monotonic_s = time.monotonic()
                    state.program_done_data = dict(data or {})
                    _keypad_log(
                        shared,
                        (
                            "received program_done before all keypad confirmations; "
                            f"waiting {robot_program_done_grace_s:.1f}s for late meter logs"
                        ),
                        section="robot",
                    )
                elif (
                    time.monotonic() - state.program_done_seen_monotonic_s >= robot_program_done_grace_s
                    and state.journal_last_fetch_ok
                ):
                    _fail_keypad(
                        shared,
                        state,
                        (
                            "received program_done before all keypad confirmations and "
                            f"the {robot_program_done_grace_s:.1f}s grace window expired. data="
                            f"{state.program_done_data}..."
                        ),
                    )

            elapsed_s = time.monotonic() - state.start_monotonic_s
            if elapsed_s > max_duration_s:
                if state.journal_consecutive_read_errors > 0:
                    _fail_keypad(
                        shared,
                        state,
                        (
                            f"Meter journal acquisition remained unavailable until max duration "
                            f"({max_duration_s:.1f} sec): {state.journal_last_error}"
                        ),
                    )
                _fail_keypad(shared, state, f"max duration exceeded ({max_duration_s:.1f} sec)")

            _maintain_keypad_page(meter, shared)

            time.sleep(poll_s)

    finally:
        collector_stop.set()
        collector_thread.join(timeout=1.0)
        _keypad_debug(
            shared,
            state,
            (
                f"final summary: success={state.success}, confirmed_counts={state.confirmed_counts}, "
                f"group_retry_counts={state.group_retry_counts}, backlog={len(state.journal_backlog)}, "
                f"journal_entries={state.journal_entries_processed}, "
                f"journal_read_errors={state.journal_read_error_count}"
            ),
            section="summary",
        )
        shared.log(f"KeypadRunState = {state}")
        _write_keypad_meta(shared, state)


def _abort_keypad_program(shared: SharedState) -> None:
    """Stop keypad motion after a local keypad failure without stopping solar."""
    try:
        RobotClient().send_command("abort_program")
        _keypad_log(shared, "Robot program aborted after keypad subtest failure", section="robot")
    except Exception as exc:
        _keypad_log(shared, f"Failed to abort robot program: {exc}", section="robot")


def _combined_stop_requested(shared: SharedState) -> bool:
    stop_event = getattr(shared, "stop_event", None)
    end_listener = getattr(shared, "end_listener", None)
    return bool(
        (stop_event is not None and stop_event.is_set())
        or (end_listener is not None and end_listener.is_set())
    )


def _interrupt_combined_meter_io(
    meter: SSHMeter,
    shared: SharedState,
    interrupted: threading.Event,
) -> None:
    """Close the shared SSH transport once to unblock a cancelled solar read."""
    if interrupted.is_set():
        return
    interrupted.set()
    close = getattr(meter, "close", None)
    if not callable(close):
        _keypad_log(
            shared,
            "Cancellation requested while solar was active, but meter has no close() method",
            section="solar",
        )
        return
    try:
        _keypad_log(
            shared,
            "Cancellation requested; closing meter SSH transport to interrupt solar journal I/O",
            section="solar",
        )
        close()
    except Exception as exc:
        _keypad_log(shared, f"Failed to close meter SSH transport during cancellation: {exc}", section="solar")


def _watch_combined_stop(
    meter: SSHMeter,
    shared: SharedState,
    watcher_done: threading.Event,
    interrupted: threading.Event,
) -> None:
    while not watcher_done.wait(COMBINED_SOLAR_JOIN_POLL_S):
        if _combined_stop_requested(shared):
            # stop_job() and critical listener faults already set stop_event.
            # end_listener normally is only set after the test returns, but if
            # another shutdown path sets it while this pair is active, turn it
            # into the same cooperative cancellation signal used by both
            # foreground keypad code and the solar worker.
            stop_event = getattr(shared, "stop_event", None)
            if stop_event is not None:
                stop_event.set()
            _interrupt_combined_meter_io(meter, shared, interrupted)
            return


def _join_combined_solar_worker(
    solar_thread: threading.Thread,
    meter: SSHMeter,
    shared: SharedState,
    interrupted: threading.Event,
) -> None:
    """Do not return from the composite while its solar worker is still alive."""
    while solar_thread.is_alive():
        solar_thread.join(COMBINED_SOLAR_JOIN_POLL_S)
        if _combined_stop_requested(shared):
            _interrupt_combined_meter_io(meter, shared, interrupted)
    solar_thread.join()


def test_robot_keypad_with_solar(meter: SSHMeter, shared: SharedState, **kwargs):
    """Run the independent solar check while the robot performs keypad presses.

    This is an intentionally paired physical-test program, not a general
    scheduler.  It preserves the normal solar and keypad result/meta keys so
    callers can continue to treat them as separate subtests.
    """
    solar_kwargs = dict(kwargs.pop("solar_kwargs"))
    keypad_kwargs = dict(kwargs)
    solar_error: Optional[Exception] = None
    keypad_error: Optional[Exception] = None
    watcher_done = threading.Event()
    meter_io_interrupted = threading.Event()

    shared.device_results["solar"] = "running"
    shared.device_results["robot_keypad"] = "running"

    def run_solar() -> None:
        nonlocal solar_error
        try:
            test_solar(
                meter,
                shared=shared,
                **{
                    **solar_kwargs,
                    "subtest": True,
                    "manage_meter_ui": False,
                },
            )
        except Exception as exc:
            solar_error = exc
            shared.device_results["solar"] = "fail"
            shared.log(f"solar subtest fail while keypad is active: {type(exc).__name__}: {exc}")
        else:
            if not shared.stop_event.is_set():
                shared.device_results["solar"] = "pass"

    solar_thread = threading.Thread(
        target=run_solar,
        name="robot-keypad-solar",
        daemon=True,
    )
    stop_watcher = threading.Thread(
        target=_watch_combined_stop,
        args=(meter, shared, watcher_done, meter_io_interrupted),
        name="robot-keypad-solar-stop-watcher",
        daemon=True,
    )
    _keypad_log(shared, "Starting solar check alongside robot keypad test", section="solar")
    stop_watcher.start()
    solar_started = False

    try:
        try:
            solar_thread.start()
            solar_started = True
        except Exception as exc:
            solar_error = exc
            shared.device_results["solar"] = "fail"
            shared.log(f"Failed to start solar worker: {type(exc).__name__}: {exc}")

        try:
            test_robot_keypad(
                meter,
                shared=shared,
                **{
                    **keypad_kwargs,
                    "subtest": True,
                    "device_name": "robot_keypad",
                    "stop_on_failure": False,
                },
            )
        except Exception as exc:
            keypad_error = exc
            shared.device_results["robot_keypad"] = "fail"
            _abort_keypad_program(shared)
    finally:
        # A keypad result must never cut the independent solar measurement
        # short.  test_solar's own finally turns both lamps off before this
        # join can return.
        try:
            if solar_started:
                _join_combined_solar_worker(
                    solar_thread,
                    meter,
                    shared,
                    meter_io_interrupted,
                )
        finally:
            watcher_done.set()
            stop_watcher.join()

    failures = []
    if keypad_error is not None:
        failures.append(f"robot_keypad: {keypad_error}")
    if solar_error is not None:
        failures.append(f"solar: {solar_error}")
    if failures:
        message = "; ".join(failures)
        shared.last_error = message
        raise StopAutomation(message)
