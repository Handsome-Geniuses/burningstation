"""End-to-end call-in automation for the MS3 diagnostics Call In flow.

This test drives the same `CIMCallInNow()` path as the meter's Service >
Call In `+` key, then validates the session using three sources:

1. `cmd.main.meter:status` for live CIM / CS / MODEM state and PPP counters.
2. `journalctl -u MS3_Modem.service` for compact modem attach/detach proof.
3. `journalctl -u MS3_Platform.service` for Session Agent and updater events.

See `CALL_IN_TEST.md` in this directory for maintenance notes and expected
behavior.
"""

import inspect
import re
import time
from datetime import datetime, timedelta
from html import unescape
from typing import Optional

from lib.automation.helpers import check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter

DEFAULT_CALL_IN_READY_TIMEOUT_S = 120.0
DEFAULT_CALL_IN_READY_STABLE_S = 3.0
DEFAULT_CALL_IN_START_TIMEOUT_S = 20.0
DEFAULT_CALL_IN_COMPLETION_TIMEOUT_S = 120.0
DEFAULT_CALL_IN_DISCONNECT_TIMEOUT_S = 45.0
DEFAULT_CALL_IN_RECOVERY_TIMEOUT_S = 180.0
DEFAULT_CALL_IN_POST_RECOVERY_GUARD_S = 75.0
DEFAULT_CALL_IN_POST_RECOVERY_TIMEOUT_S = 180.0
DEFAULT_CALL_IN_STATUS_LOSS_GRACE_S = 8.0
DEFAULT_CALL_IN_STARTUP_GUARD_S = 180.0
DEFAULT_CALL_IN_POLL_S = 2.0
DEFAULT_CALL_IN_PLATFORM_JOURNAL_LINES = 1500
DEFAULT_CALL_IN_MODEM_JOURNAL_LINES = 100
DEFAULT_CALL_IN_STARTUP_PLATFORM_JOURNAL_LINES = 1500
DEFAULT_CALL_IN_POST_GRACE_S = 2.0

CALL_IN_READY_STATE = "S1_WAITING_FOR_CALL_TIME"
CALL_IN_WAIT_CONNECTION_STATE = "S2_WAITING_FOR_CONNECTION"
CALL_IN_WAIT_COMPLETE_STATE = "S3_WAITING_FOR_CALL_COMPLETE"
CALL_IN_SUSPENDED_STATE = "S4_SUSPENDED"
CALL_IN_READY_STATES = {CALL_IN_READY_STATE, CALL_IN_SUSPENDED_STATE}

CS_WAITING_TO_CONNECT_STATE = "S1_WAITING_TO_CONNECT"
CS_CONNECTING_STATE = "S2_CONNECTING"
CS_CONNECTED_STATE = "S3_CONNECTED"
CS_DISCONNECTING_STATE = "S4_DISCONNECTING"
CS_BUSY_STATES = {
    CS_WAITING_TO_CONNECT_STATE,
    CS_CONNECTING_STATE,
    CS_CONNECTED_STATE,
    CS_DISCONNECTING_STATE,
}

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
RE_CALL_IN_RESPONSE_FAIL = re.compile(
    r'SAGENT RECV: .*"command"\s*:\s*"callInResponse".*"result"\s*:\s*-1',
    re.IGNORECASE,
)
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
RE_CALL_IN_UI_READY = re.compile(r"press\s*\[\s*\+\s*\]\s*to\s*call\s*in", re.IGNORECASE)
RE_CALL_IN_UI_WAIT = re.compile(
    r"wait\s+for\s+the\s+current\s+call\s+in\s+to\s+complete",
    re.IGNORECASE,
)
RE_JOURNAL_BOUNDS = re.compile(
    r"-- Logs begin at (?P<start>.+?), end at (?P<end>.+?)\. --",
    re.IGNORECASE,
)
RE_PLATFORM_RUNTIME_START = re.compile(r"\bMS3:main:\s*starting,\s*version:", re.IGNORECASE)
RE_PLATFORM_SERVICE_START = re.compile(r"systemd\[\d+\]: Starting MS3 Platform", re.IGNORECASE)
RE_STARTUP_CALL_IN = re.compile(r"\bMS3:sRestartCallIn:\s*startup call-in\b", re.IGNORECASE)


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
        "saw_splash_after_start": False,
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


