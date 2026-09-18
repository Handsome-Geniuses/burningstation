import inspect
import json
import re
import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from lib.automation.helpers import StopAutomation, check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


# TODO: Add some sort of operator feedback on burningstation UI

# Keep flask/lib/docs/meter/test_operator_card_reader.md in sync when changing this test.
JOURNAL_UNIT = "MS3_Platform.service"
JOURNAL_MAX_LINES = 1000
EMPTY_TRACK2_CARD_HASH = 2147815457  # 0x80051021: HashCard() with zero Track 2 bytes.

PROCESSED_CARD_READ_RE = re.compile(
    r"Meter:sProcessIPSBusMessage(?::\d+)?:\s*"
    r"EMV_CONTACT:CARD_READ_DATA:\s*"
    r"fwVersion=(?P<fw_version>\d+)\s+"
    r"CardInfoType=(?P<card_info_type>\d+)\s*,\s*"
    r"ReadType=(?P<read_type>\d+)\s*:\s*(?P<read_type_name>[^,\s]+)\s*,\s*"
    r"EncryptionType=(?P<encryption_type>\d+)\s*,\s*"
    r"inferred\s+cardType=(?P<card_type>\d+)\s*:\s*(?P<card_type_name>[^\s,]+)\s+"
    r"cardHash=(?P<card_hash>\d+)\s+"
    r"isCardAccepted=(?P<is_card_accepted>true|false)",
    re.IGNORECASE,
)

CARD_READ_INST_RE = re.compile(
    r"EMV_CONTACT\.[^\s]*->GENERIC_TERMINAL\.[^\s]*\s+CARD_READ_INST\b"
    r".*?\bseq=(?P<sequence>\d+)\b"
    r".*?\bD=(?P<payload>[0-9A-Fa-f]{2}(?:\s+[0-9A-Fa-f]{2}){3})\b",
    re.IGNORECASE,
)

INVALID_EXPIRATION_RE = re.compile(r"Invalid expiration month", re.IGNORECASE)

CARD_INSTRUCTION_NAMES = {
    0: "STATUS",
    1: "PREPARE",
    2: "READY",
    3: "COMPLETE",
    4: "ENABLE",
    5: "DISABLE",
    6: "READ_MULT",
}

CARD_FLAG_NAMES = {
    0x01: "STATE_INSERTED",
    0x02: "STATE_CHIP_DATA",
    0x04: "STATE_MAG_DATA",
    0x08: "STATE_DISABLED",
    0x10: "ERROR_INSERT",
    0x20: "ERROR_CHIP",
    0x40: "ERROR_MAG",
    0x80: "ERROR_ABORT",
}


@dataclass
class OperatorCardReaderRunState:
    required_success_count: int
    require_card_accepted: bool
    start_monotonic_s: float
    initial_journal_cursor: str = ""
    current_journal_cursor: str = ""
    reads: List[Dict[str, Any]] = field(default_factory=list)
    instruction_events: List[Dict[str, Any]] = field(default_factory=list)
    diagnostic_events: List[Dict[str, Any]] = field(default_factory=list)
    journal_poll_count: int = 0
    journal_entries_processed: int = 0
    success: bool = False
    final_error: str = ""


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


