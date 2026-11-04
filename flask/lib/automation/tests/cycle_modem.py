"""Cycle modem connection with local journal watches and state verification.

The startup guard, busy precheck, modem state polling, and required CSQ signal
line remain the test's own pass/fail checks. Once a cycle is ready, a cursor
based journal observer also applies ModemMonitor's CONNECT/DISCONNECT watches:
the command line arms a watch and a matching S4_CONNECTED/S1_IDLE line cancels
it. The observer is inactive during navigation and precheck, like the old
monitor allow-list. See flask/lib/docs/meter/cycle_modem.md for the full flow.
"""

from __future__ import annotations

import inspect
import json
import re
import shlex
import time
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from lib.automation.helpers import check_stop_event

if TYPE_CHECKING:
    from lib.meter.ssh_meter import SSHMeter
    from lib.automation.shared_state import SharedState

DEFAULT_MODEM_CONNECT_TIMEOUT_S = 35.0
DEFAULT_MODEM_DISCONNECT_TIMEOUT_S = 30.0
MODEM_PRECHECK_TIMEOUT_S = 100.0
MODEM_PRECHECK_POLL_S = 3.0
MODEM_STATE_POLL_S = 2.0
DEFAULT_JOURNAL_POLL_S = 0.5
MODEM_INFO_LOOKBACK_LEAD_S = 2.0
DEFAULT_MODEM_STARTUP_GUARD_S = 180.0
DEFAULT_MODEM_STARTUP_PLATFORM_JOURNAL_LINES = 1500
MODEM_CONNECTED_STATE = "S4_CONNECTED"
MODEM_IDLE_STATE = "S1_IDLE"
MODEM_ERROR_STATE = "S7_ERROR"
MODEM_DISCONNECTED_STATES = (MODEM_IDLE_STATE, MODEM_ERROR_STATE)
MODEM_CSQ_RE = re.compile(r"\bcsq\s*:\s*(?P<rssi>\d+)\s*,\s*(?P<ber>\d+)\b", re.IGNORECASE)
RE_JOURNAL_BOUNDS = re.compile(
    r"-- Logs begin at (?P<start>.+?), end at (?P<end>.+?)\. --",
    re.IGNORECASE,
)
RE_PLATFORM_RUNTIME_START = re.compile(r"\bMS3:main:\s*starting,\s*version:", re.IGNORECASE)
RE_PLATFORM_SERVICE_START = re.compile(r"systemd\[\d+\]: Starting MS3 Platform", re.IGNORECASE)
RE_STARTUP_CALL_IN = re.compile(r"\bMS3:sRestartCallIn:\s*startup call-in\b", re.IGNORECASE)
RE_MODEM_REQUEST = re.compile(r"\bMODEM:\s*SendRemote:\s*CMD\.(CONNECT|DISCONNECT)\b", re.IGNORECASE)
RE_MONITOR_CONNECTED = re.compile(r"\bstate=S4_CONNECTED\b", re.IGNORECASE)
RE_MONITOR_IDLE = re.compile(r"\bstate=S1_IDLE\b", re.IGNORECASE)
MODEM_BUSY_STATES = {
    "S0_START",
    "S2_POWERING_UP",
    "S3_CONNECTING",
    "S4_CONNECTED",
    "S5_WAITING_TO_SHUT_DOWN",
    "S6_SHUTTING_DOWN",
    "S8_BOUNCING",
    "(unknown:-1)", # observed during meter boot/initialization
}


def _sleep_with_stop(
    shared: SharedState,
    seconds: float,
    poll_interval: float = 0.25,
    journal_watch: Optional[_ModemJournalWatch] = None,
) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        check_stop_event(shared)
        if journal_watch is not None:
            journal_watch.poll()
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        if journal_watch is not None:
            remaining = min(remaining, journal_watch.seconds_to_deadline())
        time.sleep(min(poll_interval, remaining))