def _journal_since_now(meter: SSHMeter) -> str:
    return _format_meter_time(_get_meter_now(meter))


def _get_meter_now(meter: SSHMeter) -> datetime:
    value = meter.cli("date '+%Y-%m-%d %H:%M:%S'")
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def _format_meter_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_journal_bound(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None

    text = re.sub(r"^[A-Za-z]{3}\s+", "", text)
    text = re.sub(r"\s+[+-]\d{2}(?::?\d{2})?$", "", text)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_journal_bounds(text: str) -> tuple[Optional[datetime], Optional[datetime]]:
    match = RE_JOURNAL_BOUNDS.search(text or "")
    if not match:
        return None, None
    return _parse_journal_bound(match.group("start")), _parse_journal_bound(match.group("end"))


def _parse_journal_line_time(line: str, year: int) -> Optional[datetime]:
    text = (line or "").strip()
    if len(text) < 15:
        return None
    try:
        return datetime.strptime(f"{year} {text[:15]}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return None


def _age_seconds(now: datetime, then: Optional[datetime]) -> Optional[float]:
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds())


def _format_age(age_s: Optional[float]) -> str:
    if age_s is None:
        return "n/a"
    return f"{age_s:.1f}s"


def _last_matching_timestamp(
    text: str,
    pattern: re.Pattern,
    year: int,
    not_before: Optional[datetime] = None,
) -> Optional[datetime]:
    for line in reversed((text or "").splitlines()):
        if not pattern.search(line):
            continue

        timestamp = _parse_journal_line_time(line, year)
        if timestamp is None:
            continue
        if not_before is not None and timestamp < not_before:
            continue
        return timestamp

    return None


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
        clients = clients_match.group("clients").strip()

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
        and snapshot.get("cs_state") not in CS_BUSY_STATES
        and snapshot.get("modem_state") in MODEM_DISCONNECTED_STATES
    )


