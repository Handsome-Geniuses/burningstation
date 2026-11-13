"""End-to-end call-in automation for the MS3 diagnostics Call In flow.

This test drives the same `CIMCallInNow()` path as the meter's Service >
Call In `+` key, then validates the session using three sources:

1. `cmd.main.meter:status` for live CIM / CS / MODEM state and PPP counters.
2. The supervisor's MS3 Modem journal stream for connection proof.
3. The supervisor's MS3 Platform journal stream for Session Agent and updater events.

See `flask/lib/docs/meter/cycle_call_in.md` for maintenance notes and expected
behavior.
"""

import inspect
import re
import threading
import time
from html import unescape
from typing import Optional

from lib.automation.helpers import check_stop_event, StopAutomation
from lib.meter.lifecycle import session_for, MeterInterrupted
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter

DEFAULT_CALL_IN_READY_TIMEOUT_S = 120.0
DEFAULT_CALL_IN_READY_STABLE_S = 3.0
DEFAULT_CALL_IN_START_TIMEOUT_S = 20.0
DEFAULT_CALL_IN_COMPLETION_TIMEOUT_S = 120.0
DEFAULT_CALL_IN_DISCONNECT_TIMEOUT_S = 45.0
DEFAULT_CALL_IN_POLL_S = 2.0
DEFAULT_CALL_IN_TRANSITION_OBSERVE_S = 20.0

CALL_IN_READY_STATE = "S1_WAITING_FOR_CALL_TIME"
CALL_IN_WAIT_CONNECTION_STATE = "S2_WAITING_FOR_CONNECTION"
CALL_IN_WAIT_COMPLETE_STATE = "S3_WAITING_FOR_CALL_COMPLETE"
CALL_IN_SUSPENDED_STATE = "S4_SUSPENDED"
CALL_IN_READY_STATES = {CALL_IN_READY_STATE, CALL_IN_SUSPENDED_STATE}

CS_WAITING_TO_CONNECT_STATE = "S1_WAITING_TO_CONNECT"
CS_CONNECTING_STATE = "S2_CONNECTING"
CS_CONNECTED_STATE = "S3_CONNECTED"
CS_DISCONNECTING_STATE = "S4_DISCONNECTING"
CS_DISCONNECTED_STATE = "S5_DISCONNECTED"
CS_ERROR_STATE = "S6_ERROR"
CS_RELEASED_STATES = {CS_DISCONNECTED_STATE, CS_ERROR_STATE}

MODEM_CONNECTED_STATE = "S4_CONNECTED"
MODEM_IDLE_STATE = "S1_IDLE"
MODEM_ERROR_STATE = "S7_ERROR"
MODEM_DISCONNECTED_STATES = (MODEM_IDLE_STATE, MODEM_ERROR_STATE)

RE_CIM_STATE = re.compile(r"\bCIM:\s*state=(?P<state>S\d+_[A-Z_]+|\(unknown[^)]*\))", re.IGNORECASE)
RE_CS_STATE = re.compile(r"\bCS:\s*state=(?P<state>S\d+_[A-Z_]+|\(unknown[^)]*\))", re.IGNORECASE)
RE_MODEM_STATE = re.compile(r"\bMODEM:\s*state=(?P<state>S\d+_[A-Z_]+|\(unknown[^)]*\))", re.IGNORECASE)
RE_CLIENTS = re.compile(r"Clients requesting connection:\s*(?P<clients>.*)", re.IGNORECASE)
RE_PPP_CONNECT_COUNT = re.compile(r"PPP connect count:\s*(?P<count>\d+)", re.IGNORECASE)
RE_PPP_DISCONNECT_COUNT = re.compile(r"PPP disconnect count:\s*(?P<count>\d+)", re.IGNORECASE)
RE_PPP_FAILED_CONNECT_COUNT = re.compile(r"PPP failed connect count:\s*(?P<count>\d+)", re.IGNORECASE)
RE_CSQ_TEXT = re.compile(r"\bcsq:\s*(?P<value>[^\r\n]+)", re.IGNORECASE)

RE_CALL_IN_SEND = re.compile(r'SAGENT SEND: .*"command"\s*:\s*"callIn"', re.IGNORECASE)
RE_CALL_IN_RESPONSE = re.compile(
    r'SAGENT RECV: .*"command"\s*:\s*"callInResponse"',
    re.IGNORECASE,
)
RE_SAGENT_REFERENCE = re.compile(r'"reference"\s*:\s*(?P<reference>\d+)', re.IGNORECASE)
RE_SAGENT_RESULT_FAIL = re.compile(r'"result"\s*:\s*-1(?:\D|$)', re.IGNORECASE)
RE_SESSION_MANAGER_STARTED = re.compile(
    r'"message"\s*:\s*"Try Session Manager"|SAgent notifyCode=SAGENT_NOTIFY_SESSION_MANAGER_STARTED',
    re.IGNORECASE,
)
RE_SESSION_MANAGER_COMPLETED = re.compile(
    r'"message"\s*:\s*"Session Manager Completed"|SAgent notifyCode=SAGENT_NOTIFY_SESSION_MANAGER_COMPLETED',
    re.IGNORECASE,
)
RE_SESSION_COMPLETE = re.compile(r'"message"\s*:\s*"Session complete"', re.IGNORECASE)
RE_RSYNC_STARTED = re.compile(r'"message"\s*:\s*"Rsync Started"', re.IGNORECASE)
RE_RSYNC_COMPLETED = re.compile(r'"message"\s*:\s*"Rsync Completed"', re.IGNORECASE)
RE_RUNSCRIPT_STARTED = re.compile(r'"message"\s*:\s*"Run Script Started"', re.IGNORECASE)
RE_RUNSCRIPT_COMPLETED = re.compile(r'"message"\s*:\s*"Run Script Completed"', re.IGNORECASE)
RE_UPDATE_ACTIVITY = re.compile(
    r"Installing legacy config|package update is pending|appCfg update is pending|"
    r"appOverlay update is pending|invoking update \(systemctl restart MS3_RunOnce\)|"
    r"Restarting, to use new legacy config|Update already installed|update files not found",
    re.IGNORECASE,
)
RE_UPDATE_RESTART = re.compile(
    r"invoking update \(systemctl restart MS3_RunOnce\)|Restarting, to use new legacy config",
    re.IGNORECASE,
)
RE_DOWNLOADED_UPDATE_CONFIG = re.compile(
    r"WRITE_CONFIG_ITEM updating:|Installed new printer templates|"
    r"Installing legacy config|(?:package|appCfg|appOverlay) update is pending",
    re.IGNORECASE,
)
RE_MS3_STOPPING = re.compile(r"\bStopping MS3 Platform\b", re.IGNORECASE)