def _modem_journal_entries(output: str) -> list[tuple[str, str]]:
    """Parse a whole journal batch before advancing the cursor."""
    entries = []
    for line_number, line in enumerate((output or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid modem journal JSON at line {line_number}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("__CURSOR"), str) or not payload["__CURSOR"]:
            raise RuntimeError(f"modem journal entry at line {line_number} has no cursor")
        message = payload.get("MESSAGE", "")
        if isinstance(message, list):
            message = bytes(message).decode(errors="replace")
        entries.append((payload["__CURSOR"], str(message)))
    return entries


def _read_modem_journal(meter: SSHMeter, command: str) -> list[tuple[str, str]]:
    code, output, error = meter.exec_parse(command)
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"modem journal read failed: {detail}")
    return _modem_journal_entries(output)


class _ModemJournalWatch:
    """The active portion of ModemMonitor, driven by cursor polls."""

    def __init__(self, meter: SSHMeter, shared: SharedState, *, cycle_num: int, debug: bool):
        self.meter = meter
        self.shared = shared
        self.cycle_num = cycle_num
        self.debug = debug
        entries = _read_modem_journal(
            meter, f"journalctl -u MS3_Platform.service -n 1 --no-pager -o json"
        )
        if not entries:
            raise RuntimeError("cannot establish modem journal cursor for MS3_Platform.service")
        self.cursor = entries[-1][0]
        self.deadline: float | None = None
        self.pending: str | None = None
        if debug:
            shared.log(f"modem cycle {cycle_num}: initial journal cursor={self.cursor}")

    def seconds_to_deadline(self) -> float:
        if self.deadline is None:
            return float("inf")
        return max(0.0, self.deadline - time.monotonic())

    def poll(self) -> None:
        command = (
            "journalctl -u MS3_Platform.service "
            f"--after-cursor={shlex.quote(self.cursor)} --no-pager -o json"
        )
        entries = _read_modem_journal(self.meter, command)
        if self.debug:
            self.shared.log(
                f"modem cycle {self.cycle_num}: polled {len(entries)} journal entries after {self.cursor}"
            )
        for cursor, message in entries:
            self.cursor = cursor
            # Listener.interested() only passed lines containing 'modem'.
            if "modem" not in message.lower():
                continue
            request = RE_MODEM_REQUEST.search(message)
            if request:
                if self.pending:
                    self.shared.log(
                        f"modem cycle {self.cycle_num}: replace pending "
                        f"{self.pending.upper()} watch ({cursor})"
                    )
                self.pending = request.group(1).lower()
                timeout_s = (
                    DEFAULT_MODEM_CONNECT_TIMEOUT_S if self.pending == "connect"
                    else DEFAULT_MODEM_DISCONNECT_TIMEOUT_S
                )
                # Every new request replaces the prior watch, including one
                # for the opposite direction, exactly as ModemMonitor did.
                self.deadline = time.monotonic() + timeout_s
                self.shared.log(
                    f"modem cycle {self.cycle_num}: arm {self.pending.upper()} "
                    f"watch for {timeout_s:.1f}s ({cursor})"
                )
            elif self.pending == "connect" and RE_MONITOR_CONNECTED.search(message):
                self.pending = None
                self.deadline = None
                self.shared.log(f"modem cycle {self.cycle_num}: CONNECTED; watch cancelled ({cursor})")
            elif self.pending == "disconnect" and RE_MONITOR_IDLE.search(message):
                self.pending = None
                self.deadline = None
                self.shared.log(f"modem cycle {self.cycle_num}: DISCONNECTED/IDLE; watch cancelled ({cursor})")
            if self.debug and (request or "state=" in message.lower()):
                self.shared.log(f"modem cycle {self.cycle_num}: journal: {message}")

        if self.deadline is not None and time.monotonic() >= self.deadline:
            state = "CONNECTED" if self.pending == "connect" else "DISCONNECTED/IDLE"
            timeout_s = (
                DEFAULT_MODEM_CONNECT_TIMEOUT_S if self.pending == "connect"
                else DEFAULT_MODEM_DISCONNECT_TIMEOUT_S
            )
            raise RuntimeError(f"Modem failed to reach {state} within {timeout_s:.1f}s")