def _safe_in_splash(meter: SSHMeter) -> bool:
    try:
        return meter.in_splash()
    except Exception:
        return False


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
    last_summary = None
    last_ui_state = None

    while True:
        check_stop_event(shared)

        try:
            snapshot = _parse_meter_status(meter.get_meter_status_text())
        except Exception as exc:
            shared.log(
                f"{meter.host} call-in {phase} wait {cycle_num}: unable to read meter status ({exc}); retrying",
            )
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Call-in {phase} cycle {cycle_num} timed out while reading meter status"
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

            if idle_since is None:
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
            raise TimeoutError(
                f"Call-in {phase} cycle {cycle_num} timed out waiting for ready/idle state; last={summary}"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_call_in_lifecycle(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    start_timeout_s: float,
    completion_timeout_s: float,
    poll_s: float,
    status_loss_grace_s: float,
) -> tuple[Optional[dict], dict, float]:
    started = time.time()
    start_deadline = started + max(0.0, start_timeout_s)
    completion_deadline = start_deadline + max(0.0, completion_timeout_s)
    last_summary = None
    call_in_started = False
    status_failure_since: Optional[float] = None
    lifecycle = _new_lifecycle()

    while True:
        check_stop_event(shared)

        try:
            snapshot = _parse_meter_status(meter.get_meter_status_text())
        except Exception as exc:
            deadline = completion_deadline if call_in_started else start_deadline
            shared.log(
                f"{meter.host} call-in lifecycle {cycle_num}: unable to read meter status ({exc}); retrying",
            )
            if call_in_started:
                lifecycle["status_unavailable_after_start"] = True
                splash = _safe_in_splash(meter)
                lifecycle["saw_splash_after_start"] |= splash
                if status_failure_since is None:
                    status_failure_since = time.time()
                if splash or ((time.time() - status_failure_since) >= max(0.0, status_loss_grace_s)):
                    lifecycle["runtime_loss_after_start"] = True
                    shared.log(
                        f"{meter.host} call-in cycle {cycle_num}: meter runtime became unavailable after call-in start; "
                        f"switching to recovery handling",
                    )
                    return None, lifecycle, time.time() - started

            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Call-in cycle {cycle_num} timed out while reading meter status"
                ) from exc
            _sleep_with_stop(shared, min(poll_s, remaining))
            continue

        status_failure_since = None
        summary = _status_summary(snapshot)
        if summary != last_summary:
            shared.log(f"{meter.host} call-in lifecycle {cycle_num}: {summary}")
            last_summary = summary

        cim_state = snapshot.get("cim_state")
        cs_state = snapshot.get("cs_state")
        modem_state = snapshot.get("modem_state")

        lifecycle["saw_cim_wait_connection"] |= cim_state == CALL_IN_WAIT_CONNECTION_STATE
        lifecycle["saw_cim_wait_complete"] |= cim_state == CALL_IN_WAIT_COMPLETE_STATE
        lifecycle["saw_cs_waiting_to_connect"] |= cs_state == CS_WAITING_TO_CONNECT_STATE
        lifecycle["saw_cs_connecting"] |= cs_state == CS_CONNECTING_STATE
        lifecycle["saw_cs_connected"] |= cs_state == CS_CONNECTED_STATE
        lifecycle["saw_cs_disconnecting"] |= cs_state == CS_DISCONNECTING_STATE
        lifecycle["saw_modem_connected"] |= modem_state == MODEM_CONNECTED_STATE
        lifecycle["saw_modem_disconnected"] |= modem_state in MODEM_DISCONNECTED_STATES

        if not call_in_started:
            if cim_state in (CALL_IN_WAIT_CONNECTION_STATE, CALL_IN_WAIT_COMPLETE_STATE):
                call_in_started = True
                shared.log(f"{meter.host} call-in cycle {cycle_num}: state machine started")
            elif time.time() > start_deadline:
                raise TimeoutError(
                    f"Call-in cycle {cycle_num} never left a ready state; last={summary}"
                )
        else:
            if _snapshot_is_ready(snapshot):
                elapsed_s = time.time() - started
                lifecycle["saw_ready_return"] = True
                shared.log(
                    f"{meter.host} call-in cycle {cycle_num}: returned to ready state in {elapsed_s:.1f}s",
                )
                return snapshot, lifecycle, elapsed_s

            if time.time() > completion_deadline:
                raise TimeoutError(
                    f"Call-in cycle {cycle_num} timed out waiting for return to ready state; last={summary}"
                )

        deadline = completion_deadline if call_in_started else start_deadline
        remaining = deadline - time.time()
        _sleep_with_stop(shared, min(poll_s, max(0.1, remaining)))


def _wait_for_meter_status_recovery(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
) -> tuple[Optional[dict], dict, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    recovery = {
        "attempted": True,
        "recovered": False,
        "saw_splash": False,
        "saw_status_unavailable": False,
    }
    last_probe = None

    while True:
        check_stop_event(shared)

        try:
            snapshot = _parse_meter_status(meter.get_meter_status_text())
            recovery["recovered"] = True
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: meter runtime recovered in {elapsed_s:.1f}s | "
                f"{_status_summary(snapshot)}",
            )
            return snapshot, recovery, elapsed_s
        except Exception:
            recovery["saw_status_unavailable"] = True
            splash = _safe_in_splash(meter)
            recovery["saw_splash"] |= splash
            probe = "splash" if splash else "unreachable"
            if probe != last_probe:
                shared.log(
                    f"{meter.host} call-in cycle {cycle_num}: waiting for meter runtime recovery ({probe})",
                )
                last_probe = probe

        remaining = deadline - time.time()
        if remaining <= 0:
            return None, recovery, time.time() - started

        _sleep_with_stop(shared, min(poll_s, remaining))