RE_MODEM_CONNECT_REQUEST = re.compile(r"Requested to connect, State=", re.IGNORECASE)
RE_MODEM_DISCONNECT_REQUEST = re.compile(r"Requested to disconnect, State=", re.IGNORECASE)
RE_MODEM_STATE_CONNECTED = re.compile(r"From S\d+_[A-Z_]+ to S4_CONNECTED", re.IGNORECASE)
RE_MODEM_STATE_DISCONNECTING = re.compile(r"to S5_WAITING_TO_SHUT_DOWN|to S6_SHUTTING_DOWN", re.IGNORECASE)
RE_MODEM_STATE_IDLE = re.compile(r"to S1_IDLE", re.IGNORECASE)
RE_MODEM_SIGNAL = re.compile(
    r"Sent sig\. qual\. to client: rssi=(?P<rssi>\d+),\s*ber=(?P<ber>\d+)",
    re.IGNORECASE,
)
RE_MODEM_INFO = re.compile(
    r"Sent modem info rssi=(?P<rssi>\d+)\s*,\s*(?P<ber>\d+)",
    re.IGNORECASE,
)
RE_CONNECTION_CLIENTS_RELEASED = re.compile(
    r"Clients that need a connection:\s*\(none\)",
    re.IGNORECASE,
)
RE_CONNECTION_CLIENTS_STATUS = re.compile(r"Clients that need a connection:", re.IGNORECASE)
RE_MODEM_DISCONNECT_SUCCESS = re.compile(
    r"ModemDisconnect\(\) returned:\s*MODEM_RESULT_SUCCESS",
    re.IGNORECASE,
)
RE_PLATFORM_MODEM_DISCONNECT = re.compile(
    r"MODEM:\s*SendRemote:\s*CMD\.DISCONNECT|\bMODEM DISCONNECT\b",
    re.IGNORECASE,
)
RE_CALL_IN_UI_READY = re.compile(r"press\s*\[\s*\+\s*\]\s*to\s*call\s*in", re.IGNORECASE)
RE_CALL_IN_UI_WAIT = re.compile(
    r"wait\s+for\s+the\s+current\s+call\s+in\s+to\s+complete",
    re.IGNORECASE,
)
class CallInObservationError(TimeoutError):
    """Timeout that preserves the last status data observed by a wait loop."""

    def __init__(
        self,
        message: str,
        *,
        snapshot: Optional[dict] = None,
        lifecycle: Optional[dict] = None,
    ) -> None:
        super().__init__(message)
        self.snapshot = snapshot
        self.lifecycle = lifecycle


class _ManagedJournalCapture:
    """Capture the supervisor's live journal during one manual transaction.

    The supervisor owns a separate SSH journal follower and forwards live lines
    to session subscribers. This buffer lets the call-in reach a verdict after
    the session blocks ordinary SSHMeter commands for an update/restart.
    """

    def __init__(self, max_lines: int = 6000) -> None:
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._max_lines = max_lines

    def log(self, message: str, *, source=None, **_kwargs) -> None:
        if source != "supervisor.journal":
            return
        with self._lock:
            self._lines.append(message)
            if len(self._lines) > self._max_lines:
                del self._lines[:len(self._lines) - self._max_lines]

    def text(self) -> str:
        with self._lock:
            return "\n".join(self._lines)


def _debug_call_in(meter: SSHMeter, shared: SharedState, cycle_num: int, enabled: bool, message: str) -> None:
    """Write opt-in diagnostic context to the normal job/meter log."""
    if enabled:
        shared.log(f"{meter.host} call-in cycle {cycle_num} DEBUG: {message}")


def _new_lifecycle() -> dict:
    return {
        "saw_cim_wait_connection": False,
        "saw_cim_wait_complete": False,
        "saw_ready_return": False,
        "saw_cs_waiting_to_connect": False,
        "saw_cs_connecting": False,
        "saw_cs_connected": False,
        "saw_cs_disconnecting": False,
        "saw_modem_connected": False,
        "saw_modem_disconnected": False,
        "status_unavailable_after_start": False,
        "runtime_loss_after_start": False,
    }


def _sleep_with_stop(shared: SharedState, seconds: float, poll_interval: float = 0.25) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        check_stop_event(shared)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(poll_interval, remaining))


def _parse_int(pattern: re.Pattern, text: str) -> Optional[int]:
    match = pattern.search(text or "")
    if not match:
        return None
    return int(match.group("count"))


def _parse_meter_status(text: str) -> dict:
    cim_state = None
    cs_state = None
    modem_state = None
    clients = None
    csq_text = None

    cim_match = RE_CIM_STATE.search(text or "")
    if cim_match:
        cim_state = cim_match.group("state")

    cs_match = RE_CS_STATE.search(text or "")
    if cs_match:
        cs_state = cs_match.group("state")

    modem_match = RE_MODEM_STATE.search(text or "")
    if modem_match:
        modem_state = modem_match.group("state")

    clients_match = RE_CLIENTS.search(text or "")
    if clients_match:
        clients = _normalize_clients_text(clients_match.group("clients"))

    csq_match = RE_CSQ_TEXT.search(text or "")
    if csq_match:
        csq_text = csq_match.group("value").strip()

    return {
        "cim_state": cim_state,
        "cs_state": cs_state,
        "modem_state": modem_state,
        "clients": clients,
        "ppp_connect_count": _parse_int(RE_PPP_CONNECT_COUNT, text),
        "ppp_disconnect_count": _parse_int(RE_PPP_DISCONNECT_COUNT, text),
        "ppp_failed_connect_count": _parse_int(RE_PPP_FAILED_CONNECT_COUNT, text),
        "csq_text": csq_text,
        "raw": text,
    }


def _status_summary(snapshot: dict) -> str:
    parts = [
        f"cim={snapshot.get('cim_state') or 'unknown'}",
        f"cs={snapshot.get('cs_state') or 'unknown'}",
        f"modem={snapshot.get('modem_state') or 'unknown'}",
    ]

    clients = snapshot.get("clients")
    if clients:
        parts.append(f"clients={clients}")

    if snapshot.get("ppp_connect_count") is not None:
        parts.append(f"ppp_connect={snapshot['ppp_connect_count']}")

    if snapshot.get("ppp_disconnect_count") is not None:
        parts.append(f"ppp_disconnect={snapshot['ppp_disconnect_count']}")

    if snapshot.get("ppp_failed_connect_count") is not None:
        parts.append(f"ppp_failed={snapshot['ppp_failed_connect_count']}")

    if snapshot.get("csq_text"):
        parts.append(f"csq={snapshot['csq_text']}")

    return " | ".join(parts)


def _delta(after: Optional[int], before: Optional[int]) -> Optional[int]:
    if after is None or before is None:
        return None
    return after - before


