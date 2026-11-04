"""Cycle the printer using the former PrinterMonitor decision rules.

Each attempt captures a cursor just before ``meter.printer_test()`` and polls
only newer MS3 platform journal entries. A print request starts a watch that
defaults to eight seconds. ``SUCCEEDED`` cancels it, ``PENDING`` fails
immediately, and any other result cancels it without a fault. A request with
no result fails when its watch
expires. A missing request never starts a watch, matching PrinterMonitor.

``PRINTER_STATUS_REPLY`` never changes pass/fail. After success, a later
``TICKET_COMPLETE`` status with ``isCanPrint=true`` may end the fallback wait
early so the next print can start. Otherwise the attempt waits the same
configured duration used for the watch. Journal read errors fail because this
standalone test cannot verify results without the journal.

Keep flask/lib/docs/meter/cycle_print.md in sync with this behavior.
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
PRINT_WAIT_S = 8.0
DEFAULT_POLL_S = 0.5

PRINT_START_RE = re.compile(r"IPSBusDevSendPrintMessageVA", re.IGNORECASE)
PRINT_RESULT_RE = re.compile(
    r"PRINT_TICKET_REPLY:\s*.*?\bresult=([A-Z]+)\b", re.IGNORECASE
)
PRINTER_STATUS_RE = re.compile(
    r"PRINTER_STATUS_REPLY:\s*status=([^,]+),\s*isCanPrint=(true|false)",
    re.IGNORECASE,
)


def _journal_entries(output: str) -> list[tuple[str, str]]:
    entries = []
    for line_number, line in enumerate((output or "").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid printer journal JSON at line {line_number}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("__CURSOR"), str) or not payload["__CURSOR"]:
            raise RuntimeError(f"printer journal entry at line {line_number} has no cursor")
        message = payload.get("MESSAGE", "")
        if isinstance(message, list):
            message = bytes(message).decode(errors="replace")
        entries.append((payload["__CURSOR"], str(message)))
    return entries


def _read_journal(meter: SSHMeter, command: str) -> list[tuple[str, str]]:
    code, output, error = meter.exec_parse(command)
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"printer journal read failed: {detail}")
    return _journal_entries(output)


def _current_cursor(meter: SSHMeter) -> str:
    """Anchor one attempt after any MS3 printer reboot traffic."""
    entries = _read_journal(meter, f"journalctl -u {JOURNAL_UNIT} -n 1 --no-pager -o json")
    if not entries:
        raise RuntimeError(f"cannot establish printer journal cursor for {JOURNAL_UNIT}")
    return entries[-1][0]


def _wait_for_print(
    meter: SSHMeter,
    shared: SharedState,
    cursor: str,
    *,
    cycle_num: int,
    wait_s: float,
    poll_s: float,
    debug: bool,
    fallback_at: float,
) -> str:
    """Poll request/result lines; use status only to shorten the fallback wait.

    The print watch starts when its request is observed, not when the command
    is issued. Poll the journal before checking the deadline so a result at
    the boundary is processed before declaring a timeout.
    """
    deadline = None
    saw_request = False
    saw_success = False
    saw_unknown_result = False
    ready_after_success = False

    while True:
        check_stop_event(shared)
        command = (
            f"journalctl -u {JOURNAL_UNIT} --after-cursor={shlex.quote(cursor)} "
            "--no-pager -o json"
        )
        entries = _read_journal(meter, command)
        if debug:
            shared.log(f"printer {cycle_num}: polled {len(entries)} journal entries after {cursor}")
        for entry_cursor, message in entries:
            cursor = entry_cursor
            if PRINT_START_RE.search(message):
                # PrinterMonitor arms a fresh watch on every print request.
                deadline = time.monotonic() + wait_s
                saw_request = True
                saw_success = False
                saw_unknown_result = False
                ready_after_success = False
                shared.log(f"printer {cycle_num}: print request observed ({cursor})")
            elif saw_request:
                result = PRINT_RESULT_RE.search(message)
                status = PRINTER_STATUS_RE.search(message)
                if result:
                    value = result.group(1).upper()
                    shared.log(f"printer {cycle_num}: PRINT_TICKET_REPLY result={value} ({cursor})")
                    if value == "SUCCEEDED":
                        saw_success = True
                    elif value == "PENDING":
                        raise RuntimeError(f"printer cycle {cycle_num} returned PENDING")
                    else:
                        # PrinterMonitor cancels its watch without emitting a
                        # fault for any result other than these two values.
                        saw_unknown_result = True
                        shared.log(f"printer {cycle_num}: unknown result={value}; watch cancelled")
                elif status:
                    flags = {flag.strip().upper() for flag in status.group(1).split("+")}
                    can_print = status.group(2).lower() == "true"
                    if debug:
                        shared.log(
                            f"printer {cycle_num}: status={status.group(1)}, "
                            f"isCanPrint={str(can_print).lower()} ({cursor})"
                        )
                    # PrinterMonitor never changes a watch on status lines.
                    # This signal only permits the next print to start early.
                    if saw_success and "TICKET_COMPLETE" in flags and can_print:
                        ready_after_success = True
            if debug and (
                PRINT_START_RE.search(message)
                or PRINT_RESULT_RE.search(message)
                or PRINTER_STATUS_RE.search(message)
            ):
                shared.log(f"printer {cycle_num}: journal: {message}")

        now = time.monotonic()
        if saw_success and ready_after_success:
            shared.log(f"printer {cycle_num}: success confirmed; printer ready")
            return cursor
        if saw_request and not (saw_success or saw_unknown_result) and now >= deadline:
            raise RuntimeError(f"printer cycle {cycle_num} timed out after {wait_s:.1f}s")
        if (not saw_request or saw_success or saw_unknown_result) and now >= fallback_at:
            shared.log(f"printer {cycle_num}: completed legacy delay without ready status")
            return cursor
        remaining = fallback_at - now
        if saw_request and not (saw_success or saw_unknown_result):
            remaining = deadline - now
        time.sleep(min(poll_s, remaining))


def _configured_wait_s(kwargs: dict) -> float:
    """Use one duration for both roles, accepting the old option names."""
    provided = {
        name: float(kwargs[name])
        for name in ("wait_s", "timeout_s", "delay")
        if name in kwargs
    }
    if len(set(provided.values())) > 1:
        raise ValueError("printer wait_s, timeout_s, and delay must agree when combined")
    requested = next(iter(provided.values()), PRINT_WAIT_S)
    if requested <= 0:
        raise ValueError("printer wait_s must be positive")
    return max(requested, PRINT_WAIT_S)


def test_cycle_print(meter: SSHMeter, shared: SharedState, **kwargs):
    """Run ``job_count`` print attempts without a PrinterMonitor.

    ``wait_s`` defaults to 8 seconds and controls both the request-to-result
    timeout and the fallback wait after sending a command. Values below 8 are
    clamped to 8. The old ``timeout_s`` and ``delay`` names remain aliases for
    the same setting; conflicting values are rejected. ``poll_s`` defaults to
    0.5 seconds. ``debug=True`` adds cursor, poll, status, and matched journal
    message logs. ``subtest=True`` suppresses standalone progress broadcasts.

    On failure this function raises. The runner or cycle_all then records the
    printer result and applies the job's stop_on_fail policy.
    """
    func_name = inspect.currentframe().f_code.co_name
    job_count = int(kwargs.get("job_count", 3))
    wait_s = _configured_wait_s(kwargs)
    poll_s = float(kwargs.get("poll_s", DEFAULT_POLL_S))
    debug = bool(kwargs.get("debug", False))
    subtest = bool(kwargs.get("subtest", False))
    if poll_s <= 0:
        raise ValueError("printer poll_s must be positive")

    for i in range(job_count):
        check_stop_event(shared)
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count}")
        if not subtest:
            shared.broadcast_progress(meter.host, "printer", cycle_num, job_count)

        if meter.meter_type == "ms3":
            shared.log("Toggle printer OFF and back ON to avoid a jam")
            meter.reboot_printer()
        check_stop_event(shared)

        # Anchor immediately before the command, after any reboot status traffic.
        cursor = _current_cursor(meter)
        if debug:
            shared.log(f"printer {cycle_num}: initial journal cursor={cursor}")
        meter.printer_test()
        fallback_at = time.monotonic() + wait_s
        _wait_for_print(
            meter, shared, cursor, cycle_num=cycle_num, wait_s=wait_s,
            poll_s=poll_s, debug=debug, fallback_at=fallback_at,
        )
    check_stop_event(shared)
