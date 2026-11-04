"""Cycle NFC power while applying the former NFCMonitor watch rules.

The test captures an MS3 platform journal cursor after diagnostics navigation,
then observes every new entry while the reader is ON and OFF. The same request
payloads arm ON (6s) and OFF (3s) watches, and the same EMV_POWER_REPLY payloads
cancel them. Unknown requests/replies and EMV_UI_OUTPUT do not change results;
no matching request means no watch and no monitor fault. Each state still lasts
at least seven seconds, as in the original cycle test. Journal acquisition
errors raise because this test now owns the verification.

Keep flask/lib/docs/meter/cycle_nfc.md in sync with this behavior.
"""

from __future__ import annotations

import inspect
import json
import re
import shlex
import time
from typing import TYPE_CHECKING

from lib.automation.helpers import check_stop_event

if TYPE_CHECKING:
    from lib.automation.shared_state import SharedState
    from lib.meter.ssh_meter import SSHMeter


JOURNAL_UNIT = "MS3_Platform.service"
MIN_NFC_DELAY = 7.0
DEFAULT_ON_TIMEOUT_S = 6.0
DEFAULT_OFF_TIMEOUT_S = 3.0
DEFAULT_POLL_S = 0.5

# These payload rules preserve the NFCMonitor behavior for this cycle test.
REQUEST_RE = re.compile(
    r"GENERIC_TERMINAL\.\S*->KIOSK_(?:NFC|NEO)\.\S*\s+(?:APPLICATION_MSG\s+)?"
    r"(?P<verb>EMV_POWER|CARD_READ_INST)\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)",
    re.IGNORECASE,
)
REPLY_RE = re.compile(r"\bEMV_POWER_REPLY\b.*?\bD=(?P<payload>[0-9A-Fa-f ]+)", re.IGNORECASE)


def _journal_entries(output: str) -> list[tuple[str, str]]:
    """Parse a complete JSON batch before advancing the opaque cursor."""
    entries = []
    for line_number, line in enumerate((output or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid NFC journal JSON at line {line_number}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("__CURSOR"), str) or not payload["__CURSOR"]:
            raise RuntimeError(f"NFC journal entry at line {line_number} has no cursor")
        message = payload.get("MESSAGE", "")
        if isinstance(message, list):
            message = bytes(message).decode(errors="replace")
        entries.append((payload["__CURSOR"], str(message)))
    return entries


def _read_journal(meter: SSHMeter, command: str) -> list[tuple[str, str]]:
    code, output, error = meter.exec_parse(command)
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"NFC journal read failed: {detail}")
    return _journal_entries(output)


def _current_cursor(meter: SSHMeter) -> str:
    entries = _read_journal(meter, f"journalctl -u {JOURNAL_UNIT} -n 1 --no-pager -o json")
    if not entries:
        raise RuntimeError(f"cannot establish NFC journal cursor for {JOURNAL_UNIT}")
    return entries[-1][0]


def _request_state(verb: str, payload: str) -> str | None:
    """Decode exactly the ON/OFF request forms watched by NFCMonitor."""
    tokens = payload.upper().split()
    if len(tokens) < 2:
        return None
    if verb.upper() == "EMV_POWER" and tokens[0] == "01":
        return {"01": "on", "00": "off"}.get(tokens[1])
    if verb.upper() == "CARD_READ_INST" and tokens[0] == "00":
        return {"02": "on", "05": "off"}.get(tokens[1])
    return None


def _reply_state(payload: str) -> str | None:
    """Decode MS2.5 two-byte and MSX four-byte EMV_POWER_REPLY forms."""
    tokens = payload.upper().split()
    if len(tokens) < 2:
        return None
    if len(tokens) == 2:
        return {("01", "00"): "on", ("00", "00"): "off"}.get(tuple(tokens))
    if tokens[0] == "01":
        return {"01": "on", "00": "off"}.get(tokens[1])
    return None


def _sleep_with_stop(shared: SharedState, seconds: float, poll_s: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        check_stop_event(shared)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(poll_s, remaining))


