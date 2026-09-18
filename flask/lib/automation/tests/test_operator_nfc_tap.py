import html
import inspect
import json
import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple

from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


# Keep flask/lib/docs/meter/test_operator_nfc_tap.md in sync when changing this test.
JOURNAL_UNIT = "MS3_Platform.service"
JOURNAL_MAX_LINES = 600
PAGE_FETCH_TIMEOUT_S = 2.0
RECOVERY_OFF_SETTLE_S = 3.0
PROGRESS_PROGRAM = "operator_nfc_tap"

CONTACTLESS_PAGE_ALIASES = {
    "contact less",
    "contactless",
    "contactless emv",
    "nfc",
}

DIAGNOSTICS_TITLE_RE = re.compile(
    r"<div[^>]*class\s*=\s*(?:[\"']?diagtitle[\"']?)[^>]*>\s*"
    r"<div[^>]*>(?P<title>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
CARD_READ_RE = re.compile(
    r"\b(?:emv|nfc)\s+card\s+read\s*:\s*"
    r"(?P<masked>(?:[Xx\d]{4}[ \t]+){3}[Xx\d]{4})",
    re.IGNORECASE,
)
NFC_POWER_REPLY_RE = re.compile(
    r"KIOSK_(?P<module>NFC|NEO)\.[^\s]*->GENERIC_TERMINAL\.[^\s]*\s+"
    r"EMV_POWER_REPLY\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)",
    re.IGNORECASE,
)
TRANSACTION_RESULT_RE = re.compile(
    r"VirtualPCCreditProcessor:sProcessIPSBusMessage:\s*EMV_TRANS_RESULT:.*?"
    r"\bresultState=(?P<result_state>[A-Z0-9_]+)",
    re.IGNORECASE,
)
DISPLAY_OUTPUT_RE = re.compile(
    r"VirtualPCCreditProcessor:sProcessIPSBusMessage:\s*EMV_UI_OUTPUT:\s*"
    r"DISP\b.*?[\"'](?P<text>[^\"']*)[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NFCPageSnapshot:
    title: str
    on_contactless_page: bool
    card_masked: Optional[str]
    card_last4: Optional[str]


@dataclass
class OperatorNFCTapRunState:
    required_success_count: int
    start_monotonic_s: float
    initial_journal_cursor: str = ""
    current_journal_cursor: str = ""
    reader_state: str = "unknown"
    last_ui_html: str = ""
    card_last4s: List[str] = field(default_factory=list)
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    journal_events: List[Dict[str, Any]] = field(default_factory=list)
    journal_poll_count: int = 0
    journal_entries_processed: int = 0
    journal_read_error_count: int = 0
    journal_consecutive_read_errors: int = 0
    journal_last_error: str = ""
    ui_poll_count: int = 0
    ui_read_error_count: int = 0
    ui_consecutive_read_errors: int = 0
    ui_last_error: str = ""
    attempt_active: bool = False
    recovery_ready_monotonic_s: float = 0.0
    success: bool = False
    final_error: str = ""
    cleanup_attempted: bool = False
    cleanup_success: bool = False
    cleanup_error: str = ""


def _coerce_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"{name} must be a boolean value")


def _strip_html(value: str) -> str:
    text = html.unescape(value or "").replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_diagnostics_label(value: str) -> str:
    text = _strip_html(value).lower()
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_nfc_page(page_html: str) -> NFCPageSnapshot:
    title_match = DIAGNOSTICS_TITLE_RE.search(page_html or "")
    title = _strip_html(title_match.group("title")) if title_match else ""
    title_segments = [part.strip() for part in title.split(":") if part.strip()]
    final_title = (
        _normalize_diagnostics_label(title_segments[-1]) if title_segments else ""
    )
    on_contactless_page = final_title in CONTACTLESS_PAGE_ALIASES

    page_text = _strip_html(page_html)
    card_match = CARD_READ_RE.search(page_text)
    card_masked: Optional[str] = None
    card_last4: Optional[str] = None
    if card_match:
        card_masked = re.sub(r"\s+", " ", card_match.group("masked")).strip()
        final_group = card_masked.split()[-1]
        if final_group.isdigit() and len(final_group) == 4:
            card_last4 = final_group

    return NFCPageSnapshot(
        title=title,
        on_contactless_page=on_contactless_page,
        card_masked=card_masked,
        card_last4=card_last4,
    )


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


def _parse_journal_json_batch(text: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
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


def _decode_power_reply(payload: str) -> Optional[str]:
    try:
        tokens = [int(token, 16) for token in payload.split()]
    except ValueError:
        return None

    # KIOSK_NFC: ON=01 00, OFF=00 00.
    if len(tokens) == 2:
        if tokens == [0x01, 0x00]:
            return "on"
        if tokens == [0x00, 0x00]:
            return "off"
        return None

    # KIOSK_NEO: version byte followed by the state byte.
    if len(tokens) >= 4 and tokens[0] == 0x01:
        if tokens[1] == 0x01:
            return "on"
        if tokens[1] == 0x00:
            return "off"
    return None


def _current_attempt(state: OperatorNFCTapRunState) -> Optional[Dict[str, Any]]:
    if not state.attempt_active or not state.attempts:
        return None
    return state.attempts[-1]


def _record_journal_event(
    shared: SharedState,
    state: OperatorNFCTapRunState,
    event: Dict[str, Any],
) -> None:
    state.journal_events.append(event)
    attempt = _current_attempt(state)
    if attempt is not None:
        attempt["journal_events"].append(event)
    shared.log(
        "operator NFC journal event: "
        f"type={event['type']} | value={event.get('value')!r} | "
        f"module={event.get('module')!r} | timestamp={event['timestamp']} | "
        f"attempt={attempt['attempt_number'] if attempt else None}"
    )


def _poll_nfc_journal(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
) -> None:
    state.journal_poll_count += 1
    command = _journal_after_cursor_command(state.current_journal_cursor)
    try:
        code, output, error = meter.exec_parse(command)
        if code != 0:
            detail = str(error or output or f"exit code {code}").strip()
            raise RuntimeError(detail)
        entries = _parse_journal_json_batch(output)
    except Exception as exc:
        message = f"operator NFC journal poll failed: {exc}"
        state.journal_read_error_count += 1
        state.journal_consecutive_read_errors += 1
        if message != state.journal_last_error or state.journal_consecutive_read_errors == 1:
            shared.log(message)
        state.journal_last_error = message
        return

    if state.journal_consecutive_read_errors:
        shared.log("operator NFC journal acquisition recovered")
    state.journal_consecutive_read_errors = 0

    if not entries:
        return

    for entry in entries:
        message = entry["message"]

        power_match = NFC_POWER_REPLY_RE.search(message)
        if power_match:
            power_state = _decode_power_reply(power_match.group("payload"))
            if power_state is not None:
                state.reader_state = power_state
                _record_journal_event(
                    shared,
                    state,
                    {
                        "type": "power",
                        "value": power_state,
                        "module": f"KIOSK_{power_match.group('module').upper()}",
                        "payload": " ".join(
                            power_match.group("payload").upper().split()
                        ),
                        "timestamp": entry["timestamp"],
                        "cursor": entry["cursor"],
                    },
                )

        result_match = TRANSACTION_RESULT_RE.search(message)
        if result_match:
            _record_journal_event(
                shared,
                state,
                {
                    "type": "transaction_result",
                    "value": result_match.group("result_state").upper(),
                    "module": None,
                    "timestamp": entry["timestamp"],
                    "cursor": entry["cursor"],
                },
            )

        display_match = DISPLAY_OUTPUT_RE.search(message)
        if display_match:
            _record_journal_event(
                shared,
                state,
                {
                    "type": "display",
                    "value": display_match.group("text").strip(),
                    "module": None,
                    "timestamp": entry["timestamp"],
                    "cursor": entry["cursor"],
                },
            )

    # Advance only after the complete JSON batch parses and processes successfully.
    state.current_journal_cursor = entries[-1]["cursor"]
    state.journal_entries_processed += len(entries)


def _fetch_nfc_page(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
) -> Optional[Tuple[str, NFCPageSnapshot]]:
    state.ui_poll_count += 1
    try:
        page_html = meter.get_ui_page_html(timeout=PAGE_FETCH_TIMEOUT_S)
        snapshot = _parse_nfc_page(page_html)
    except Exception as exc:
        message = f"operator NFC UI read failed: {exc}"
        state.ui_read_error_count += 1
        state.ui_consecutive_read_errors += 1
        if message != state.ui_last_error or state.ui_consecutive_read_errors == 1:
            shared.log(message)
        state.ui_last_error = message
        return None

    if state.ui_consecutive_read_errors:
        shared.log("operator NFC UI acquisition recovered")
    state.ui_consecutive_read_errors = 0
    return page_html, snapshot


def _require_contactless_page(snapshot: NFCPageSnapshot) -> None:
    if not snapshot.on_contactless_page:
        raise RuntimeError(
            f"expected contactless diagnostics page, found {snapshot.title!r}"
        )


def _start_attempt(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
) -> None:
    attempt_number = len(state.attempts) + 1
    meter.press("plus")
    state.reader_state = "turning_on"
    state.attempt_active = True
    attempt = {
        "attempt_number": attempt_number,
        "started_elapsed_s": round(
            max(0.0, time.monotonic() - state.start_monotonic_s), 3
        ),
        "status": "waiting",
        "card_masked": None,
        "card_last4": None,
        "retry_reason": "",
        "completed_elapsed_s": None,
        "journal_events": [],
    }
    state.attempts.append(attempt)
    shared.log(
        f"operator NFC attempt {attempt_number} started with plus; "
        f"progress={len(state.card_last4s)}/{state.required_success_count}"
    )


def _finish_attempt_from_page(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
    snapshot: NFCPageSnapshot,
) -> None:
    attempt = _current_attempt(state)
    if attempt is None or snapshot.card_last4 is None:
        return

    last4 = snapshot.card_last4
    attempt["card_masked"] = snapshot.card_masked
    attempt["card_last4"] = last4
    attempt["completed_elapsed_s"] = round(
        max(0.0, time.monotonic() - state.start_monotonic_s), 3
    )
    state.attempt_active = False
    # Captured MS3 runs display the result only after NFC has powered off.
    state.reader_state = "off"

    if last4 == "0000":
        attempt["status"] = "retry"
        attempt["retry_reason"] = "no_card_timeout"
        shared.log(
            f"operator NFC attempt {attempt['attempt_number']} timed out without "
            "a card (last4=0000); re-arming"
        )
        return

    attempt["status"] = "pass"
    state.card_last4s.append(last4)
    completed = len(state.card_last4s)
    shared.log(
        f"operator NFC attempt {attempt['attempt_number']} passed | "
        f"last4={last4} | progress={completed}/{state.required_success_count}"
    )
    shared.broadcast_progress(
        meter.host,
        PROGRESS_PROGRAM,
        completed,
        state.required_success_count,
    )
    # TODO (Johnson): Update something on the UI for the operator to see


def _interrupt_active_attempt(
    shared: SharedState,
    state: OperatorNFCTapRunState,
    reason: str,
) -> None:
    attempt = _current_attempt(state)
    if attempt is None:
        return
    attempt["status"] = "retry"
    attempt["retry_reason"] = reason
    attempt["completed_elapsed_s"] = round(
        max(0.0, time.monotonic() - state.start_monotonic_s), 3
    )
    state.attempt_active = False
    shared.log(
        f"operator NFC attempt {attempt['attempt_number']} interrupted: {reason}"
    )


def _recover_contactless_page(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
    previous_title: str,
) -> None:
    shared.log(
        f"operator NFC left the contactless page ({previous_title!r}); recovering"
    )
    _interrupt_active_attempt(shared, state, "contactless_page_lost")
    meter.goto_nfc()
    page_html = meter.get_ui_page_html(timeout=PAGE_FETCH_TIMEOUT_S)
    snapshot = _parse_nfc_page(page_html)
    _require_contactless_page(snapshot)
    meter.press("minus")
    state.reader_state = "turning_off"
    state.recovery_ready_monotonic_s = time.monotonic() + RECOVERY_OFF_SETTLE_S
    state.last_ui_html = page_html
    shared.log(
        "operator NFC contactless page restored; sent minus and waiting for "
        f"{RECOVERY_OFF_SETTLE_S:.1f}s off-settle interval"
    )


def _fail_nfc(
    shared: SharedState,
    state: OperatorNFCTapRunState,
    message: str,
) -> None:
    state.final_error = message
    shared.last_error = message
    device = getattr(shared, "current_device", None) or "contactless"
    shared.device_results[device] = "fail"
    shared.log(message)
    shared.stop_event.set()
    raise StopAutomation(message)


def _cleanup_nfc(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorNFCTapRunState,
) -> None:
    state.cleanup_attempted = True
    try:
        page_html = meter.get_ui_page_html(timeout=PAGE_FETCH_TIMEOUT_S)
        snapshot = _parse_nfc_page(page_html)
        if not snapshot.on_contactless_page:
            shared.log(
                "operator NFC cleanup restoring contactless page before minus | "
                f"current_title={snapshot.title!r}"
            )
            meter.goto_nfc()
            page_html = meter.get_ui_page_html(timeout=PAGE_FETCH_TIMEOUT_S)
            snapshot = _parse_nfc_page(page_html)
            _require_contactless_page(snapshot)
        meter.press("minus")
        state.cleanup_success = True
        state.reader_state = "turning_off"
        shared.log("operator NFC cleanup sent minus from verified contactless page")
    except Exception as exc:
        state.cleanup_success = False
        state.cleanup_error = str(exc)
        shared.log(f"operator NFC cleanup failed: {state.cleanup_error}")


def _combine_errors(primary_error: str, cleanup_error: str) -> str:
    if primary_error and cleanup_error:
        return f"{primary_error}; cleanup failed: {cleanup_error}"
    if cleanup_error:
        return f"cleanup failed: {cleanup_error}"
    return primary_error


def _write_nfc_metadata(
    shared: SharedState,
    state: OperatorNFCTapRunState,
) -> None:
    meta = shared.device_meta.setdefault("contactless", {})
    meta.clear()
    meta.update(
        {
            "result": "pass" if state.success else "fail",
            "error": state.final_error,
            "elapsed_time": round(
                max(0.0, time.monotonic() - state.start_monotonic_s), 3
            ),
            "total_card_reads": len(state.card_last4s),
            "card_last4s": list(state.card_last4s),
            "cleanup": {
                "attempted": state.cleanup_attempted,
                "success": state.cleanup_success,
                "error": state.cleanup_error,
            },
        }
    )


def test_operator_nfc_tap(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
) -> None:
    """Run the operator-guided contactless-card tap test.

    The test opens the meter's Contact(less) diagnostics page, enables the NFC
    reader with the plus button, and waits for the UI to show a masked card
    number. Each non-``0000`` result counts as one successful tap; ``0000`` is
    treated as a no-card timeout and the reader is re-armed while time remains.
    Repeated taps from the same card count independently.

    Keyword arguments:

    - ``job_count=1``: number of successful tap cycles required.
    - ``max_duration_s=60.0``: overall timeout, including setup.
    - ``poll_s=0.75``: delay between UI and journal polls.
    - ``subtest=False``: identifies execution from ``operator_cycle_all``.

    Progress is broadcast throughout the run. Compact results, including the
    ordered card last-four values, are written to
    ``shared.device_meta["contactless"]``. The cleanup path always returns to
    the contactless page when necessary and presses minus to disable NFC.
    """
    func_name = inspect.currentframe().f_code.co_name
    state = OperatorNFCTapRunState(
        required_success_count=1,
        start_monotonic_s=time.monotonic(),
    )
    caught_exception: Optional[Exception] = None
    caught_traceback: Optional[TracebackType] = None

    try:
        subtest = _coerce_bool(kwargs.get("subtest", False), "subtest")
        max_duration_s = float(kwargs.get("max_duration_s", 60.0))
        poll_s = float(kwargs.get("poll_s", 0.75))
        job_count = int(kwargs.get("job_count", 1))
        if max_duration_s <= 0:
            raise ValueError("max_duration_s must be greater than zero")
        if poll_s <= 0:
            raise ValueError("poll_s must be greater than zero")
        if job_count <= 0:
            raise ValueError("job_count must be greater than zero")
        state.required_success_count = job_count

        shared.log(f"{meter.host} {func_name} 0/{job_count}")
        shared.log(
            f"{meter.host} operator NFC initialized | job_count={job_count} | "
            f"max_duration_s={max_duration_s:.1f} | poll_s={poll_s:.2f} | "
            f"subtest={subtest} | journal_max_lines={JOURNAL_MAX_LINES}"
        )
        shared.broadcast_progress(meter.host, PROGRESS_PROGRAM, 0, job_count)

        check_stop_event(shared)
        cursor = _initial_journal_cursor(meter)
        state.initial_journal_cursor = cursor
        state.current_journal_cursor = cursor
        shared.log(f"operator NFC initial journal cursor={cursor}")

        meter.goto_nfc()
        initial_page = meter.get_ui_page_html(timeout=PAGE_FETCH_TIMEOUT_S)
        initial_snapshot = _parse_nfc_page(initial_page)
        _require_contactless_page(initial_snapshot)
        state.last_ui_html = initial_page
        # goto_nfc() resets diagnostics before entering the page. The observed
        # MS3 page is idle/off until plus starts a transaction.
        state.reader_state = "off"
        shared.log(
            "operator NFC ready; present a contactless card after the reader "
            f"starts | page_title={initial_snapshot.title!r}"
        )

        while True:
            check_stop_event(shared)
            elapsed_s = time.monotonic() - state.start_monotonic_s
            if elapsed_s >= max_duration_s:
                acquisition_detail = ""
                if state.journal_consecutive_read_errors:
                    acquisition_detail += (
                        f"; journal unavailable: {state.journal_last_error}"
                    )
                if state.ui_consecutive_read_errors:
                    acquisition_detail += f"; UI unavailable: {state.ui_last_error}"
                _fail_nfc(
                    shared,
                    state,
                    f"max duration exceeded ({max_duration_s:.1f}s); captured "
                    f"{len(state.card_last4s)}/{job_count} successful NFC taps "
                    f"across {len(state.attempts)} attempts{acquisition_detail}",
                )

            _poll_nfc_journal(meter, shared, state)

            page_result = _fetch_nfc_page(meter, shared, state)
            if page_result is None:
                time.sleep(poll_s)
                continue
            page_html, snapshot = page_result

            if not snapshot.on_contactless_page:
                _recover_contactless_page(
                    meter,
                    shared,
                    state,
                    previous_title=snapshot.title,
                )
                time.sleep(poll_s)
                continue

            page_changed = page_html != state.last_ui_html
            if page_changed:
                shared.log(
                    "operator NFC UI changed | "
                    f"title={snapshot.title!r} | card={snapshot.card_masked!r}"
                )
                state.last_ui_html = page_html
                if state.attempt_active and snapshot.card_last4 is not None:
                    _finish_attempt_from_page(
                        meter,
                        shared,
                        state,
                        snapshot,
                    )

            if len(state.card_last4s) >= job_count:
                state.success = True
                shared.log(
                    f"operator NFC passed with {len(state.card_last4s)}/{job_count} "
                    f"successful taps | card_last4s={state.card_last4s}"
                )
                break

            now = time.monotonic()
            if (
                not state.attempt_active
                and now >= state.recovery_ready_monotonic_s
            ):
                if state.reader_state == "turning_off":
                    # The explicit recovery minus has had the same three-second
                    # timeout used by the legacy NFC monitor.
                    state.reader_state = "off"
                if state.reader_state == "off":
                    _start_attempt(meter, shared, state)

            time.sleep(poll_s)

    except Exception as exc:
        caught_exception = exc
        caught_traceback = exc.__traceback__
        state.success = False
        if not state.final_error:
            state.final_error = str(exc)
        shared.last_error = state.final_error
        shared.stop_event.set()
    finally:
        _cleanup_nfc(meter, shared, state)
        if not state.cleanup_success:
            state.success = False
            state.final_error = _combine_errors(
                state.final_error,
                state.cleanup_error,
            )

        device = getattr(shared, "current_device", None) or "contactless"
        shared.device_results[device] = "pass" if state.success else "fail"
        if not state.success:
            shared.last_error = state.final_error
            shared.stop_event.set()

        _write_nfc_metadata(shared, state)
        meta = shared.device_meta["contactless"]
        shared.log(
            "operator NFC final summary: "
            f"success={state.success} | error={state.final_error!r} | "
            f"successful_reads={meta['total_card_reads']}/{state.required_success_count} | "
            f"attempts={len(state.attempts)} | card_last4s={state.card_last4s} | "
            f"elapsed_time={meta['elapsed_time']} | "
            f"cleanup_success={state.cleanup_success}"
        )
        shared.log(
            "operator NFC final acquisition details: "
            f"journal_polls={state.journal_poll_count} | "
            f"journal_entries={state.journal_entries_processed} | "
            f"journal_read_errors={state.journal_read_error_count} | "
            f"initial_cursor={state.initial_journal_cursor!r} | "
            f"current_cursor={state.current_journal_cursor!r} | "
            f"ui_polls={state.ui_poll_count} | "
            f"ui_read_errors={state.ui_read_error_count} | "
            f"reader_state={state.reader_state}"
        )
        shared.log(
            "operator NFC final collected data: "
            f"attempts={state.attempts} | journal_events={state.journal_events}"
        )
        shared.broadcast_progress(
            meter.host,
            PROGRESS_PROGRAM,
            min(len(state.card_last4s), state.required_success_count),
            state.required_success_count,
        )

    if caught_exception is not None:
        raise caught_exception.with_traceback(caught_traceback)
    if not state.cleanup_success:
        raise StopAutomation(state.final_error)