def _decode_card_instruction(match: re.Match, entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = match.group("payload").upper()
    version, instruction, flags, spare = (
        int(part, 16) for part in payload.split()
    )
    return {
        "timestamp": entry["timestamp"],
        "cursor": entry["cursor"],
        "sequence": int(match.group("sequence")),
        "payload": payload,
        "version": version,
        "instruction": instruction,
        "instruction_name": CARD_INSTRUCTION_NAMES.get(
            instruction, f"UNKNOWN_{instruction}"
        ),
        "flags": flags,
        "flag_names": [
            name for bit, name in CARD_FLAG_NAMES.items() if flags & bit
        ],
        "spare": spare,
    }


def _classify_card_read(
    match: re.Match,
    entry: Dict[str, Any],
    state: OperatorCardReaderRunState,
) -> Dict[str, Any]:
    card_info_type = int(match.group("card_info_type"))
    read_type = int(match.group("read_type"))
    read_type_name = match.group("read_type_name").upper()
    encryption_type = int(match.group("encryption_type"))
    card_type = int(match.group("card_type"))
    card_type_name = match.group("card_type_name").upper()
    card_hash = int(match.group("card_hash"))
    is_card_accepted = match.group("is_card_accepted").lower() == "true"

    retry_reasons: List[str] = []
    if card_info_type != 1:
        retry_reasons.append(f"CardInfoType={card_info_type}, expected 1")
    if read_type != 1 or read_type_name != "MAGSTRIPE":
        retry_reasons.append(
            f"ReadType={read_type}:{read_type_name}, expected 1:MAGSTRIPE"
        )
    if encryption_type != 0:
        retry_reasons.append(
            f"EncryptionType={encryption_type}, expected unencrypted type 0"
        )
    if card_type in {0, 1} or card_type_name in {"INVALID", "UNKNOWN"}:
        retry_reasons.append(
            f"inferred card type is not usable ({card_type}:{card_type_name})"
        )
    if card_hash == EMPTY_TRACK2_CARD_HASH:
        retry_reasons.append(
            "cardHash=2147815457 (0x80051021) indicates zero Track 2 bytes"
        )
    if state.require_card_accepted and not is_card_accepted:
        retry_reasons.append(
            "isCardAccepted=false while require_card_accepted is enabled"
        )

    classification = "retry" if retry_reasons else "pass"
    return {
        "read_number": len(state.reads) + 1,
        "timestamp": entry["timestamp"],
        "cursor": entry["cursor"],
        # This is the processed meter summary, not the raw CARD_READ_DATA D= payload.
        "processed_summary": entry["message"],
        "fw_version": int(match.group("fw_version")),
        "card_info_type": card_info_type,
        "read_type": read_type,
        "read_type_name": read_type_name,
        "encryption_type": encryption_type,
        "card_type": card_type,
        "card_type_name": card_type_name,
        "card_hash": card_hash,
        "card_hash_hex": f"0x{card_hash:08X}",
        "is_card_accepted": is_card_accepted,
        "classification": classification,
        "retry_reasons": retry_reasons,
    }


def _poll_card_reader(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorCardReaderRunState,
) -> None:
    state.journal_poll_count += 1
    command = _journal_after_cursor_command(state.current_journal_cursor)
    try:
        code, output, error = meter.exec_parse(command)
    except Exception as exc:
        raise RuntimeError(f"card reader journal poll failed: {exc}") from exc
    if code != 0:
        detail = str(error or output or f"exit code {code}").strip()
        raise RuntimeError(f"card reader journal poll failed: {detail}")

    entries = _parse_journal_json_batch(output)
    if not entries:
        return

    for entry in entries:
        message = entry["message"]

        instruction_match = CARD_READ_INST_RE.search(message)
        if instruction_match:
            event = _decode_card_instruction(instruction_match, entry)
            instruction_name = event["instruction_name"]
            # PREPARE ordinarily begins a read; STATUS ordinarily reports the state
            # after it. This association is diagnostic only and never gates a result.
            if instruction_name == "PREPARE":
                event["related_read_number"] = len(state.reads) + 1
            else:
                event["related_read_number"] = max(len(state.reads), 1)
            related_read_number = event["related_read_number"]
            if 1 <= related_read_number <= len(state.reads):
                event["related_read_classification"] = state.reads[
                    related_read_number - 1
                ]["classification"]
            else:
                event["related_read_classification"] = "pending"
            state.instruction_events.append(event)
            shared.log(
                "operator card reader CARD_READ_INST: "
                f"payload={event['payload']} | sequence={event['sequence']} | "
                f"instruction={instruction_name} | flags={event['flag_names'] or ['NONE']} | "
                f"related_read={related_read_number} | "
                f"related_classification={event['related_read_classification']} | "
                f"timestamp={event['timestamp']}"
            )

        read_match = PROCESSED_CARD_READ_RE.search(message)
        if read_match:
            read = _classify_card_read(read_match, entry, state)
            state.reads.append(read)
            for event in state.instruction_events:
                if event["related_read_number"] == read["read_number"]:
                    event["related_read_classification"] = read["classification"]
            successful_count = sum(
                item["classification"] == "pass" for item in state.reads
            )
            summary = (
                f"operator card reader read {read['read_number']}: "
                f"classification={read['classification']} | "
                f"card_type={read['card_type']}:{read['card_type_name']} | "
                f"card_hash={read['card_hash']} ({read['card_hash_hex']}) | "
                f"accepted={read['is_card_accepted']} | "
                f"successful_reads={successful_count}/{state.required_success_count}"
            )
            if read["retry_reasons"]:
                summary += f" | reasons={read['retry_reasons']}"
            shared.log(summary)
            shared.log(
                "operator card reader processed summary: "
                f"{read['processed_summary']}"
            )
            # print(f"[{summary}]")

        if INVALID_EXPIRATION_RE.search(message):
            diagnostic = {
                "timestamp": entry["timestamp"],
                "cursor": entry["cursor"],
                "related_read_number": len(state.reads) or None,
                "type": "invalid_expiration_month",
                "message": message,
            }
            state.diagnostic_events.append(diagnostic)
            shared.log(
                "operator card reader diagnostic: Invalid expiration month | "
                f"related_read={diagnostic['related_read_number']} | "
                f"timestamp={diagnostic['timestamp']}"
            )

    # Advance only after the entire JSON batch parses and is processed successfully.
    state.current_journal_cursor = entries[-1]["cursor"]
    state.journal_entries_processed += len(entries)


def _successful_read_count(state: OperatorCardReaderRunState) -> int:
    return sum(read["classification"] == "pass" for read in state.reads)


def _fail_card_reader(
    shared: SharedState,
    state: OperatorCardReaderRunState,
    message: str,
) -> None:
    state.final_error = message
    shared.last_error = message
    device = getattr(shared, "current_device", None) or "card_reader"
    shared.device_results[device] = "fail"
    shared.log(message)
    shared.stop_event.set()
    raise StopAutomation(message)


def _write_card_reader_metadata(
    shared: SharedState,
    state: OperatorCardReaderRunState,
) -> None:
    elapsed_s = max(0.0, time.monotonic() - state.start_monotonic_s)
    meta = shared.device_meta.setdefault("card_reader", {})
    meta.clear()
    meta.update(
        {
            "status": "pass" if state.success else "fail",
            "error": state.final_error or ("" if state.success else shared.last_error or ""),
            "duration_s": round(elapsed_s, 3),
            "classifications": [
                read["classification"] for read in state.reads
            ],
        }
    )


def test_operator_card_reader(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
) -> None:
    """Wait for the operator to produce the requested number of valid card reads."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = _coerce_bool(kwargs.get("subtest", False), "subtest")
    max_duration_s = float(kwargs.get("max_duration_s", 60.0))
    poll_s = float(kwargs.get("poll_s", 0.5))
    job_count = int(kwargs.get("job_count", 1))
    require_card_accepted = _coerce_bool(
        kwargs.get("require_card_accepted", False),
        "require_card_accepted",
    )

    if max_duration_s <= 0:
        raise ValueError(
            "max_duration_s must be greater than zero"
        )
    if poll_s <= 0:
        raise ValueError(
            "poll_s must be greater than zero"
        )
    if job_count <= 0:
        raise ValueError(
            "job_count must be greater than zero"
        )

    state = OperatorCardReaderRunState(
        required_success_count=job_count,
        require_card_accepted=require_card_accepted,
        start_monotonic_s=time.monotonic(),
    )

    shared.log(f"{meter.host} {func_name} 0/{job_count}")
    shared.log(
        f"{meter.host} operator card reader initialized | "
        f"required_success_count={job_count} | "
        f"require_card_accepted={require_card_accepted} | "
        f"max_duration_s={max_duration_s:.1f} | poll_s={poll_s:.2f}"
    )
    if not subtest:
        shared.broadcast_progress(meter.host, "card_reader", 0, job_count)

    try:
        check_stop_event(shared)
        meter.force_diagnostics()
        check_stop_event(shared)

        cursor = _initial_journal_cursor(meter)
        state.initial_journal_cursor = cursor
        state.current_journal_cursor = cursor
        shared.log(
            "operator card reader ready; insert and remove a QA test card | "
            f"journal_unit={JOURNAL_UNIT} | journal_max_lines={JOURNAL_MAX_LINES} | "
            f"starting_cursor={cursor}"
        )

        while True:
            check_stop_event(shared)
            duration_s = time.monotonic() - state.start_monotonic_s
            if duration_s >= max_duration_s:
                _fail_card_reader(
                    shared,
                    state,
                    f"max duration exceeded ({max_duration_s:.1f}s); "
                    f"captured {_successful_read_count(state)}/{job_count} successful "
                    f"card reads ({len(state.reads)} total processed reads)",
                )

            previous_success_count = _successful_read_count(state)
            _poll_card_reader(meter, shared, state)
            successful_count = _successful_read_count(state)

            if not subtest and successful_count > previous_success_count:
                shared.broadcast_progress(
                    meter.host,
                    "card_reader",
                    min(successful_count, job_count),
                    job_count,
                )

            if successful_count >= job_count:
                state.success = True
                device = getattr(shared, "current_device", None) or "card_reader"
                shared.device_results[device] = "pass"
                shared.log(
                    f"operator card reader passed with {successful_count}/{job_count} "
                    f"successful reads ({len(state.reads)} total processed reads)"
                )
                return

            time.sleep(poll_s)

    except Exception as exc:
        if not state.final_error:
            state.final_error = str(exc)
        if not getattr(shared, "last_error", None):
            shared.last_error = state.final_error
        device = getattr(shared, "current_device", None) or "card_reader"
        shared.device_results[device] = "fail"
        raise
    finally:
        _write_card_reader_metadata(shared, state)
        meta = shared.device_meta["card_reader"]
        successful_count = _successful_read_count(state)
        retry_count = len(state.reads) - successful_count
        shared.log(
            "operator card reader final summary: "
            f"success={state.success} | error={state.final_error!r} | "
            f"successful_reads={successful_count}/{job_count} | "
            f"retry_reads={retry_count} | "
            f"total_reads={len(state.reads)} | duration_s={meta['duration_s']} | "
            f"require_card_accepted={require_card_accepted}"
        )
        shared.log(
            "operator card reader final journal details: "
            f"polls={state.journal_poll_count} | "
            f"entries={state.journal_entries_processed} | "
            f"initial_cursor={state.initial_journal_cursor!r} | "
            f"current_cursor={state.current_journal_cursor!r}"
        )
        shared.log(
            "operator card reader final collected data: "
            f"reads={state.reads} | "
            f"CARD_READ_INST={state.instruction_events} | "
            f"diagnostics={state.diagnostic_events}"
        )