def _observe_post_recovery_guard(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    observe_s: float,
    timeout_s: float,
    poll_s: float,
) -> tuple[dict, float]:
    if observe_s <= 0:
        snapshot, elapsed_s = _wait_for_call_in_idle(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=timeout_s,
            poll_s=poll_s,
            phase="post-recovery settle",
        )
        return snapshot, elapsed_s

    started = time.time()
    observe_deadline = started + max(0.0, observe_s)
    deadline = started + max(timeout_s, observe_s)
    last_summary = None

    while True:
        check_stop_event(shared)

        snapshot = _parse_meter_status(meter.get_meter_status_text())
        summary = _status_summary(snapshot)
        if summary != last_summary:
            shared.log(f"{meter.host} call-in post-recovery guard {cycle_num}: {summary}")
            last_summary = summary

        if time.time() >= observe_deadline and _snapshot_is_idle(snapshot):
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: post-recovery guard clear after {elapsed_s:.1f}s",
            )
            return snapshot, elapsed_s

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Call-in cycle {cycle_num} timed out during post-recovery guard; last={summary}"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def _get_service_journal(
    meter: SSHMeter,
    service: str,
    since: str,
    max_lines: int,
    include_previous_boot: bool = False,
) -> str:
    if max_lines <= 0:
        return ""

    chunks = []
    boots = (-1, 0) if include_previous_boot else (0,)
    for boot in boots:
        cmd = (
            f'journalctl -u {service} --since "{since}" '
            f"-n {max_lines} --no-pager -o cat -b {boot}"
        )
        try:
            text = meter.cli(cmd)
        except Exception:
            text = ""
        if text:
            chunks.append(text)

    return "\n".join(chunks).strip()


def _get_raw_service_journal(
    meter: SSHMeter,
    service: str,
    since: str,
    max_lines: int,
) -> str:
    if max_lines <= 0:
        return ""

    cmd = f'journalctl -u {service} --since "{since}" -n {max_lines} --no-pager'
    try:
        return meter.cli(cmd)
    except Exception:
        return ""


def _last_matching_line(text: str, pattern: re.Pattern) -> str:
    for line in reversed((text or "").splitlines()):
        if pattern.search(line):
            return line.strip()
    return ""