def _strip_html(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_clients_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    # Some meter-status responses append the next HTML section on the same
    # logical line, for example "(none)<hr>Modem Service:".  It is not a
    # ConnectionServer client and must not make an idle snapshot look active.
    text = re.split(r"<hr\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return _strip_html(text)


def _clients_have_active_connection_need(value: Optional[str]) -> bool:
    text = _normalize_clients_text(value)
    if not text:
        return False
    return not text.lower().startswith("(none)")


def _get_call_in_ui_state(meter: SSHMeter) -> tuple[str, str]:
    page_text = _strip_html(meter.get_ui_page_html(timeout=2.0))
    normalized = page_text.lower()

    if RE_CALL_IN_UI_READY.search(normalized):
        return "ready", page_text
    if RE_CALL_IN_UI_WAIT.search(normalized):
        return "wait", page_text
    return "unknown", page_text


def _snapshot_is_ready(snapshot: dict) -> bool:
    return snapshot.get("cim_state") in CALL_IN_READY_STATES


def _snapshot_is_idle(snapshot: dict) -> bool:
    return (
        _snapshot_is_ready(snapshot)
        and snapshot.get("cs_state") in CS_RELEASED_STATES
        and snapshot.get("modem_state") in MODEM_DISCONNECTED_STATES
        and not _clients_have_active_connection_need(snapshot.get("clients"))
    )


def _wait_for_call_in_idle(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
    phase: str,
    stable_s: float = 0.0,
    require_ui_ready: bool = False,
) -> tuple[dict, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    idle_since: Optional[float] = None
    last_snapshot: Optional[dict] = None
    last_summary = None
    last_ui_state = None

    while True:
        check_stop_event(shared)
        session = session_for(meter)
        if session is not None and not session.ready:
            # Recovery can reset the UI. Never resume an old navigation path.
            raise MeterInterrupted(session.reason, session.epoch)

        try:
            snapshot = _parse_meter_status(meter.get_meter_status_text())
            last_snapshot = snapshot
        except Exception as exc:
            idle_since = None
            shared.log(
                f"{meter.host} call-in {phase} wait {cycle_num}: unable to read meter status ({exc}); retrying",
            )
            remaining = deadline - time.time()
            if remaining <= 0:
                raise CallInObservationError(
                    f"Call-in {phase} cycle {cycle_num} timed out while reading meter status",
                    snapshot=last_snapshot,
                ) from exc
            _sleep_with_stop(shared, min(poll_s, remaining))
            continue

        summary = _status_summary(snapshot)
        if summary != last_summary:
            shared.log(f"{meter.host} call-in {phase} wait {cycle_num}: {summary}")
            last_summary = summary

        if _snapshot_is_idle(snapshot):
            ui_ready = True
            if require_ui_ready:
                try:
                    ui_state, ui_text = _get_call_in_ui_state(meter)
                except Exception as exc:
                    shared.log(
                        f"{meter.host} call-in {phase} wait {cycle_num}: unable to read Call In page ({exc}); retrying",
                    )
                    ui_ready = False
                else:
                    ui_state_changed = ui_state != last_ui_state
                    if ui_state_changed:
                        shared.log(
                            f"{meter.host} call-in {phase} wait {cycle_num}: call-in page state={ui_state}",
                        )
                        last_ui_state = ui_state
                    if ui_state != "ready":
                        ui_ready = False
                        if ui_state == "unknown" and ui_state_changed:
                            shared.log(
                                f"{meter.host} call-in {phase} wait {cycle_num}: unexpected Call In page text -> {ui_text}",
                            )

            if not ui_ready:
                idle_since = None
            elif idle_since is None:
                idle_since = time.time()
            if ui_ready and (time.time() - idle_since) >= max(0.0, stable_s):
                elapsed_s = time.time() - started
                shared.log(
                    f"{meter.host} call-in {phase} wait {cycle_num}: ready in {elapsed_s:.1f}s",
                )
                return snapshot, elapsed_s
        else:
            idle_since = None

        remaining = deadline - time.time()
        if remaining <= 0:
            raise CallInObservationError(
                f"Call-in {phase} cycle {cycle_num} timed out waiting for ready/idle state; last={summary}",
                snapshot=snapshot,
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_call_in_lifecycle(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    start_timeout_s: float,
    completion_timeout_s: float,
    poll_s: float,
    *,
    proof_complete,
    request_started,
) -> tuple[Optional[dict], dict, float]:
    """Observe manual CIM progress while status is available.

    The journal callbacks confirm a fast request
    from the journal and finish from proof before CIM is fully idle. Session
    restriction returns control to the independent journal capture.
    """
    started = time.time()
    start_deadline = started + max(0.0, start_timeout_s)
    completion_deadline = start_deadline + max(0.0, completion_timeout_s)
    last_summary = None
    last_snapshot: Optional[dict] = None
    call_in_started = False
    lifecycle = _new_lifecycle()

    while True:
        check_stop_event(shared)

        session = session_for(meter)
        if session is not None and not session.ready:
            lifecycle["runtime_loss_after_start"] = True
            return None, lifecycle, time.time() - started

        try:
            snapshot = _parse_meter_status(meter.get_meter_status_text())
            last_snapshot = snapshot
        except Exception as exc:
            deadline = completion_deadline if call_in_started else start_deadline
            shared.log(
                f"{meter.host} call-in lifecycle {cycle_num}: unable to read meter status ({exc}); retrying",
            )
            if session is not None and not session.ready:
                lifecycle["runtime_loss_after_start"] = call_in_started
                return None, lifecycle, time.time() - started
            if call_in_started:
                lifecycle["status_unavailable_after_start"] = True
                # The journal subscriber still works if ordinary status reads
                # fail. Stop status polling and decide from its live evidence.
                return None, lifecycle, time.time() - started

            remaining = deadline - time.time()
            if remaining <= 0:
                raise CallInObservationError(
                    f"Call-in cycle {cycle_num} timed out while reading meter status",
                    snapshot=last_snapshot,
                    lifecycle=lifecycle,
                ) from exc
            _sleep_with_stop(shared, min(poll_s, remaining))
            continue

        summary = _status_summary(snapshot)
        if summary != last_summary:
            shared.log(f"{meter.host} call-in lifecycle {cycle_num}: {summary}")
            last_summary = summary

        cim_state = snapshot.get("cim_state")
        cs_state = snapshot.get("cs_state")
        modem_state = snapshot.get("modem_state")

        if not call_in_started:
            if cim_state in (CALL_IN_WAIT_CONNECTION_STATE, CALL_IN_WAIT_COMPLETE_STATE) or request_started():
                call_in_started = True
                shared.log(f"{meter.host} call-in cycle {cycle_num}: state machine started")
            elif time.time() > start_deadline:
                raise CallInObservationError(
                    f"Call-in cycle {cycle_num} never left a ready state; last={summary}",
                    snapshot=snapshot,
                    lifecycle=lifecycle,
                )

        if call_in_started:
            lifecycle["saw_cim_wait_connection"] |= cim_state == CALL_IN_WAIT_CONNECTION_STATE
            lifecycle["saw_cim_wait_complete"] |= cim_state == CALL_IN_WAIT_COMPLETE_STATE
            lifecycle["saw_cs_waiting_to_connect"] |= cs_state == CS_WAITING_TO_CONNECT_STATE
            lifecycle["saw_cs_connecting"] |= cs_state == CS_CONNECTING_STATE
            lifecycle["saw_cs_connected"] |= cs_state == CS_CONNECTED_STATE
            lifecycle["saw_cs_disconnecting"] |= cs_state == CS_DISCONNECTING_STATE
            lifecycle["saw_modem_connected"] |= modem_state == MODEM_CONNECTED_STATE
            if lifecycle["saw_modem_connected"]:
                lifecycle["saw_modem_disconnected"] |= modem_state in MODEM_DISCONNECTED_STATES

            if proof_complete(lifecycle, snapshot):
                return snapshot, lifecycle, time.time() - started

            if _snapshot_is_ready(snapshot):
                elapsed_s = time.time() - started
                lifecycle["saw_ready_return"] = True
                shared.log(
                    f"{meter.host} call-in cycle {cycle_num}: returned to ready state in {elapsed_s:.1f}s",
                )
                return snapshot, lifecycle, elapsed_s

            if time.time() > completion_deadline:
                raise CallInObservationError(
                    f"Call-in cycle {cycle_num} timed out waiting for return to ready state; last={summary}",
                    snapshot=snapshot,
                    lifecycle=lifecycle,
                )

        deadline = completion_deadline if call_in_started else start_deadline
        remaining = deadline - time.time()
        _sleep_with_stop(shared, min(poll_s, max(0.1, remaining)))


def _last_matching_line(text: str, pattern: re.Pattern) -> str:
    for line in reversed((text or "").splitlines()):
        if pattern.search(line):
            return line.strip()
    return ""


def _sagent_reference(line: str) -> Optional[int]:
    match = RE_SAGENT_REFERENCE.search(line or "")
    if not match:
        return None
    return int(match.group("reference"))


def _collect_platform_call_in_evidence(journal_text: str) -> dict:
    """Match the first post-trigger callIn to its response and bound its proof.

    A subsequent startup/scheduled call-in begins a new transaction. Client
    release only counts after session completion within the first window.
    """
    lines = (journal_text or "").splitlines()
    send_index = next((i for i, line in enumerate(lines) if RE_CALL_IN_SEND.search(line)), None)
    send_line = lines[send_index].strip() if send_index is not None else ""
    call_in_reference = _sagent_reference(send_line)
    next_send_index = None
    if send_index is not None:
        next_send_index = next(
            (i for i in range(send_index + 1, len(lines)) if RE_CALL_IN_SEND.search(lines[i])),
            None,
        )
    transaction_limit = next_send_index if next_send_index is not None else len(lines)

    response_index = None
    if send_index is not None:
        for i in range(send_index + 1, transaction_limit):
            line = lines[i]
            if not RE_CALL_IN_RESPONSE.search(line):
                continue
            response_reference = _sagent_reference(line)
            if call_in_reference is None or response_reference == call_in_reference:
                response_index = i
                break

    response_line = lines[response_index].strip() if response_index is not None else ""
    transaction_text = (
        "\n".join(lines[send_index:transaction_limit]) if send_index is not None else ""
    )
    post_send_text = transaction_text
    # Follow-on clients may still own the modem when CIM returns to ready.
    # A release marker counts only after the Session Agent completed this
    # transaction, and never after the next startup/scheduled call-in begins.
    completion_index = next(
        (i for i in range(send_index + 1, transaction_limit)
         if RE_SESSION_MANAGER_COMPLETED.search(lines[i]) or RE_SESSION_COMPLETE.search(lines[i])),
        None,
    ) if send_index is not None else None
    last_client_index = next(
        (i for i in range(transaction_limit - 1, completion_index, -1)
         if RE_CONNECTION_CLIENTS_STATUS.search(lines[i])),
        None,
    ) if completion_index is not None else None
    release_index = (
        last_client_index if last_client_index is not None
        and RE_CONNECTION_CLIENTS_RELEASED.search(lines[last_client_index]) else None
    )

    return {
        "call_in_send": send_index is not None,
        "call_in_reference": call_in_reference,
        "call_in_response": response_index is not None,
        "call_in_response_failed": bool(RE_SAGENT_RESULT_FAIL.search(response_line)),
        "session_manager_started": bool(RE_SESSION_MANAGER_STARTED.search(transaction_text)),
        "session_manager_completed": bool(RE_SESSION_MANAGER_COMPLETED.search(transaction_text)),
        "session_complete": bool(RE_SESSION_COMPLETE.search(transaction_text)),
        "rsync_started": bool(RE_RSYNC_STARTED.search(post_send_text)),
        "rsync_completed": bool(RE_RSYNC_COMPLETED.search(post_send_text)),
        "runscript_started": bool(RE_RUNSCRIPT_STARTED.search(post_send_text)),
        "runscript_completed": bool(RE_RUNSCRIPT_COMPLETED.search(post_send_text)),
        "update_activity": bool(RE_UPDATE_ACTIVITY.search(post_send_text)),
        "update_restart": bool(RE_UPDATE_RESTART.search(post_send_text)),
        "update_or_config_downloaded": bool(RE_DOWNLOADED_UPDATE_CONFIG.search(post_send_text)),
        "restart_started": bool(RE_MS3_STOPPING.search(post_send_text)),
        "next_call_in_send": next_send_index is not None,
        "clients_released": bool(RE_CONNECTION_CLIENTS_RELEASED.search(post_send_text)),
        "clients_released_after_session": release_index is not None,
        "modem_disconnect_success": bool(RE_MODEM_DISCONNECT_SUCCESS.search(post_send_text)),
        "platform_modem_disconnect": bool(RE_PLATFORM_MODEM_DISCONNECT.search(post_send_text)),
        "call_in_send_line": send_line,
        "call_in_response_line": response_line,
        "session_complete_line": _last_matching_line(transaction_text, RE_SESSION_COMPLETE),
        "clients_released_line": _last_matching_line(
            post_send_text,
            RE_CONNECTION_CLIENTS_RELEASED,
        ),
        "update_line": _last_matching_line(post_send_text, RE_UPDATE_ACTIVITY),
    }


def _collect_modem_call_in_evidence(journal_text: str) -> dict:
    signal_line = ""
    rssi = None
    ber = None

    for line in journal_text.splitlines():
        signal_match = RE_MODEM_SIGNAL.search(line)
        info_match = RE_MODEM_INFO.search(line)
        if signal_match:
            signal_line = line.strip()
            rssi = int(signal_match.group("rssi"))
            ber = int(signal_match.group("ber"))
        elif info_match:
            signal_line = line.strip()
            rssi = int(info_match.group("rssi"))
            ber = int(info_match.group("ber"))

    return {
        "connect_requested": bool(RE_MODEM_CONNECT_REQUEST.search(journal_text)),
        "disconnect_requested": bool(RE_MODEM_DISCONNECT_REQUEST.search(journal_text)),
        "connected": bool(RE_MODEM_STATE_CONNECTED.search(journal_text)),
        "disconnecting": bool(RE_MODEM_STATE_DISCONNECTING.search(journal_text)),
        "idle_after_disconnect": bool(RE_MODEM_STATE_IDLE.search(journal_text)),
        "signal_line": signal_line,
        "rssi": rssi,
        "ber": ber,
        "connect_line": _last_matching_line(journal_text, RE_MODEM_CONNECT_REQUEST),
        "disconnect_line": _last_matching_line(journal_text, RE_MODEM_DISCONNECT_REQUEST),
    }


def _validate_call_in_result(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    baseline_snapshot: dict,
    cleanup_snapshot: Optional[dict],
    lifecycle: dict,
    platform_evidence: dict,
    modem_evidence: dict,
    *,
    log_result: bool = True,
) -> dict:
    """Evaluate the original transaction's required proof and its sources.

    ``log_result=False`` is used only for repeated checks during live capture;
    the final call logs the complete verdict once.
    """
    connect_delta = None
    disconnect_delta = None
    failed_connect_delta = None

    if cleanup_snapshot is not None:
        connect_delta = _delta(
            cleanup_snapshot.get("ppp_connect_count"),
            baseline_snapshot.get("ppp_connect_count"),
        )
        disconnect_delta = _delta(
            cleanup_snapshot.get("ppp_disconnect_count"),
            baseline_snapshot.get("ppp_disconnect_count"),
        )
        failed_connect_delta = _delta(
            cleanup_snapshot.get("ppp_failed_connect_count"),
            baseline_snapshot.get("ppp_failed_connect_count"),
        )

    failures = []
    warnings = []
    call_in_started = (
        lifecycle["saw_cim_wait_connection"]
        or lifecycle["saw_cim_wait_complete"]
        or platform_evidence["call_in_send"]
    )
    connect_proved = (
        (connect_delta is not None and connect_delta >= 1)
        or lifecycle["saw_cs_connected"]
        or lifecycle["saw_modem_connected"]
        or modem_evidence["connect_requested"]
        or modem_evidence["connected"]
    )
    cleanup_release_proved = cleanup_snapshot is not None and _snapshot_is_idle(cleanup_snapshot)
    disconnect_proved = (
        cleanup_release_proved
        or (disconnect_delta is not None and disconnect_delta >= 1)
        or lifecycle["saw_cs_disconnecting"]
        or lifecycle["saw_modem_disconnected"]
        or modem_evidence["disconnect_requested"]
        or modem_evidence["disconnecting"]
        or modem_evidence["idle_after_disconnect"]
    )
    session_proved = (
        platform_evidence["session_manager_completed"] or platform_evidence["session_complete"]
    )
    release_proved = (
        disconnect_proved or platform_evidence["clients_released_after_session"]
        or platform_evidence["update_activity"]
    )

    connect_sources = []
    if connect_delta is not None and connect_delta >= 1:
        connect_sources.append("ppp_connect_counter")
    if lifecycle["saw_cs_connected"]:
        connect_sources.append("lifecycle_cs_connected")
    if lifecycle["saw_modem_connected"]:
        connect_sources.append("lifecycle_modem_connected")
    if modem_evidence["connect_requested"]:
        connect_sources.append("modem_journal_connect_request")
    if modem_evidence["connected"]:
        connect_sources.append("modem_journal_connected")

    release_sources = []
    if cleanup_release_proved:
        release_sources.append("final_status_snapshot")
    if disconnect_delta is not None and disconnect_delta >= 1:
        release_sources.append("ppp_disconnect_counter")
    if lifecycle["saw_cs_disconnecting"]:
        release_sources.append("lifecycle_cs_disconnecting")
    if lifecycle["saw_modem_disconnected"]:
        release_sources.append("lifecycle_modem_terminal_after_connected")
    if modem_evidence["disconnect_requested"]:
        release_sources.append("modem_journal_disconnect_request")
    if modem_evidence["disconnecting"]:
        release_sources.append("modem_journal_disconnecting")
    if modem_evidence["idle_after_disconnect"]:
        release_sources.append("modem_journal_idle")
    if platform_evidence["update_activity"]:
        release_sources.append("post_call_in_update_activity")
    if platform_evidence["clients_released_after_session"]:
        release_sources.append("platform_clients_released_after_session")

    if not call_in_started:
        failures.append("call-in never appeared to start")

    if not connect_proved:
        failures.append("missing modem/connection proof for call-in start")

    if not platform_evidence["call_in_send"]:
        failures.append("missing SAgent callIn request")

    if platform_evidence["call_in_response_failed"]:
        failures.append("SAgent returned callInResponse with result=-1")
    elif not platform_evidence["call_in_response"]:
        failures.append("missing SAgent callInResponse")

    if not session_proved:
        failures.append("missing Session Manager completion evidence")

    if not release_proved:
        failures.append("missing modem disconnect / connection-release evidence")

    if cleanup_release_proved and (
        cleanup_snapshot.get("cs_state") == CS_ERROR_STATE
        or cleanup_snapshot.get("modem_state") == MODEM_ERROR_STATE
    ) and (
        platform_evidence["call_in_response"]
        and not platform_evidence["call_in_response_failed"]
        and session_proved
    ):
        warnings.append("connection released through modem/ConnectionServer error terminal state")

    if failed_connect_delta is not None and failed_connect_delta > 0:
        warnings.append(f"PPP failed-connect counter increased by {failed_connect_delta}")

    response_summary = "failed" if platform_evidence["call_in_response_failed"] else "no"
    if platform_evidence["call_in_response"] and not platform_evidence["call_in_response_failed"]:
        response_summary = "yes"

    proof_summary = (
        f"started={'yes' if call_in_started else 'no'} | "
        f"connect={'yes' if connect_proved else 'no'}"
        f"[{','.join(connect_sources) or 'none'}] | "
        f"request={'yes' if platform_evidence['call_in_send'] else 'no'}"
        f"(ref={platform_evidence.get('call_in_reference') or 'n/a'}) | "
        f"response={response_summary} | "
        f"session={'yes' if session_proved else 'no'} | "
        f"release={'yes' if release_proved else 'no'}"
        f"[{','.join(release_sources) or 'none'}]"
    )
    if log_result:
        shared.log(f"{meter.host} call-in cycle {cycle_num}: validation proofs -> {proof_summary}")
        if failures:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: validation failed -> {'; '.join(failures)}"
            )
        for warning in warnings:
            shared.log(f"{meter.host} call-in cycle {cycle_num}: validation warning -> {warning}")

    return {
        "connect_delta": connect_delta,
        "disconnect_delta": disconnect_delta,
        "failed_connect_delta": failed_connect_delta,
        "call_in_started": call_in_started,
        "connect_proved": connect_proved,
        "session_proved": session_proved,
        "cleanup_release_proved": cleanup_release_proved,
        "disconnect_proved": disconnect_proved,
        "release_proved": release_proved,
        "connect_sources": connect_sources,
        "release_sources": release_sources,
        "failures": failures,
        "warnings": warnings,
    }


def _get_call_in_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("call_in", {})


def _snapshot_metadata(snapshot: Optional[dict]) -> Optional[dict]:
    if snapshot is None:
        return None
    return {
        "cim_state": snapshot.get("cim_state"),
        "cs_state": snapshot.get("cs_state"),
        "modem_state": snapshot.get("modem_state"),
        "clients": snapshot.get("clients"),
        "ppp_connect_count": snapshot.get("ppp_connect_count"),
        "ppp_disconnect_count": snapshot.get("ppp_disconnect_count"),
        "ppp_failed_connect_count": snapshot.get("ppp_failed_connect_count"),
        "csq_text": snapshot.get("csq_text"),
    }


def _managed_evidence(journal_text: str) -> tuple[dict, dict]:
    """Keep modem proof inside the first call-in's transaction window.

    Attach/connect can precede SAgent's send. Teardown must follow that send;
    a previous call-in's late idle marker cannot release this transaction.
    """
    lines = journal_text.splitlines()
    sends = [i for i, line in enumerate(lines) if RE_CALL_IN_SEND.search(line)]
    modem_limit = sends[1] if len(sends) > 1 else len(lines)
    modem = _collect_modem_call_in_evidence("\n".join(lines[:modem_limit]))
    if sends:
        teardown = _collect_modem_call_in_evidence("\n".join(lines[sends[0]:modem_limit]))
        for key in ("disconnect_requested", "disconnecting", "idle_after_disconnect", "disconnect_line"):
            modem[key] = teardown[key]
    return _collect_platform_call_in_evidence(journal_text), modem


def _complete_managed_call_in_cycle(
    meter: SSHMeter,
    shared: SharedState,
    session,
    capture: _ManagedJournalCapture,
    cycle_num: int,
    cycle_meta: dict,
    settings: dict,
    baseline_snapshot: dict,
    cycle_started: float,
) -> None:
    """Finish the triggered transaction from live proof, even during restriction.

    No status or UI command is sent after the supervisor restricts the meter.
    The short post-proof window observes update and MS3-stop markers; recovery
    and the next runtime's startup call-in belong to the supervisor.
    """
    lifecycle = _new_lifecycle()
    lifecycle_snapshot = None
    lifecycle_error = None
    started = time.monotonic()
    deadline = started + settings["start_timeout_s"] + settings["completion_timeout_s"] + settings["disconnect_timeout_s"]
    last_debug_signature = [None]

    def assess(snapshot=None):
        journal_text = capture.text()
        platform, modem = _managed_evidence(journal_text)
        validation = _validate_call_in_result(
            meter, shared, cycle_num, baseline_snapshot, snapshot, lifecycle,
            platform, modem, log_result=False,
        )
        if settings.get("debug", False):
            signature = (
                platform["call_in_send"], platform["call_in_response"],
                platform["call_in_response_failed"], validation["session_proved"],
                tuple(validation["connect_sources"]), tuple(validation["release_sources"]),
                tuple(validation["failures"]), session.ready, session.epoch,
            )
            if signature != last_debug_signature[0]:
                _debug_call_in(
                    meter, shared, cycle_num, True,
                    f"stream_lines={len(journal_text.splitlines())} "
                    f"connected={session.journal_connected} ready={session.ready} "
                    f"epoch={session.epoch} ref={platform['call_in_reference']} "
                    f"response={platform['call_in_response']} failed_response={platform['call_in_response_failed']} "
                    f"session={validation['session_proved']} connect={validation['connect_sources']} "
                    f"release={validation['release_sources']} missing={validation['failures']}",
                )
                last_debug_signature[0] = signature
        return platform, modem, validation

    def proof_complete(observed_lifecycle, snapshot):
        lifecycle.update(observed_lifecycle)
        _, _, validation = assess(snapshot if _snapshot_is_idle(snapshot) else None)
        return not validation["failures"]

    cycle_meta["phase"] = "lifecycle"
    try:
        lifecycle_snapshot, observed, elapsed = _wait_for_call_in_lifecycle(
            meter, shared, cycle_num,
            start_timeout_s=settings["start_timeout_s"],
            completion_timeout_s=settings["completion_timeout_s"],
            poll_s=settings["poll_s"],
            proof_complete=proof_complete,
            request_started=lambda: bool(RE_CALL_IN_SEND.search(capture.text())),
        )
        lifecycle.update(observed)
        cycle_meta["lifecycle_elapsed_s"] = round(elapsed, 1)
    except StopAutomation:
        raise
    except Exception as exc:
        lifecycle_error = str(exc)
        if isinstance(exc, CallInObservationError):
            lifecycle_snapshot = exc.snapshot
            if exc.lifecycle is not None:
                lifecycle.update(exc.lifecycle)
        shared.log(f"{meter.host} call-in cycle {cycle_num}: status observer ended: {type(exc).__name__}: {exc}")

    cleanup_snapshot = (
        lifecycle_snapshot if lifecycle_snapshot and _snapshot_is_idle(lifecycle_snapshot)
        and session.epoch == cycle_meta.get("trigger_epoch", session.epoch) else None
    )
    cleanup_source = "lifecycle" if cleanup_snapshot else None
    cleanup_error = None
    platform, modem, validation = assess(cleanup_snapshot)
    # CIM cannot finish the manual Session Agent transaction before sending
    # callIn. A short follower-lag allowance is enough; a later scheduled or
    # startup call-in must not turn this abandoned '+' into a pass.
    closed_without_send = lifecycle["saw_ready_return"] and not platform["call_in_send"]
    if closed_without_send:
        deadline = min(deadline, time.monotonic() + 5)
    # A completed response can be followed by RSYNC/RunScript release markers.
    # Observe the independent journal stream without asking a restricted meter
    # for status, and leave a short catch-up period after interruption.
    disrupted_at = None
    while validation["failures"] and not platform["call_in_response_failed"]:
        check_stop_event(shared)
        now = time.monotonic()
        if not session.ready and disrupted_at is None:
            disrupted_at = now
        if now >= deadline or (disrupted_at is not None and now - disrupted_at >= 8):
            break
        if session.ready and session.epoch == cycle_meta.get("trigger_epoch", session.epoch):
            try:
                snapshot = _parse_meter_status(meter.get_meter_status_text())
                if _snapshot_is_idle(snapshot):
                    cleanup_snapshot = snapshot
                    cleanup_source = "status"
            except MeterInterrupted:
                pass
            except Exception:
                pass  # The live journal remains the independent proof source.
        _sleep_with_stop(shared, min(settings["poll_s"], deadline - now))
        platform, modem, validation = assess(cleanup_snapshot)

    missed_manual_send = closed_without_send and not platform["call_in_send"]
    if missed_manual_send:
        shared.log(f"{meter.host} call-in cycle {cycle_num}: CIM returned to ready without a manual callIn send")
    # A matched response and release can precede the updater decision. The
    # archive's largest observed response-to-commit gap is 11.7 seconds, so a
    # 20-second window covers that path without following the restarted app.
    observed_s = 0.0
    if not validation["failures"]:
        cycle_meta["phase"] = "observe_transition"
        observe_started = time.monotonic()
        observe_s = max(0.0, settings.get("transition_observe_s", DEFAULT_CALL_IN_TRANSITION_OBSERVE_S))
        while True:
            check_stop_event(shared)
            platform, modem, validation = assess(cleanup_snapshot)
            restart_detected = platform["restart_started"] or (
                not platform["next_call_in_send"] and (
                    session.phase == "restarting"
                    or (cycle_meta.get("trigger_generation") is not None
                        and session.generation is not None
                        and session.generation != cycle_meta["trigger_generation"])
                )
            )
            observed_s = time.monotonic() - observe_started
            if restart_detected or platform["next_call_in_send"] or observed_s >= observe_s:
                break
            _sleep_with_stop(shared, min(settings["poll_s"], observe_s - observed_s))

        # On a stable runtime, later controls need the local Call In state to
        # become idle. Once an update/restart restricts the session, the
        # supervisor owns that handoff and no further meter read is safe.
        if session.ready and session.epoch == cycle_meta.get("trigger_epoch", session.epoch) and cleanup_snapshot is None:
            cycle_meta["phase"] = "cleanup"
            try:
                cleanup_snapshot, cleanup_elapsed = _wait_for_call_in_idle(
                    meter, shared, cycle_num, settings["disconnect_timeout_s"],
                    settings["poll_s"], "cleanup",
                )
                cycle_meta["cleanup_elapsed_s"] = round(cleanup_elapsed, 1)
                cleanup_source = "cleanup"
            except StopAutomation:
                raise
            except MeterInterrupted:
                pass
            except Exception as exc:
                cleanup_error = str(exc)
                shared.log(f"{meter.host} call-in cycle {cycle_num}: cleanup observer ended: {type(exc).__name__}: {exc}")

    if session.epoch != cycle_meta.get("trigger_epoch", session.epoch):
        # A newly recovered runtime's idle status cannot release the manual
        # transaction that ran in the prior generation.
        cleanup_snapshot = None
        cleanup_source = None
    # Cleanup may overlap an updater transition; include any final live lines
    # before freezing metadata and the verdict.
    platform, modem, validation = assess(cleanup_snapshot)
    restart_detected = platform["restart_started"] or (
        not platform["next_call_in_send"] and (
            session.phase == "restarting"
            or (cycle_meta.get("trigger_generation") is not None
                and session.generation is not None
                and session.generation != cycle_meta["trigger_generation"])
        )
    )

    cycle_meta["phase"] = "validate"
    validation = _validate_call_in_result(
        meter, shared, cycle_num, baseline_snapshot, cleanup_snapshot,
        lifecycle, platform, modem,
    )
    cycle_meta.update({
        "lifecycle": dict(lifecycle),
        "lifecycle_snapshot": _snapshot_metadata(lifecycle_snapshot),
        "lifecycle_error": lifecycle_error,
        "cleanup_snapshot": _snapshot_metadata(cleanup_snapshot),
        "cleanup_error": cleanup_error,
        "effective_cleanup_source": cleanup_source,
        "effective_cleanup_snapshot": _snapshot_metadata(cleanup_snapshot),
        "evidence_source": "supervisor_journal",
        "journal_stream_connected": session.journal_connected,
        "manual_window_closed_without_send": missed_manual_send,
        "platform_evidence": platform,
        "modem_evidence": modem,
        "validation": validation,
        "connect_delta": validation["connect_delta"],
        "disconnect_delta": validation["disconnect_delta"],
        "failed_connect_delta": validation["failed_connect_delta"],
        "rssi": modem["rssi"],
        "ber": modem["ber"],
        "session_manager_started": platform["session_manager_started"],
        "session_manager_completed": platform["session_manager_completed"],
        "session_complete": platform["session_complete"],
        "update_activity": platform["update_activity"],
        "update_restart": platform["update_restart"],
        "update_or_config_downloaded": platform["update_or_config_downloaded"],
        "restart_detected": restart_detected,
        "follow_on_call_in_seen": platform["next_call_in_send"],
        "transition_observed_s": round(observed_s, 1),
        "transition_observation_complete": not validation["failures"] and observed_s >= max(
            0.0, settings.get("transition_observe_s", DEFAULT_CALL_IN_TRANSITION_OBSERVE_S)
        ),
        "runtime_loss_after_start": lifecycle["runtime_loss_after_start"],
        "total_elapsed_s": round(time.time() - cycle_started, 1),
    })
    if validation["failures"]:
        raise RuntimeError("; ".join(validation["failures"]))
    cycle_meta.update(status="pass", phase="complete", error=None)
    shared.log(
        f"{meter.host} call-in cycle {cycle_num}: pass in {cycle_meta['total_elapsed_s']:.1f}s "
        f"from supervisor journal (ref={platform['call_in_reference']}, "
        f"release={','.join(validation['release_sources'])})"
    )
    shared.extras.pop("call_in_in_flight", None)


def _run_call_in_cycle(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    cycle_meta: dict,
    settings: dict,
    cycle_started: float,
) -> None:
    """Trigger one supervised manual call-in and validate that transaction.

    The pre-trigger wait may restart this iteration. Once '+' could have been
    delivered, its journal window is never replayed, even if MS3 restarts.
    """
    session = session_for(meter)
    if session is None or session.supervisor is None:
        raise RuntimeError("Call In requires an active meter supervisor")

    cycle_meta["phase"] = "wait_for_journal"
    shared.attempt_epoch = session.wait_ready(shared)
    shared.disruption_event.clear()
    shared.extras.pop("call_in_in_flight", None)
    journal_deadline = time.monotonic() + settings["ready_timeout_s"]
    while True:
        check_stop_event(shared)
        with session.condition:
            if not session.ready:
                raise MeterInterrupted(session.reason, session.epoch)
            if session.journal_connected:
                break
            remaining = journal_deadline - time.monotonic()
            if remaining <= 0:
                raise CallInObservationError(
                    f"Call-in cycle {cycle_num} timed out waiting for supervisor journal capture"
                )
            session.condition.wait(min(0.25, remaining))

    cycle_meta["phase"] = "navigate_to_call_in"
    meter.goto_callin()

    cycle_meta["phase"] = "pre_check"
    baseline_snapshot, ready_elapsed_s = _wait_for_call_in_idle(
        meter,
        shared,
        cycle_num=cycle_num,
        timeout_s=settings["ready_timeout_s"],
        poll_s=settings["poll_s"],
        phase="pre-check",
        stable_s=settings["ready_stable_s"],
        require_ui_ready=True,
    )
    cycle_meta["ready_elapsed_s"] = round(ready_elapsed_s, 1)
    cycle_meta["baseline_snapshot"] = _snapshot_metadata(baseline_snapshot)
    shared.log(
        f"{meter.host} call-in pre-check {cycle_num}: ready after {ready_elapsed_s:.1f}s | "
        f"{_status_summary(baseline_snapshot)}"
    )

    cycle_meta["phase"] = "start_call_in"
    cycle_meta["trigger_epoch"] = session.epoch
    cycle_meta["trigger_generation"] = session.generation
    capture = _ManagedJournalCapture()
    with session.condition:
        if not session.ready or not session.journal_connected or session.epoch != cycle_meta["trigger_epoch"]:
            # No '+' was sent. The outer pre-trigger retry navigates again.
            raise MeterInterrupted(session.reason, session.epoch)
        session.subscribers.add(capture)
    shared.log(f"{meter.host} call-in cycle {cycle_num}: press '+' on Service:Call In")
    shared.extras["call_in_in_flight"] = True
    shared.lifecycle_observer = True
    try:
        try:
            meter.press("plus")
        except MeterInterrupted:
            # The press might have reached MS3 before the restriction arrived.
            # Retain this transaction window and never send '+' again.
            shared.log("MS3 interrupted the call-in trigger; retaining the original transaction window")
        _complete_managed_call_in_cycle(
            meter, shared, session, capture, cycle_num, cycle_meta,
            settings, baseline_snapshot, cycle_started,
        )
    finally:
        with session.condition:
            session.subscribers.discard(capture)


def test_cycle_call_in(meter: SSHMeter, shared: SharedState, **kwargs):
    """Run ``job_count`` independent call-ins, retaining per-cycle proof.

    On failure metadata remains in ``shared.device_meta['call_in']`` so the
    job summary can distinguish a missing response from a meter disruption.
    """
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    subtest = bool(kwargs.get("subtest", False))
    settings = {
        "debug": bool(kwargs.get("debug", False)),
        "ready_timeout_s": float(
            kwargs.get("ready_timeout_s", DEFAULT_CALL_IN_READY_TIMEOUT_S)
        ),
        "ready_stable_s": float(kwargs.get("ready_stable_s", DEFAULT_CALL_IN_READY_STABLE_S)),
        "start_timeout_s": float(kwargs.get("start_timeout_s", DEFAULT_CALL_IN_START_TIMEOUT_S)),
        "completion_timeout_s": float(
            kwargs.get("completion_timeout_s", DEFAULT_CALL_IN_COMPLETION_TIMEOUT_S)
        ),
        "disconnect_timeout_s": float(
            kwargs.get("disconnect_timeout_s", DEFAULT_CALL_IN_DISCONNECT_TIMEOUT_S)
        ),
        "poll_s": float(kwargs.get("state_poll_s", DEFAULT_CALL_IN_POLL_S)),
        "transition_observe_s": float(
            kwargs.get("transition_observe_s", DEFAULT_CALL_IN_TRANSITION_OBSERVE_S)
        ),
    }

    call_in_meta = _get_call_in_meta(shared)
    for i in range(job_count):
        cycle_num = i + 1
        cycle_started = time.time()
        cycle_meta = {
            "status": "running",
            "phase": "initialize",
            "error": None,
            "cycle": cycle_num,
            "job_count": job_count,
            "debug": settings["debug"],
        }
        call_in_meta[cycle_num] = cycle_meta

        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        _debug_call_in(
            meter, shared, cycle_num, settings["debug"],
            f"timeouts=start:{settings['start_timeout_s']}s completion:{settings['completion_timeout_s']}s "
            f"disconnect:{settings['disconnect_timeout_s']}s transition:{settings['transition_observe_s']}s",
        )
        try:
            if not subtest:
                shared.broadcast_progress(meter.host, "call in", cycle_num, job_count)

            pretrigger_deadline = time.monotonic() + 900
            while True:
                try:
                    _run_call_in_cycle(
                        meter,
                        shared,
                        cycle_num=cycle_num,
                        cycle_meta=cycle_meta,
                        settings=settings,
                        cycle_started=cycle_started,
                    )
                    break
                except MeterInterrupted as exc:
                    session = session_for(meter)
                    if session is None or shared.extras.get("call_in_in_flight"):
                        raise
                    remaining = pretrigger_deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    shared.log(
                        f"{meter.host} call-in cycle {cycle_num}: pre-trigger interruption "
                        f"({exc}); waiting to navigate again"
                    )
                    shared.attempt_epoch = session.wait_ready(shared, timeout=remaining)
                    shared.disruption_event.clear()
                    retries = cycle_meta.get("pretrigger_restarts", 0) + 1
                    cycle_meta.clear()
                    cycle_meta.update(status="running", phase="initialize", error=None,
                                      cycle=cycle_num, job_count=job_count,
                                      debug=settings["debug"],
                                      pretrigger_restarts=retries)
        except Exception as exc:
            cycle_meta.update(
                {
                    "status": "fail",
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                    "total_elapsed_s": round(time.time() - cycle_started, 1),
                }
            )
            if isinstance(exc, CallInObservationError) and exc.snapshot is not None:
                cycle_meta["last_observed_snapshot"] = _snapshot_metadata(exc.snapshot)
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: failure metadata -> {cycle_meta}"
            )
            raise
        finally:
            # The observer exemption belongs only to this transaction. A later
            # call-in iteration must start with ordinary lifecycle checks.
            shared.lifecycle_observer = False