def _get_modem_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("modem", {})


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


def _parse_modem_signal_line(line: str) -> Optional[dict]:
    match = MODEM_CSQ_RE.search(line or "")
    if not match:
        return None
    return {
        "rssi": int(match.group("rssi")),
        "ber": int(match.group("ber")),
    }


def _get_latest_modem_signal_info(meter: SSHMeter, since: str) -> tuple[Optional[dict], str]:
    # journalctl -u MS3_Platform.service --since "<since>" --no-pager -r | grep -m 1 -F 'csq:'
    #   -r = newest first
    #   grep -m 1 = stop after first match
    cmd = (
        f"journalctl -u MS3_Platform.service --since \"{since}\" -n 800 --no-pager | "
        "grep -F 'csq:' | tail -n 1"
    )
    result = meter.cli(cmd)
    if not result:
        return None, ""

    for line in reversed(result.splitlines()):
        modem_info = _parse_modem_signal_line(line)
        if modem_info:
            return modem_info, line

    return None, result.strip()


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
                f"{meter.host} modem startup guard {cycle_num}: unable to read meter time ({exc}); retrying",
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
            shared.log(f"{meter.host} modem startup guard {cycle_num}: {summary}")
            last_summary = summary

        if startup_call_in_dt is not None:
            shared.log(
                f"{meter.host} modem startup guard {cycle_num}: startup call-in already started; "
                f"continuing to modem pre-check",
            )
            return result

        guard_age_s = runtime_age_s if runtime_age_s is not None else boot_age_s
        if guard_age_s is not None and guard_age_s >= guard_s:
            shared.log(
                f"{meter.host} modem startup guard {cycle_num}: no startup marker seen by "
                f"{_format_age(guard_age_s)}; continuing to modem pre-check",
            )
            return result

        if guard_age_s is None and (time.time() - started) >= guard_s:
            shared.log(
                f"{meter.host} modem startup guard {cycle_num}: unable to derive startup age "
                f"within {guard_s:.1f}s; continuing to modem pre-check",
            )
            return result

        _sleep_with_stop(shared, poll_s)


def _stop_modem_after_error(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    reason: str,
    timeout_s: float,
    poll_s: float,
) -> None:
    shared.log(f"{meter.host} modem cycle {cycle_num}: attempting modem OFF after {reason}")
    try:
        meter.toggle_modem(False)
    except Exception as exc:
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: failed to send modem OFF after {reason} ({exc})",
        )
        return

    try:
        _, disconnect_elapsed_s = _wait_for_modem_state(
            meter,
            shared,
            cycle_num=cycle_num,
            phase="disconnect cleanup",
            expected_states=MODEM_DISCONNECTED_STATES,
            timeout_s=timeout_s,
            poll_s=poll_s,
        )
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: cleanup reached "
            f"{MODEM_IDLE_STATE} or {MODEM_ERROR_STATE} in {disconnect_elapsed_s:.1f}s",
        )
    except Exception as exc:
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: cleanup failed after {reason} ({exc})",
        )