def _collect_platform_call_in_evidence(journal_text: str) -> dict:
    return {
        "call_in_send": bool(RE_CALL_IN_SEND.search(journal_text)),
        "call_in_response": bool(RE_CALL_IN_RESPONSE.search(journal_text)),
        "call_in_response_failed": bool(RE_CALL_IN_RESPONSE_FAIL.search(journal_text)),
        "session_manager_started": bool(RE_SESSION_MANAGER_STARTED.search(journal_text)),
        "session_manager_completed": bool(RE_SESSION_MANAGER_COMPLETED.search(journal_text)),
        "session_complete": bool(RE_SESSION_COMPLETE.search(journal_text)),
        "rsync_started": bool(RE_RSYNC_STARTED.search(journal_text)),
        "rsync_completed": bool(RE_RSYNC_COMPLETED.search(journal_text)),
        "runscript_started": bool(RE_RUNSCRIPT_STARTED.search(journal_text)),
        "runscript_completed": bool(RE_RUNSCRIPT_COMPLETED.search(journal_text)),
        "update_activity": bool(RE_UPDATE_ACTIVITY.search(journal_text)),
        "update_restart": bool(RE_UPDATE_RESTART.search(journal_text)),
        "call_in_send_line": _last_matching_line(journal_text, RE_CALL_IN_SEND),
        "call_in_response_line": _last_matching_line(journal_text, RE_CALL_IN_RESPONSE),
        "session_complete_line": _last_matching_line(journal_text, RE_SESSION_COMPLETE),
        "update_line": _last_matching_line(journal_text, RE_UPDATE_ACTIVITY),
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


def _format_delta(name: str, delta: Optional[int]) -> str:
    if delta is None:
        return f"{name}=n/a"
    return f"{name}={delta:+d}"


def _wait_for_startup_call_in_guard(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    guard_s: float,
    platform_journal_max_lines: int,
    poll_s: float,
) -> dict:
    result = {
        "checked": guard_s > 0,
        "runtime_age_s": None,
        "boot_age_s": None,
        "startup_seen": False,
        "startup_age_s": None,
    }
    if guard_s <= 0:
        return result

    started = time.time()
    last_summary = None

    while True:
        check_stop_event(shared)

        try:
            now_dt = _get_meter_now(meter)
        except Exception as exc:
            shared.log(
                f"{meter.host} call-in startup guard {cycle_num}: unable to read meter time ({exc}); retrying",
            )
            _sleep_with_stop(shared, poll_s)
            continue

        lookback_s = guard_s + 120.0
        since = _format_meter_time(now_dt - timedelta(seconds=lookback_s))
        platform_journal = _get_raw_service_journal(
            meter,
            service="MS3_Platform.service",
            since=since,
            max_lines=platform_journal_max_lines,
        )

        boot_start_dt, _ = _parse_journal_bounds(platform_journal)
        runtime_start_dt = _last_matching_timestamp(
            platform_journal,
            RE_PLATFORM_RUNTIME_START,
            year=now_dt.year,
        )
        if runtime_start_dt is None:
            runtime_start_dt = _last_matching_timestamp(
                platform_journal,
                RE_PLATFORM_SERVICE_START,
                year=now_dt.year,
            )
        startup_call_in_dt = _last_matching_timestamp(
            platform_journal,
            RE_STARTUP_CALL_IN,
            year=now_dt.year,
            not_before=runtime_start_dt,
        )

        runtime_age_s = _age_seconds(now_dt, runtime_start_dt)
        boot_age_s = _age_seconds(now_dt, boot_start_dt)
        startup_age_s = _age_seconds(now_dt, startup_call_in_dt)

        result.update(
            {
                "runtime_age_s": runtime_age_s,
                "boot_age_s": boot_age_s,
                "startup_seen": startup_call_in_dt is not None,
                "startup_age_s": startup_age_s,
            }
        )

        summary = (
            f"runtime_age={_format_age(runtime_age_s)} | "
            f"boot_age={_format_age(boot_age_s)} | "
            f"startup_seen={'yes' if startup_call_in_dt is not None else 'no'}"
        )
        if summary != last_summary:
            shared.log(f"{meter.host} call-in startup guard {cycle_num}: {summary}")
            last_summary = summary

        if startup_call_in_dt is not None:
            shared.log(
                f"{meter.host} call-in startup guard {cycle_num}: startup call-in already started; "
                f"continuing to regular pre-check",
            )
            return result

        guard_age_s = runtime_age_s if runtime_age_s is not None else boot_age_s
        if guard_age_s is not None and guard_age_s >= guard_s:
            shared.log(
                f"{meter.host} call-in startup guard {cycle_num}: no startup marker seen by "
                f"{_format_age(guard_age_s)}; continuing with regular pre-check",
            )
            return result

        if guard_age_s is None and (time.time() - started) >= guard_s:
            shared.log(
                f"{meter.host} call-in startup guard {cycle_num}: unable to derive startup age "
                f"within {guard_s:.1f}s; continuing with regular pre-check",
            )
            return result

        _sleep_with_stop(shared, poll_s)


def _validate_call_in_result(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    baseline_snapshot: dict,
    cleanup_snapshot: Optional[dict],
    lifecycle: dict,
    platform_evidence: dict,
    modem_evidence: dict,
) -> dict:
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
    disconnect_proved = (
        (disconnect_delta is not None and disconnect_delta >= 1)
        or lifecycle["saw_cs_disconnecting"]
        or lifecycle["saw_modem_disconnected"]
        or modem_evidence["disconnect_requested"]
        or modem_evidence["disconnecting"]
        or modem_evidence["idle_after_disconnect"]
    )
    session_proved = (
        platform_evidence["session_manager_completed"] or platform_evidence["session_complete"]
    )

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

    if not (disconnect_proved or platform_evidence["update_activity"]):
        failures.append("missing modem disconnect / connection-release evidence")

    if failures:
        summary = "; ".join(failures)
        shared.log(f"{meter.host} call-in cycle {cycle_num}: validation failed -> {summary}")
        raise RuntimeError(summary)

    return {
        "connect_delta": connect_delta,
        "disconnect_delta": disconnect_delta,
        "failed_connect_delta": failed_connect_delta,
    }


def _get_call_in_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("call_in", {})


def test_cycle_call_in(meter: SSHMeter, shared: SharedState, **kwargs):
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    ready_timeout_s = float(kwargs.get("ready_timeout_s", DEFAULT_CALL_IN_READY_TIMEOUT_S))
    ready_stable_s = float(kwargs.get("ready_stable_s", DEFAULT_CALL_IN_READY_STABLE_S))
    start_timeout_s = float(kwargs.get("start_timeout_s", DEFAULT_CALL_IN_START_TIMEOUT_S))
    completion_timeout_s = float(kwargs.get("completion_timeout_s", DEFAULT_CALL_IN_COMPLETION_TIMEOUT_S))
    disconnect_timeout_s = float(kwargs.get("disconnect_timeout_s", DEFAULT_CALL_IN_DISCONNECT_TIMEOUT_S))
    recovery_timeout_s = float(kwargs.get("recovery_timeout_s", DEFAULT_CALL_IN_RECOVERY_TIMEOUT_S))
    post_recovery_guard_s = float(
        kwargs.get("post_recovery_guard_s", DEFAULT_CALL_IN_POST_RECOVERY_GUARD_S)
    )
    post_recovery_timeout_s = float(
        kwargs.get("post_recovery_timeout_s", DEFAULT_CALL_IN_POST_RECOVERY_TIMEOUT_S)
    )
    status_loss_grace_s = float(
        kwargs.get("status_loss_grace_s", DEFAULT_CALL_IN_STATUS_LOSS_GRACE_S)
    )
    startup_guard_s = float(kwargs.get("startup_guard_s", DEFAULT_CALL_IN_STARTUP_GUARD_S))
    poll_s = float(kwargs.get("state_poll_s", DEFAULT_CALL_IN_POLL_S))
    platform_journal_max_lines = int(
        kwargs.get("platform_journal_max_lines", DEFAULT_CALL_IN_PLATFORM_JOURNAL_LINES)
    )
    modem_journal_max_lines = int(
        kwargs.get("modem_journal_max_lines", DEFAULT_CALL_IN_MODEM_JOURNAL_LINES)
    )
    startup_platform_journal_max_lines = int(
        kwargs.get(
            "startup_platform_journal_max_lines",
            DEFAULT_CALL_IN_STARTUP_PLATFORM_JOURNAL_LINES,
        )
    )
    post_completion_grace_s = float(
        kwargs.get("post_completion_grace_s", DEFAULT_CALL_IN_POST_GRACE_S)
    )
    subtest = bool(kwargs.get("subtest", False))

    for i in range(count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{count}")
        if not subtest:
            shared.broadcast_progress(meter.host, "call in", cycle_num, count)

        meter.goto_callin()
        shared.set_allowed(set(), reason="Call-in pre-check in progress")
        startup_guard = _wait_for_startup_call_in_guard(
            meter,
            shared,
            cycle_num=cycle_num,
            guard_s=startup_guard_s,
            platform_journal_max_lines=startup_platform_journal_max_lines,
            poll_s=poll_s,
        )
        baseline_snapshot, ready_elapsed_s = _wait_for_call_in_idle(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=ready_timeout_s,
            poll_s=poll_s,
            phase="pre-check",
            stable_s=ready_stable_s,
            require_ui_ready=True,
        )
        shared.log(
            f"{meter.host} call-in pre-check {cycle_num}: ready after {ready_elapsed_s:.1f}s | "
            f"{_status_summary(baseline_snapshot)}"
        )

        journal_since = _journal_since_now(meter)
        shared.log(f"{meter.host} call-in cycle {cycle_num}: press '+' on Service:Call In")
        meter.press("plus")

        lifecycle = _new_lifecycle()
        lifecycle_snapshot: Optional[dict] = None
        lifecycle_elapsed_s = 0.0
        cleanup_snapshot: Optional[dict] = None
        cleanup_elapsed_s: Optional[float] = None
        recovery_snapshot: Optional[dict] = None
        recovery_elapsed_s: Optional[float] = None
        post_recovery_elapsed_s: Optional[float] = None
        lifecycle_error = ""
        cleanup_error = ""
        recovery = {
            "attempted": False,
            "recovered": False,
            "saw_splash": False,
            "saw_status_unavailable": False,
        }

        try:
            lifecycle_snapshot, lifecycle, lifecycle_elapsed_s = _wait_for_call_in_lifecycle(
                meter,
                shared,
                cycle_num=cycle_num,
                start_timeout_s=start_timeout_s,
                completion_timeout_s=completion_timeout_s,
                poll_s=poll_s,
                status_loss_grace_s=status_loss_grace_s,
            )
        except Exception as exc:
            lifecycle_error = str(exc)
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: lifecycle observation ended with "
                f"{type(exc).__name__}: {exc}",
            )

        if not lifecycle_error and not lifecycle["runtime_loss_after_start"]:
            if post_completion_grace_s > 0:
                _sleep_with_stop(shared, post_completion_grace_s)

            try:
                cleanup_snapshot, cleanup_elapsed_s = _wait_for_call_in_idle(
                    meter,
                    shared,
                    cycle_num=cycle_num,
                    timeout_s=disconnect_timeout_s,
                    poll_s=poll_s,
                    phase="cleanup",
                )
            except Exception as exc:
                cleanup_error = str(exc)
                shared.log(
                    f"{meter.host} call-in cycle {cycle_num}: cleanup observation ended with "
                    f"{type(exc).__name__}: {exc}",
                )

        need_recovery = lifecycle["runtime_loss_after_start"] or bool(lifecycle_error) or bool(cleanup_error)
        if need_recovery:
            recovery_snapshot, recovery, recovery_elapsed_s = _wait_for_meter_status_recovery(
                meter,
                shared,
                cycle_num=cycle_num,
                timeout_s=recovery_timeout_s,
                poll_s=poll_s,
            )
            if recovery_snapshot is not None:
                try:
                    recovery_snapshot, post_recovery_elapsed_s = _observe_post_recovery_guard(
                        meter,
                        shared,
                        cycle_num=cycle_num,
                        observe_s=post_recovery_guard_s,
                        timeout_s=post_recovery_timeout_s,
                        poll_s=poll_s,
                    )
                except Exception as exc:
                    shared.log(
                        f"{meter.host} call-in cycle {cycle_num}: post-recovery guard ended with "
                        f"{type(exc).__name__}: {exc}",
                    )

        include_previous_boot = bool(need_recovery)
        platform_journal = _get_service_journal(
            meter,
            service="MS3_Platform.service",
            since=journal_since,
            max_lines=platform_journal_max_lines,
            include_previous_boot=include_previous_boot,
        )
        modem_journal = _get_service_journal(
            meter,
            service="MS3_Modem.service",
            since=journal_since,
            max_lines=modem_journal_max_lines,
            include_previous_boot=include_previous_boot,
        )

        platform_evidence = _collect_platform_call_in_evidence(platform_journal)
        modem_evidence = _collect_modem_call_in_evidence(modem_journal)

        effective_cleanup_snapshot = cleanup_snapshot
        if effective_cleanup_snapshot is None and recovery_snapshot is not None and not recovery.get("saw_splash"):
            effective_cleanup_snapshot = recovery_snapshot
        if effective_cleanup_snapshot is None and lifecycle_snapshot is not None and lifecycle["saw_ready_return"]:
            effective_cleanup_snapshot = lifecycle_snapshot

        deltas = _validate_call_in_result(
            meter,
            shared,
            cycle_num=cycle_num,
            baseline_snapshot=baseline_snapshot,
            cleanup_snapshot=effective_cleanup_snapshot,
            lifecycle=lifecycle,
            platform_evidence=platform_evidence,
            modem_evidence=modem_evidence,
        )

        call_in_meta = _get_call_in_meta(shared)
        call_in_meta[cycle_num] = {
            "ready_elapsed_s": round(ready_elapsed_s, 1),
            "lifecycle_elapsed_s": round(lifecycle_elapsed_s, 1),
            "cleanup_elapsed_s": round(cleanup_elapsed_s, 1) if cleanup_elapsed_s is not None else None,
            "recovery_elapsed_s": round(recovery_elapsed_s, 1) if recovery_elapsed_s is not None else None,
            "post_recovery_elapsed_s": (
                round(post_recovery_elapsed_s, 1) if post_recovery_elapsed_s is not None else None
            ),
            "connect_delta": deltas["connect_delta"],
            "disconnect_delta": deltas["disconnect_delta"],
            "failed_connect_delta": deltas["failed_connect_delta"],
            "rssi": modem_evidence["rssi"],
            "ber": modem_evidence["ber"],
            "session_manager_started": platform_evidence["session_manager_started"],
            "session_manager_completed": platform_evidence["session_manager_completed"],
            "session_complete": platform_evidence["session_complete"],
            "rsync_started": platform_evidence["rsync_started"],
            "rsync_completed": platform_evidence["rsync_completed"],
            "runscript_started": platform_evidence["runscript_started"],
            "runscript_completed": platform_evidence["runscript_completed"],
            "update_activity": platform_evidence["update_activity"],
            "update_restart": platform_evidence["update_restart"],
            "runtime_loss_after_start": lifecycle["runtime_loss_after_start"],
            "saw_runtime_splash": lifecycle["saw_splash_after_start"] or recovery.get("saw_splash"),
            "used_previous_boot_journal": include_previous_boot,
            "startup_guard_checked": startup_guard["checked"],
            "startup_guard_runtime_age_s": (
                round(startup_guard["runtime_age_s"], 1)
                if startup_guard["runtime_age_s"] is not None
                else None
            ),
            "startup_guard_boot_age_s": (
                round(startup_guard["boot_age_s"], 1)
                if startup_guard["boot_age_s"] is not None
                else None
            ),
            "startup_call_in_seen_before_test": startup_guard["startup_seen"],
            "startup_call_in_age_s": (
                round(startup_guard["startup_age_s"], 1)
                if startup_guard["startup_age_s"] is not None
                else None
            ),
        }

        signal_summary = ""
        if modem_evidence["rssi"] is not None and modem_evidence["ber"] is not None:
            signal_summary = f" | rssi={modem_evidence['rssi']} ber={modem_evidence['ber']}"
        elif effective_cleanup_snapshot and effective_cleanup_snapshot.get("csq_text"):
            signal_summary = f" | csq={effective_cleanup_snapshot['csq_text']}"

        pass_elapsed_s = max(
            ready_elapsed_s,
            lifecycle_elapsed_s,
            cleanup_elapsed_s or 0.0,
            recovery_elapsed_s or 0.0,
            post_recovery_elapsed_s or 0.0,
        )
        shared.log(
            f"{meter.host} call-in cycle {cycle_num}: pass in {pass_elapsed_s:.1f}s "
            f"({_format_delta('ppp_connect', deltas['connect_delta'])}, "
            f"{_format_delta('ppp_disconnect', deltas['disconnect_delta'])})"
            f"{signal_summary}"
        )

        if lifecycle_error:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: validated despite lifecycle observer error -> "
                f"{lifecycle_error}",
            )
        if cleanup_error:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: validated despite cleanup observer error -> "
                f"{cleanup_error}",
            )
        if recovery.get("recovered"):
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: recovery path succeeded "
                f"(splash={recovery.get('saw_splash')})",
            )

        if modem_evidence["signal_line"]:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: modem marker -> {modem_evidence['signal_line']}"
            )
        if platform_evidence["session_complete_line"]:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: session marker -> "
                f"{platform_evidence['session_complete_line']}"
            )
        elif platform_evidence["call_in_response_line"]:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: response marker -> "
                f"{platform_evidence['call_in_response_line']}"
            )

        if platform_evidence["update_activity"]:
            shared.log(
                f"{meter.host} call-in cycle {cycle_num}: update activity observed -> "
                f"{platform_evidence['update_line'] or 'see platform journal'}",
            )

        check_stop_event(shared)
