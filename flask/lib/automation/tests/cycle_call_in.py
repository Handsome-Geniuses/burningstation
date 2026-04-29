from html import unescape
import inspect
import re
import time
from typing import Optional

from lib.automation.helpers import check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


DEFAULT_CALL_IN_READY_TIMEOUT_S = 90.0
DEFAULT_CALL_IN_START_TIMEOUT_S = 20.0
DEFAULT_CALL_IN_COMPLETE_TIMEOUT_S = 180.0
DEFAULT_CALL_IN_RETURN_TIMEOUT_S = 20.0
DEFAULT_CALL_IN_POLL_S = 2.0
DEFAULT_CALL_IN_PAGE_SETTLE_S = 1.0
CALL_IN_READY_STATES = {"S1_WAITING_FOR_CALL_TIME", "S4_SUSPENDED"}
CALL_IN_ACTIVE_STATES = {"S2_WAITING_FOR_CONNECTION", "S3_WAITING_FOR_CALL_COMPLETE"}
CALL_IN_STATE_RE = re.compile(r"\bCIM:\s*state=(S\d+_[A-Z_]+)\b", re.IGNORECASE)
CALL_IN_REFERENCE_RE = re.compile(r'"reference"\s*:\s*(\d+)')
CALL_IN_REASON_RE = re.compile(r'"reasonMessage"\s*:\s*"([^"]*)"')


def _sleep_with_stop(shared: SharedState, seconds: float, poll_interval: float = 0.25) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        check_stop_event(shared)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(poll_interval, remaining))


def _strip_html(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _journal_since_now(meter: SSHMeter) -> str:
    return meter.cli("date '+%Y-%m-%d %H:%M:%S'")


def _get_call_in_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("call in", {})


def _extract_reference(line: str) -> Optional[int]:
    match = CALL_IN_REFERENCE_RE.search(line or "")
    if not match:
        return None
    return int(match.group(1))


def _parse_call_in_page(meter: SSHMeter) -> dict:
    state = meter.get_diagnostics_state(timeout=5.0)
    page_text = _strip_html(state["page_html"])
    cim_match = CALL_IN_STATE_RE.search(page_text)
    cim_state = cim_match.group(1).upper() if cim_match else None
    can_call_in = (
        "press" in page_text.lower()
        and "call in" in page_text.lower()
        and "wait for the current call in to complete" not in page_text.lower()
    )
    is_waiting = "wait for the current call in to complete" in page_text.lower()
    return {
        "title": state["title"],
        "cim_state": cim_state,
        "can_call_in": can_call_in or cim_state in CALL_IN_READY_STATES,
        "is_waiting": is_waiting or cim_state in CALL_IN_ACTIVE_STATES,
        "page_text": page_text,
    }


def _wait_for_call_in_ready(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
) -> tuple[dict, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_cim_state: Optional[str] = None
    last_mode: Optional[str] = None
    last_snapshot: Optional[dict] = None

    while True:
        check_stop_event(shared)
        snapshot = _parse_call_in_page(meter)
        last_snapshot = snapshot

        cim_state = snapshot["cim_state"] or "unknown"
        mode = "ready" if snapshot["can_call_in"] else "waiting"
        if cim_state != last_cim_state or mode != last_mode:
            shared.log(
                f"{meter.host} call-in ready wait {cycle_num}: "
                f"title={snapshot['title']!r} cim_state={cim_state} mode={mode}",
            )
            last_cim_state = cim_state
            last_mode = mode

        if snapshot["can_call_in"]:
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} call-in ready wait {cycle_num}: ready in {elapsed_s:.1f}s "
                f"(cim_state={cim_state})",
            )
            return snapshot, elapsed_s

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Call-in cycle {cycle_num} timed out waiting for ready state; "
                f"last_cim_state={(last_snapshot or {}).get('cim_state') or 'unknown'}"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _get_call_in_log_summary(meter: SSHMeter, since: str) -> dict:
    cmd = f'journalctl -u MS3_Platform.service --since "{since}" -n 1600 --no-pager'
    output = meter.cli(cmd)
    lines = [line.strip() for line in output.splitlines() if line.strip()]

    summary = {
        "line_count": len(lines),
        "call_in_requested": False,
        "waiting_for_call_complete": False,
        "call_in_sent": False,
        "call_in_reference": None,
        "reason_message": None,
        "call_in_response": False,
        "call_in_response_reference": None,
        "call_in_completed": False,
        "modem_connect": False,
        "modem_disconnect": False,
        "session_manager_started": False,
        "session_manager_completed": False,
        "rsync_started": False,
        "rsync_completed": False,
    }

    for line in lines:
        if "CallInManager:sGotoState: From S1_WAITING_FOR_CALL_TIME to S2_WAITING_FOR_CONNECTION" in line:
            summary["call_in_requested"] = True
        elif "CallInManager:sGotoState: From S2_WAITING_FOR_CONNECTION to S3_WAITING_FOR_CALL_COMPLETE" in line:
            summary["waiting_for_call_complete"] = True
        elif "SAGENT SEND:" in line and '"command": "callIn"' in line:
            summary["call_in_sent"] = True
            summary["call_in_reference"] = _extract_reference(line)
            reason_match = CALL_IN_REASON_RE.search(line)
            if reason_match:
                summary["reason_message"] = reason_match.group(1)
        elif '"command": "callInResponse"' in line:
            response_ref = _extract_reference(line)
            summary["call_in_response_reference"] = response_ref
            if summary["call_in_reference"] is None or response_ref == summary["call_in_reference"]:
                summary["call_in_response"] = True
        elif "CallInManager:sGotoState: From S3_WAITING_FOR_CALL_COMPLETE to S1_WAITING_FOR_CALL_TIME" in line:
            summary["call_in_completed"] = True
        elif "Meter:sSetIsConnected: MODEM CONNECT" in line:
            summary["modem_connect"] = True
        elif "Meter:sSetIsConnected: MODEM DISCONNECT" in line:
            summary["modem_disconnect"] = True
        elif "Meter:sProcessSAgentMessage: SAgent notifyCode=SESSION_MANAGER_STARTED" in line:
            summary["session_manager_started"] = True
        elif "Meter:sProcessSAgentMessage: SAgent notifyCode=SESSION_MANAGER_COMPLETED" in line:
            summary["session_manager_completed"] = True
        elif "Meter:sProcessSAgentMessage: SAgent notifyCode=RSYNC_STARTED" in line:
            summary["rsync_started"] = True
        elif "Meter:sProcessSAgentMessage: SAgent notifyCode=RSYNC_COMPLETED" in line:
            summary["rsync_completed"] = True

    return summary