def _wait_for_modem_ready(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
) -> tuple[bool, Optional[str], float]:
    started = time.time()
    deadline = time.time() + max(0.0, timeout_s)
    last_state: Optional[str] = None

    while True:
        check_stop_event(shared)

        try:
            modem_state = meter.get_modem_state()
        except Exception as exc:
            shared.log(
                f"{meter.host} modem pre-check {cycle_num}: unable to read modem state ({exc}); proceeding",
            )
            return True, None, time.time() - started

        if modem_state != last_state:
            shared.log(
                f"{meter.host} modem pre-check {cycle_num}: state={modem_state or 'unknown'}",
            )
            last_state = modem_state

        if not modem_state or modem_state not in MODEM_BUSY_STATES:
            return True, modem_state, time.time() - started

        remaining = deadline - time.time()
        if remaining <= 0:
            return False, modem_state, time.time() - started

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_modem_state(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    phase: str,
    expected_states: tuple[str, ...],
    timeout_s: float,
    poll_s: float,
    journal_watch: Optional[_ModemJournalWatch] = None,
    journal_poll_s: float = DEFAULT_JOURNAL_POLL_S,
) -> tuple[str, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_state: Optional[str] = None

    while True:
        check_stop_event(shared)
        if journal_watch is not None:
            journal_watch.poll()

        try:
            modem_state = meter.get_modem_state()
        except Exception as exc:
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: unable to read modem state ({exc}); retrying",
            )
            modem_state = None

        if modem_state != last_state:
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: state={modem_state or 'unknown'}",
            )
            last_state = modem_state

        if modem_state in expected_states:
            if journal_watch is not None:
                journal_watch.poll()
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: reached {modem_state} in {elapsed_s:.1f}s",
            )
            return modem_state, elapsed_s

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Modem {phase} cycle {cycle_num} timed out waiting for "
                f"{' or '.join(expected_states)}; "
                f"last_state={modem_state or 'unknown'} after {timeout_s:.1f}s"
            )

        _sleep_with_stop(
            shared,
            min(poll_s, remaining),
            poll_interval=journal_poll_s if journal_watch is not None else 0.25,
            journal_watch=journal_watch,
        )