def _observe_nfc(
    meter: SSHMeter,
    shared: SharedState,
    cursor: str,
    watches: dict[str, float],
    *,
    cycle_num: int,
    phase: str,
    duration_s: float,
    on_timeout_s: float,
    off_timeout_s: float,
    poll_s: float,
    debug: bool,
) -> str:
    """Poll through a dwell, processing replies before checking watch deadlines.

    Watches carry between ON/OFF dwells, just as the listener's watches did.
    A repeated request replaces the watch for that direction. A reply only
    cancels its own direction; an opposite or unrecognized reply does not.
    """
    dwell_end = time.monotonic() + duration_s
    while True:
        check_stop_event(shared)
        command = (
            f"journalctl -u {JOURNAL_UNIT} --after-cursor={shlex.quote(cursor)} "
            "--no-pager -o json"
        )
        entries = _read_journal(meter, command)
        if debug:
            shared.log(f"NFC {cycle_num} {phase}: polled {len(entries)} entries after {cursor}")
        for entry_cursor, message in entries:
            cursor = entry_cursor
            request = REQUEST_RE.search(message)
            reply = REPLY_RE.search(message) if not request else None
            if request:
                state = _request_state(request.group("verb"), request.group("payload"))
                if debug:
                    shared.log(f"NFC {cycle_num} {phase}: request {request.group('verb')} D={request.group('payload').strip()} -> {state}")
                if state:
                    timeout_s = on_timeout_s if state == "on" else off_timeout_s
                    watches[state] = time.monotonic() + timeout_s
                    shared.log(f"NFC {cycle_num}: arm {state.upper()} watch for {timeout_s:.1f}s ({cursor})")
            elif reply:
                state = _reply_state(reply.group("payload"))
                if debug:
                    shared.log(f"NFC {cycle_num} {phase}: reply D={reply.group('payload').strip()} -> {state}")
                if state and state in watches:
                    watches.pop(state)
                    shared.log(f"NFC {cycle_num}: {state.upper()} confirmed; watch cancelled ({cursor})")
            if debug and (request or reply):
                shared.log(f"NFC {cycle_num} {phase}: journal: {message}")

        now = time.monotonic()
        for state, deadline in tuple(watches.items()):
            if now >= deadline:
                timeout_s = on_timeout_s if state == "on" else off_timeout_s
                raise RuntimeError(f"NFC failed to power {state.upper()} within {timeout_s:.1f}s (cycle {cycle_num})")
        if now >= dwell_end:
            return cursor
        next_deadline = min(dwell_end, *watches.values()) if watches else dwell_end
        time.sleep(min(poll_s, next_deadline - now))


def test_cycle_nfc(meter: SSHMeter, shared: SharedState, **kwargs):
    """Toggle NFC ON/OFF for ``job_count`` cycles without an NFCMonitor.

    ``delay`` is the minimum dwell for each ON and OFF phase (at least 7s).
    ``timeout_on_s`` and ``timeout_off_s`` default to the monitor's 6s and 3s
    watch durations. ``poll_s`` defaults to 0.5s. ``debug=True`` adds cursor,
    poll, request, reply, and matched raw journal message logs. A watched
    timeout or journal acquisition problem raises for the runner/cycle_all.
    """
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    delay = max(float(kwargs.get("delay", MIN_NFC_DELAY)), MIN_NFC_DELAY)
    on_timeout_s = float(kwargs.get("timeout_on_s", DEFAULT_ON_TIMEOUT_S))
    off_timeout_s = float(kwargs.get("timeout_off_s", DEFAULT_OFF_TIMEOUT_S))
    poll_s = float(kwargs.get("poll_s", DEFAULT_POLL_S))
    debug = bool(kwargs.get("debug", False))
    subtest = bool(kwargs.get("subtest", False))
    if on_timeout_s <= 0 or off_timeout_s <= 0 or poll_s <= 0:
        raise ValueError("NFC watch timeouts and poll_s must be positive")

    # Navigation may itself request NFC OFF. The old test suppressed the
    # monitor then, but armed it for the following one-second settling period.
    _sleep_with_stop(shared, 1.0, poll_s)
    meter.goto_nfc()
    try:
        cursor = _current_cursor(meter)
    except Exception:
        try:
            meter.force_diagnostics()
        except Exception as exc:
            shared.log(f"NFC cleanup: unable to return to diagnostics: {exc}")
        raise
    if debug:
        shared.log(f"NFC initial journal cursor={cursor}")

    watches: dict[str, float] = {}
    reader_may_be_on = False
    try:
        cursor = _observe_nfc(
            meter, shared, cursor, watches, cycle_num=0, phase="setup",
            duration_s=1.0, on_timeout_s=on_timeout_s,
            off_timeout_s=off_timeout_s, poll_s=poll_s, debug=debug,
        )
        for i in range(job_count):
            check_stop_event(shared)
            cycle_num = i + 1
            shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
            if not subtest:
                shared.broadcast_progress(meter.host, "nfc", cycle_num, job_count)

            reader_may_be_on = True
            meter.press("plus")
            cursor = _observe_nfc(
                meter, shared, cursor, watches, cycle_num=cycle_num, phase="on",
                duration_s=delay, on_timeout_s=on_timeout_s,
                off_timeout_s=off_timeout_s, poll_s=poll_s, debug=debug,
            )

            meter.press("minus")
            reader_may_be_on = False
            cursor = _observe_nfc(
                meter, shared, cursor, watches, cycle_num=cycle_num, phase="off",
                duration_s=delay, on_timeout_s=on_timeout_s,
                off_timeout_s=off_timeout_s, poll_s=poll_s, debug=debug,
            )

        # The original test kept its monitor armed for one more second before
        # clearing watches, then waited one second before leaving diagnostics.
        cursor = _observe_nfc(
            meter, shared, cursor, watches, cycle_num=job_count, phase="cleanup",
            duration_s=1.0, on_timeout_s=on_timeout_s,
            off_timeout_s=off_timeout_s, poll_s=poll_s, debug=debug,
        )
        watches.clear()
        _sleep_with_stop(shared, 1.0, poll_s)
        meter.force_diagnostics()
    except Exception:
        # Direct polling now raises during a dwell. Leave the reader powered
        # down if ON was sent, while preserving the original failure reason.
        if reader_may_be_on:
            try:
                meter.press("minus")
            except Exception as exc:
                shared.log(f"NFC cleanup: unable to press minus: {exc}")
        try:
            meter.force_diagnostics()
        except Exception as exc:
            shared.log(f"NFC cleanup: unable to return to diagnostics: {exc}")
        raise