def _summary_milestones(summary: dict) -> tuple[str, ...]:
    milestones = []
    ordered_keys = (
        ("call_in_requested", "requested"),
        ("waiting_for_call_complete", "waiting_for_call_complete"),
        ("call_in_sent", "call_in_sent"),
        ("modem_connect", "modem_connect"),
        ("session_manager_started", "session_manager_started"),
        ("rsync_started", "rsync_started"),
        ("rsync_completed", "rsync_completed"),
        ("session_manager_completed", "session_manager_completed"),
        ("call_in_response", "call_in_response"),
        ("call_in_completed", "call_in_completed"),
        ("modem_disconnect", "modem_disconnect"),
    )
    for key, label in ordered_keys:
        if summary.get(key):
            milestones.append(label)
    return tuple(milestones)


def _wait_for_call_in_start(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    since: str,
    timeout_s: float,
    poll_s: float,
) -> tuple[dict, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_milestones: tuple[str, ...] = tuple()

    while True:
        check_stop_event(shared)
        summary = _get_call_in_log_summary(meter, since)
        milestones = _summary_milestones(summary)
        if milestones != last_milestones:
            shared.log(
                f"{meter.host} call-in start wait {cycle_num}: milestones={list(milestones)} "
                f"ref={summary.get('call_in_reference')}",
            )
            last_milestones = milestones

        if summary["call_in_requested"] or summary["call_in_sent"] or summary["waiting_for_call_complete"]:
            return summary, time.time() - started

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Call-in cycle {cycle_num} did not show start activity within {timeout_s:.1f}s"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_call_in_response(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    since: str,
    timeout_s: float,
    poll_s: float,
) -> tuple[dict, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_milestones: tuple[str, ...] = tuple()

    while True:
        check_stop_event(shared)
        summary = _get_call_in_log_summary(meter, since)
        milestones = _summary_milestones(summary)
        if milestones != last_milestones:
            shared.log(
                f"{meter.host} call-in response wait {cycle_num}: milestones={list(milestones)} "
                f"ref={summary.get('call_in_reference')} response_ref={summary.get('call_in_response_reference')}",
            )
            last_milestones = milestones

        if summary["call_in_response"]:
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} call-in response wait {cycle_num}: matched response in {elapsed_s:.1f}s "
                f"(ref={summary.get('call_in_reference')})",
            )
            return summary, elapsed_s

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Call-in cycle {cycle_num} timed out waiting for callInResponse "
                f"after {timeout_s:.1f}s"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_call_in_return_ready(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
) -> tuple[bool, Optional[dict], float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_cim_state: Optional[str] = None

    while True:
        check_stop_event(shared)
        snapshot = _parse_call_in_page(meter)
        cim_state = snapshot["cim_state"] or "unknown"
        if cim_state != last_cim_state:
            shared.log(
                f"{meter.host} call-in return wait {cycle_num}: cim_state={cim_state}",
            )
            last_cim_state = cim_state

        if snapshot["can_call_in"]:
            return True, snapshot, time.time() - started

        remaining = deadline - time.time()
        if remaining <= 0:
            return False, snapshot, time.time() - started

        _sleep_with_stop(shared, min(poll_s, remaining))


def test_cycle_call_in(meter: SSHMeter, shared: SharedState, **kwargs):
    """Trigger manual Call-In from the diagnostics page and record observed milestones."""
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 1))
    ready_timeout_s = float(kwargs.get("ready_timeout_s", DEFAULT_CALL_IN_READY_TIMEOUT_S))
    start_timeout_s = float(kwargs.get("start_timeout_s", DEFAULT_CALL_IN_START_TIMEOUT_S))
    complete_timeout_s = float(kwargs.get("complete_timeout_s", DEFAULT_CALL_IN_COMPLETE_TIMEOUT_S))
    return_timeout_s = float(kwargs.get("return_timeout_s", DEFAULT_CALL_IN_RETURN_TIMEOUT_S))
    poll_s = float(kwargs.get("poll_s", DEFAULT_CALL_IN_POLL_S))
    page_settle_s = float(kwargs.get("page_settle_s", DEFAULT_CALL_IN_PAGE_SETTLE_S))
    subtest = bool(kwargs.get("subtest", False))

    shared.set_allowed(set(), reason="Call-in test uses UI and journal polling only")
    meter.goto_callin()
    _sleep_with_stop(shared, page_settle_s)

    for i in range(count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{count}")
        if not subtest:
            shared.broadcast_progress(meter.host, "call in", cycle_num, count)

        ready_snapshot, ready_elapsed_s = _wait_for_call_in_ready(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=ready_timeout_s,
            poll_s=poll_s,
        )

        journal_since = _journal_since_now(meter)
        meter.press("plus")
        shared.log(
            f"{meter.host} call-in cycle {cycle_num}: pressed plus from cim_state="
            f"{ready_snapshot.get('cim_state') or 'unknown'}",
        )

        _start_summary, start_elapsed_s = _wait_for_call_in_start(
            meter,
            shared,
            cycle_num=cycle_num,
            since=journal_since,
            timeout_s=start_timeout_s,
            poll_s=poll_s,
        )
        response_summary, response_elapsed_s = _wait_for_call_in_response(
            meter,
            shared,
            cycle_num=cycle_num,
            since=journal_since,
            timeout_s=complete_timeout_s,
            poll_s=poll_s,
        )

        ready_again, return_snapshot, return_elapsed_s = _wait_for_call_in_return_ready(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=return_timeout_s,
            poll_s=poll_s,
        )

        cycle_meta = {
            "ready_wait_s": round(ready_elapsed_s, 1),
            "start_wait_s": round(start_elapsed_s, 1),
            "response_wait_s": round(response_elapsed_s, 1),
            "return_wait_s": round(return_elapsed_s, 1),
            "ready_cim_state": ready_snapshot.get("cim_state"),
            "return_cim_state": (return_snapshot or {}).get("cim_state"),
            "page_ready_after_response": ready_again,
        }
        cycle_meta.update(response_summary)
        _get_call_in_meta(shared)[cycle_num] = cycle_meta

        shared.log(
            f"{meter.host} call-in cycle {cycle_num}: "
            f"response_ref={response_summary.get('call_in_response_reference')} "
            f"ready_again={ready_again} "
            f"milestones={list(_summary_milestones(response_summary))}",
        )

        if not ready_again:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: page did not return to ready state within "
                f"{return_timeout_s:.1f}s after response",
            )

        _sleep_with_stop(shared, page_settle_s)