def test_cycle_modem(meter: SSHMeter, shared: SharedState, **kwargs):
    """Toggle the modem with existing state/signal checks and local log watches.

    ``poll_s`` (default 0.5s) controls journal polling while a cycle is active.
    ``state_poll_s`` and ``precheck_poll_s`` retain their separate defaults.
    ``debug=True`` logs journal cursors, poll counts, and matching raw lines.
    The monitor's default 35s/30s watches remain separate from configurable
    state wait timeouts, matching the previous monitor registration.
    """
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    connect_timeout_s = float(kwargs.get("connect_timeout_s", kwargs.get("delay_on", DEFAULT_MODEM_CONNECT_TIMEOUT_S)))
    disconnect_timeout_s = float(kwargs.get("disconnect_timeout_s", kwargs.get("delay_off", DEFAULT_MODEM_DISCONNECT_TIMEOUT_S)))
    precheck_timeout_s = float(kwargs.get("precheck_timeout_s", MODEM_PRECHECK_TIMEOUT_S))
    precheck_poll_s = float(kwargs.get("precheck_poll_s", MODEM_PRECHECK_POLL_S))
    state_poll_s = float(kwargs.get("state_poll_s", MODEM_STATE_POLL_S))
    poll_s = float(kwargs.get("poll_s", DEFAULT_JOURNAL_POLL_S))
    debug = bool(kwargs.get("debug", False))
    if poll_s <= 0:
        raise ValueError("modem poll_s must be positive")
    modem_info_lookback_lead_s = float(
        kwargs.get("modem_info_lookback_lead_s", MODEM_INFO_LOOKBACK_LEAD_S)
    )
    startup_guard_s = float(kwargs.get("startup_guard_s", DEFAULT_MODEM_STARTUP_GUARD_S))
    startup_platform_journal_max_lines = int(
        kwargs.get(
            "startup_platform_journal_max_lines",
            DEFAULT_MODEM_STARTUP_PLATFORM_JOURNAL_LINES,
        )
    )
    subtest = bool(kwargs.get("subtest", False))

    for i in range(job_count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {i+1}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'modem', cycle_num, job_count)

        meter.goto_callin()

        _wait_for_startup_call_in_guard(
            meter,
            shared,
            cycle_num=cycle_num,
            guard_s=startup_guard_s,
            platform_journal_max_lines=startup_platform_journal_max_lines,
            poll_s=precheck_poll_s,
        )

        ready, modem_state, precheck_elapsed_s = _wait_for_modem_ready(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=precheck_timeout_s,
            poll_s=precheck_poll_s,
        )
        shared.log(
            f"{meter.host} modem pre-check {cycle_num}: "
            f"{'ready' if ready else 'busy'} after {precheck_elapsed_s:.1f}s "
            f"(state={modem_state or 'unknown'})",
        )
        if not ready:
            shared.log(
                f"{meter.host} {func_name} {cycle_num}/{job_count} skipped; modem stayed busy in {modem_state}",
            )
            continue

        journal_watch = _ModemJournalWatch(meter, shared, cycle_num=cycle_num, debug=debug)
        modem_on = False

        try:
            connect_journal_since = _journal_since_now(meter)
            if modem_info_lookback_lead_s > 0:
                _sleep_with_stop(
                    shared, modem_info_lookback_lead_s,
                    poll_interval=poll_s, journal_watch=journal_watch,
                )

            meter.toggle_modem(True)
            modem_on = True
            connected_state, connect_elapsed_s = _wait_for_modem_state(
                meter,
                shared,
                cycle_num=cycle_num,
                phase="connect",
                expected_states=(MODEM_CONNECTED_STATE,),
                timeout_s=connect_timeout_s,
                poll_s=state_poll_s,
                journal_watch=journal_watch,
                journal_poll_s=poll_s,
            )

            modem_info, modem_info_line = _get_latest_modem_signal_info(meter, connect_journal_since)
            if modem_info is not None:
                modem_meta = _get_modem_meta(shared)
                modem_meta[cycle_num] = {"rssi": modem_info["rssi"], "ber": modem_info["ber"]}
                shared.log(
                    f"{meter.host} modem cycle {cycle_num}: "
                    f"connected={connected_state} in {connect_elapsed_s:.1f}s | "
                    f"rssi={modem_info['rssi']} ber={modem_info['ber']}",
                )
            else:
                if modem_info_line:
                    shared.log(
                        f"{meter.host} modem cycle {cycle_num}: unable to parse modem info line -> {modem_info_line}",
                    )
                else:
                    shared.log(
                        f"{meter.host} modem cycle {cycle_num}: no modem signal info found since {connect_journal_since}",
                    )
                _stop_modem_after_error(
                    meter,
                    shared,
                    cycle_num=cycle_num,
                    reason="missing modem signal info",
                    timeout_s=disconnect_timeout_s,
                    poll_s=state_poll_s,
                )
                modem_on = False
                raise RuntimeError("Modem Connection Error")

            _sleep_with_stop(shared, 5.0, poll_interval=poll_s, journal_watch=journal_watch)
            meter.toggle_modem(False)
            modem_on = False
            disconnected_state, disconnect_elapsed_s = _wait_for_modem_state(
                meter,
                shared,
                cycle_num=cycle_num,
                phase="disconnect",
                expected_states=MODEM_DISCONNECTED_STATES,
                timeout_s=disconnect_timeout_s,
                poll_s=state_poll_s,
                journal_watch=journal_watch,
                journal_poll_s=poll_s,
            )
            shared.log(
                f"{meter.host} modem cycle {cycle_num}: "
                f"disconnected={disconnected_state} in {disconnect_elapsed_s:.1f}s",
            )
            _sleep_with_stop(shared, 5.0, poll_interval=poll_s, journal_watch=journal_watch)

        except Exception as exc:
            if modem_on:
                _stop_modem_after_error(
                    meter,
                    shared,
                    cycle_num=cycle_num,
                    reason=f"{type(exc).__name__}: {exc}",
                    timeout_s=disconnect_timeout_s,
                    poll_s=state_poll_s,
                )
            raise

        check_stop_event(shared)
