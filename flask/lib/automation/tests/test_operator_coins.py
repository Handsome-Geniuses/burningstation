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
from lib.sse.sse_queue_manager import SSEQM

# TODO (Johnson): Add a way for them to select the type of coins they want to use in the test. And a bool for if they want to allow rejected coins to count or not
# Ex of ALL US coin options: "us": {"penny": {"currency_code": "USD", "value_minor": 1, "quantity": 3}, "nickel": {"currency_code": "USD", "value_minor": 5, "quantity": 3}, "dime": {"currency_code": "USD", "value_minor": 10, "quantity": 3}, "quarter": {"currency_code": "USD", "value_minor": 25, "quantity": 3}, "dollar_coin": {"currency_code": "USD", "value_minor": 100, "quantity": 1}}
# Ex of ALL UK coin options: "uk": {"1p":   {"currency_code": "GBP", "value_minor": 1,   "quantity": 3}, "2p":   {"currency_code": "GBP", "value_minor": 2,   "quantity": 3}, "5p":   {"currency_code": "GBP", "value_minor": 5,   "quantity": 3}, "10p":  {"currency_code": "GBP", "value_minor": 10,  "quantity": 3}, "20p":  {"currency_code": "GBP", "value_minor": 20,  "quantity": 3}, "50p":  {"currency_code": "GBP", "value_minor": 50,  "quantity": 3}, "£1":   {"currency_code": "GBP", "value_minor": 100, "quantity": 3}, "£2":   {"currency_code": "GBP", "value_minor": 200, "quantity": 3}}

# Keep flask/lib/docs/meter/test_operator_coins.md in sync when changing this test.
JOURNAL_UNIT = "MS3_Platform.service"

CURRENCY_ITEM_RE = re.compile(
    r"Meter:sProcessIPSBusMessage(?::\d+)?:\s*"
    r"CURRENCY_ITEM:\s*"
    r"index=(?P<currency_index>\d+)\s+"
    r"type=(?P<item_type>[^\s]+)\s+"
    r"handling:(?P<handling>[^\s]+)\s+"
    r"location:(?P<location>[^\s]+)\s+"
    r"validationWindow:(?P<validation_window>\d+)\s+"
    r"itemIndex:(?P<item_index>\d+)\s+"
    r"configVersion=(?P<config_version>\d+)\s+"
    r"value=(?P<value>[+-]?\d+)\s+"
    r"code='(?P<currency_code>[^']*)'",
    re.IGNORECASE,
)

DEFAULT_COIN_REQUIREMENTS_BY_REGION: Dict[str, Dict[str, Dict[str, Any]]] = {
    "us": {
        "penny": {
            "currency_code": "USD",
            "value_minor": 1,
            "quantity": 3,
        },
        "nickel": {
            "currency_code": "USD",
            "value_minor": 5,
            "quantity": 3,
        },
        "dime": {
            "currency_code": "USD",
            "value_minor": 10,
            "quantity": 3,
        },
        "quarter": {
            "currency_code": "USD",
            "value_minor": 25,
            "quantity": 3,
        },
        "dollar_coin": {
            "currency_code": "USD",
            "value_minor": 100,
            "quantity": 1,
        },
    },
    "uk": {
        "5p": {
            "currency_code": "GBP",
            "value_minor": 5,
            "quantity": 3,
        },
        "10p": {
            "currency_code": "GBP",
            "value_minor": 10,
            "quantity": 3,
        },
        "20p": {
            "currency_code": "GBP",
            "value_minor": 20,
            "quantity": 3,
        },
        "50p": {
            "currency_code": "GBP",
            "value_minor": 50,
            "quantity": 3,
        },
    },
}


@dataclass(frozen=True)
class CoinRequirement:
    name: str
    currency_code: str
    value_minor: int
    quantity: int

    @property
    def identity(self) -> Tuple[str, int]:
        return self.currency_code, self.value_minor


@dataclass
class OperatorCoinsRunState:
    start_monotonic_s: float
    allow_rejected: bool = False
    requirements: Dict[str, CoinRequirement] = field(default_factory=dict)
    counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    initial_journal_cursor: str = ""
    current_journal_cursor: str = ""
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    journal_poll_count: int = 0
    journal_entries_processed: int = 0
    journal_read_error_count: int = 0
    journal_consecutive_read_errors: int = 0
    journal_last_error: str = ""
    total_coins_detected: int = 0
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


def _coerce_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, str) and not re.fullmatch(r"[+-]?\d+", value.strip()):
        raise ValueError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _default_coin_requirements(meter_region: Any) -> Dict[str, Dict[str, Any]]:
    region = str(meter_region or "").strip().lower()
    defaults = DEFAULT_COIN_REQUIREMENTS_BY_REGION.get(region)
    if defaults is None:
        raise ValueError(
            f"coin_requirements is required for unsupported meter region {region!r}"
        )
    return {name: dict(config) for name, config in defaults.items()}


def _normalize_coin_requirements(
    raw_requirements: Any,
) -> Dict[str, CoinRequirement]:
    if not isinstance(raw_requirements, dict) or not raw_requirements:
        raise ValueError("coin_requirements must be a non-empty mapping")

    requirements: Dict[str, CoinRequirement] = {}
    identities: Dict[Tuple[str, int], str] = {}
    for raw_name, raw_config in raw_requirements.items():
        name = str(raw_name or "").strip()
        if not name:
            raise ValueError("coin requirement names must be non-empty")
        if not isinstance(raw_config, dict):
            raise ValueError(f"coin requirement {name!r} must be a mapping")
        if "allow_rejected" in raw_config:
            raise ValueError(
                f"coin requirement {name!r} contains allow_rejected; pass "
                "allow_rejected once as a top-level test kwarg"
            )

        currency_code = str(raw_config.get("currency_code") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency_code):
            raise ValueError(
                f"coin requirement {name!r} currency_code must be three letters"
            )

        try:
            raw_value_minor = raw_config["value_minor"]
            raw_quantity = raw_config["quantity"]
        except KeyError as exc:
            raise ValueError(
                f"coin requirement {name!r} is missing {exc.args[0]!r}"
            ) from exc

        value_minor = _coerce_integer(
            raw_value_minor,
            f"coin requirement {name!r} value_minor",
        )
        quantity = _coerce_integer(
            raw_quantity,
            f"coin requirement {name!r} quantity",
        )

        if value_minor <= 0:
            raise ValueError(
                f"coin requirement {name!r} value_minor must be greater than zero"
            )
        if quantity <= 0:
            raise ValueError(
                f"coin requirement {name!r} quantity must be greater than zero"
            )

        requirement = CoinRequirement(
            name=name,
            currency_code=currency_code,
            value_minor=value_minor,
            quantity=quantity,
        )
        duplicate_name = identities.get(requirement.identity)
        if duplicate_name is not None:
            raise ValueError(
                f"coin requirements {duplicate_name!r} and {name!r} have the same "
                f"identity {currency_code}/{value_minor}"
            )
        identities[requirement.identity] = name
        requirements[name] = requirement

    return requirements


def _initialize_counts(state: OperatorCoinsRunState) -> None:
    state.counts = {
        name: {
            "detected": 0,
            "accepted": 0,
            "rejected": 0,
            "qualified": 0,
            "credited": 0,
        }
        for name in state.requirements
    }


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
        "--no-pager -o json"
    )


def _requirement_by_identity(
    state: OperatorCoinsRunState,
) -> Dict[Tuple[str, int], CoinRequirement]:
    return {requirement.identity: requirement for requirement in state.requirements.values()}


def _parse_coin_attempt(
    match: re.Match,
    entry: Dict[str, Any],
    state: OperatorCoinsRunState,
) -> Dict[str, Any]:
    handling = match.group("handling").strip().lower()
    currency_code = match.group("currency_code").strip().upper()
    signed_value = int(match.group("value"))
    value_minor = abs(signed_value)
    detected = bool(currency_code and signed_value != 0)
    detection_number: Optional[int] = None
    if detected:
        state.total_coins_detected += 1
        detection_number = state.total_coins_detected

    requirement = None
    if detected:
        requirement = _requirement_by_identity(state).get(
            (currency_code, value_minor)
        )

    accepted = handling == "accept"
    rejected = handling == "reject"
    eligible = False
    credited = False
    requirement_count: Optional[int] = None
    requirement_quantity: Optional[int] = None

    if requirement is not None:
        counts = state.counts[requirement.name]
        counts["detected"] += 1
        if accepted:
            counts["accepted"] += 1
        elif rejected:
            counts["rejected"] += 1

        eligible = accepted or (rejected and state.allow_rejected)
        if eligible:
            counts["qualified"] += 1
            if counts["credited"] < requirement.quantity:
                counts["credited"] += 1
                credited = True
        requirement_count = counts["credited"]
        requirement_quantity = requirement.quantity

    return {
        "insertion_number": len(state.attempts) + 1,
        "detection_number": detection_number,
        "timestamp": entry["timestamp"],
        "cursor": entry["cursor"],
        "currency_index": int(match.group("currency_index")),
        "item_type": match.group("item_type").strip().lower(),
        "handling": handling,
        "location": match.group("location").strip().lower(),
        "validation_window": int(match.group("validation_window")),
        "item_index": int(match.group("item_index")),
        "config_version": int(match.group("config_version")),
        "signed_value": signed_value,
        "value_minor": value_minor,
        "currency_code": currency_code,
        "detected": detected,
        "matched_requirement": requirement.name if requirement else None,
        "required_for_test": requirement is not None,
        "eligible": eligible,
        "credited": credited,
        "requirement_count": requirement_count,
        "requirement_quantity": requirement_quantity,
        "processed_summary": entry["message"],
    }


def _log_coin_attempt(shared: SharedState, attempt: Dict[str, Any]) -> None:
    requirement_progress = "n/a"
    if attempt["matched_requirement"] is not None:
        requirement_progress = (
            f"{attempt['requirement_count']}/{attempt['requirement_quantity']}"
        )
    shared.log(
        "operator coins attempt: "
        f"insertion={attempt['insertion_number']} | "
        f"detection={attempt['detection_number']} | "
        f"coin={attempt['currency_code']}/{attempt['value_minor']} | "
        f"signed_value={attempt['signed_value']} | "
        f"handling={attempt['handling']} | location={attempt['location']} | "
        f"requirement={attempt['matched_requirement']!r} | "
        f"eligible={attempt['eligible']} | credited={attempt['credited']} | "
        f"requirement_progress={requirement_progress} | "
        f"currency_index={attempt['currency_index']} | "
        f"validation_window={attempt['validation_window']} | "
        f"item_index={attempt['item_index']} | "
        f"config_version={attempt['config_version']} | "
        f"timestamp={attempt['timestamp']}"
    )
    shared.log(
        "operator coins processed summary: "
        f"{attempt['processed_summary']}"
    )


def _poll_coin_attempts(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorCoinsRunState,
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
        message = f"operator coins journal poll failed: {exc}"
        state.journal_read_error_count += 1
        state.journal_consecutive_read_errors += 1
        if message != state.journal_last_error or state.journal_consecutive_read_errors == 1:
            shared.log(message)
        state.journal_last_error = message
        return 0

    if state.journal_consecutive_read_errors:
        shared.log("operator coins journal acquisition recovered")
    state.journal_consecutive_read_errors = 0

    if not entries:
        return 0

    attempts_added = 0
    for entry in entries:
        match = CURRENCY_ITEM_RE.search(entry["message"])
        if not match or match.group("item_type").strip().lower() != "coin":
            continue
        attempt = _parse_coin_attempt(match, entry, state)
        state.attempts.append(attempt)
        attempts_added += 1
        _log_coin_attempt(shared, attempt)

    # Advance only after the complete JSON batch parses and processes successfully.
    state.current_journal_cursor = entries[-1]["cursor"]
    state.journal_entries_processed += len(entries)
    return attempts_added


def _progress_totals(state: OperatorCoinsRunState) -> Tuple[int, int]:
    current = sum(counts["credited"] for counts in state.counts.values())
    total = sum(requirement.quantity for requirement in state.requirements.values())
    return current, total


def _detections_dict(state: OperatorCoinsRunState) -> Dict[str, Dict[str, Any]]:
    return {
        name: {
            "currency_code": requirement.currency_code,
            "value_minor": requirement.value_minor,
            "required": requirement.quantity,
            "detected": state.counts.get(name, {}).get("detected", 0),
            "accepted": state.counts.get(name, {}).get("accepted", 0),
            "rejected": state.counts.get(name, {}).get("rejected", 0),
            "qualified": state.counts.get(name, {}).get("qualified", 0),
            "credited": state.counts.get(name, {}).get("credited", 0),
        }
        for name, requirement in state.requirements.items()
    }


def _broadcast_coin_state(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorCoinsRunState,
    *,
    status: str,
    error: str = "",
) -> None:
    current, total = _progress_totals(state)
    shared.broadcast_progress(meter.host, "operator_coins", current, total)
    SSEQM.broadcast(
        "operator_coins",
        {
            "ip": meter.host,
            "progress_percent": float(current / total) if total else 0.0,
            "current": current,
            "total": total,
            "allow_rejected": state.allow_rejected,
            "detections": _detections_dict(state),
            "status": status,
            "error": error,
        },
    )
    # TODO (Johnson): Use this to update the station's UI to show how many coins are still required and what type(s). "detections" holds a dict of "<coin_name>" being tested and then you can grab and display each ones "accepted" and "required"


def _missing_requirements(state: OperatorCoinsRunState) -> Dict[str, int]:
    return {
        name: requirement.quantity - state.counts[name]["credited"]
        for name, requirement in state.requirements.items()
        if state.counts[name]["credited"] < requirement.quantity
    }


def _fail_coins(
    shared: SharedState,
    state: OperatorCoinsRunState,
    message: str,
) -> None:
    state.final_error = message
    shared.last_error = message
    device = getattr(shared, "current_device", None) or "coins"
    shared.device_results[device] = "fail"
    shared.log(message)
    shared.stop_event.set()
    raise StopAutomation(message)


def _cleanup_coin_tallies(
    meter: SSHMeter,
    shared: SharedState,
    state: OperatorCoinsRunState,
) -> None:
    state.cleanup_attempted = True
    try:
        result = meter.clear_coin_tallies()
        state.cleanup_success = result is True
        if not state.cleanup_success:
            state.cleanup_error = "meter.clear_coin_tallies() returned false"
    except Exception as exc:
        state.cleanup_success = False
        state.cleanup_error = f"meter.clear_coin_tallies() failed: {exc}"

    if state.cleanup_success:
        shared.log(f"{meter.host} operator coins clear_coin_tallies result = True")
    else:
        shared.log(
            f"{meter.host} operator coins clear_coin_tallies failure | "
            f"{state.cleanup_error}"
        )


def _combine_errors(primary_error: str, cleanup_error: str) -> str:
    if primary_error and cleanup_error:
        return f"{primary_error}; cleanup failed: {cleanup_error}"
    return primary_error or cleanup_error


def _write_coin_metadata(
    shared: SharedState,
    state: OperatorCoinsRunState,
) -> None:
    current, total = _progress_totals(state)
    meta = shared.device_meta.setdefault("coins", {})
    meta.clear()
    meta.update(
        {
            "result": "pass" if state.success else "fail",
            "error": state.final_error,
            "elapsed_time": round(
                max(0.0, time.monotonic() - state.start_monotonic_s), 3
            ),
            "total_coins_detected": state.total_coins_detected,
            "total_coins_inserted": len(state.attempts),
            "total_coins_required": total,
            "total_coins_credited": current,
            "allow_rejected": state.allow_rejected,
            "detections_dict": _detections_dict(state),
            "cleanup": {
                "attempted": state.cleanup_attempted,
                "success": state.cleanup_success,
                "error": state.cleanup_error,
            },
        }
    )


def test_operator_coins(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
) -> None:
    """Run the operator-guided physical coin validator test.

    ``coin_requirements`` is a mapping whose keys are display names and whose
    values describe the denomination to detect. Each denomination must provide:

    - ``currency_code``: a three-letter currency code such as ``"USD"``,
      ``"GBP"``, or ``"EUR"``. Matching is case-insensitive.
    - ``value_minor``: the positive integer value in the currency's minor unit
      (for example, cents or pence).
    - ``quantity``: the positive number of qualifying detections required.

    Display names are used in logs, broadcasts, and result metadata only. Coin
    events are matched by ``currency_code`` plus the absolute ``value_minor``;
    validator indexes are configuration-dependent and are diagnostic only.

    A mapping containing every standard US coin option is::

        {
            "penny": {
                "currency_code": "USD", "value_minor": 1, "quantity": 3
            },
            "nickel": {
                "currency_code": "USD", "value_minor": 5, "quantity": 3
            },
            "dime": {
                "currency_code": "USD", "value_minor": 10, "quantity": 3
            },
            "quarter": {
                "currency_code": "USD", "value_minor": 25, "quantity": 3
            },
            "dollar_coin": {
                "currency_code": "USD", "value_minor": 100, "quantity": 1
            },
        }

    A mapping containing every standard UK coin option is::

        {
            "1p": {
                "currency_code": "GBP", "value_minor": 1, "quantity": 3
            },
            "2p": {
                "currency_code": "GBP", "value_minor": 2, "quantity": 3
            },
            "5p": {
                "currency_code": "GBP", "value_minor": 5, "quantity": 3
            },
            "10p": {
                "currency_code": "GBP", "value_minor": 10, "quantity": 3
            },
            "20p": {
                "currency_code": "GBP", "value_minor": 20, "quantity": 3
            },
            "50p": {
                "currency_code": "GBP", "value_minor": 50, "quantity": 3
            },
            "£1": {
                "currency_code": "GBP", "value_minor": 100, "quantity": 3
            },
            "£2": {
                "currency_code": "GBP", "value_minor": 200, "quantity": 3
            },
        }

    The UK example above lists all denominations that may be explicitly
    requested; the built-in UK default selects 5p, 10p, 20p, and 50p. Other
    currencies and display names may be supplied with the same schema, subject
    to the denominations supported by the meter's validator configuration.

    Optional keyword arguments are:

    - ``coin_requirements``: the mapping described above. When omitted, the
      default mapping for ``meter.meter_region`` is used.
    - ``allow_rejected=False``: a single run-wide policy. Accepted matching
      coins always qualify; rejected matching coins qualify only when this is
      true. It applies equally to every requested denomination.
    - ``max_duration_s=60.0``: maximum time allowed for the operator to meet
      all requirements.
    - ``poll_s=0.75``: delay between journal polls.
    - ``job_count=1``: accepted for automation compatibility but does not
      have any effect on requested quantities.
    - ``subtest=False``: identifies execution within ``operator_cycle_all`` and
      enables its standard subtest progress behavior.

    The test passes when every requirement's credited count reaches its
    quantity. Extra, unmatched, unknown, and non-qualifying rejected attempts
    remain available in diagnostic logs but do not inflate progress.
    """
    func_name = inspect.currentframe().f_code.co_name
    state = OperatorCoinsRunState(start_monotonic_s=time.monotonic())
    caught_exception: Optional[Exception] = None
    caught_traceback: Optional[TracebackType] = None

    try:
        subtest = _coerce_bool(kwargs.get("subtest", False), "subtest")
        max_duration_s = float(kwargs.get("max_duration_s", 60.0))
        poll_s = float(kwargs.get("poll_s", 0.75))
        job_count = int(kwargs.get("job_count", 1))
        state.allow_rejected = _coerce_bool(
            kwargs.get("allow_rejected", False),
            "allow_rejected",
        )
        if max_duration_s <= 0:
            raise ValueError("max_duration_s must be greater than zero")
        if poll_s <= 0:
            raise ValueError("poll_s must be greater than zero")
        if job_count <= 0:
            raise ValueError("job_count must be greater than zero")

        raw_requirements = kwargs.get("coin_requirements")
        if raw_requirements is None:
            raw_requirements = _default_coin_requirements(
                getattr(meter, "meter_region", "")
            )
        state.requirements = _normalize_coin_requirements(raw_requirements)
        _initialize_counts(state)
        total_required = _progress_totals(state)[1]

        shared.log(f"{meter.host} {func_name} 0/{total_required}")
        shared.log(
            f"{meter.host} operator coins initialized | "
            f"meter_region={getattr(meter, 'meter_region', '')!r} | "
            f"requirements={_detections_dict(state)} | "
            f"allow_rejected={state.allow_rejected} | "
            f"max_duration_s={max_duration_s:.1f} | poll_s={poll_s:.2f} | "
            f"subtest={subtest}"
        )
        if job_count > 1:
            shared.log(
                f"operator coins job_count={job_count} is currently used only to "
                "enable the subtest; coin_requirements controls required quantities"
            )
        _broadcast_coin_state(meter, shared, state, status="running")

        check_stop_event(shared)
        cursor = _initial_journal_cursor(meter)
        state.initial_journal_cursor = cursor
        state.current_journal_cursor = cursor
        shared.log(f"operator coins initial journal cursor={cursor}")

        meter.goto_coins()
        shared.log("operator coins ready; insert the requested physical coins")

        while True:
            check_stop_event(shared)
            elapsed_s = time.monotonic() - state.start_monotonic_s
            if elapsed_s >= max_duration_s:
                if state.journal_consecutive_read_errors:
                    _fail_coins(
                        shared,
                        state,
                        "operator coins journal acquisition remained unavailable "
                        f"until max duration: {state.journal_last_error}",
                    )
                _fail_coins(
                    shared,
                    state,
                    f"max duration exceeded ({max_duration_s:.1f}s); "
                    f"missing={_missing_requirements(state)}",
                )

            attempts_added = _poll_coin_attempts(meter, shared, state)
            if attempts_added:
                _broadcast_coin_state(meter, shared, state, status="running")

            current, total = _progress_totals(state)
            if total > 0 and current >= total:
                state.success = True
                shared.log(
                    f"operator coins requirements satisfied: {current}/{total} | "
                    f"detections={_detections_dict(state)}"
                )
                break

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
        _cleanup_coin_tallies(meter, shared, state)
        if not state.cleanup_success:
            state.success = False
            state.final_error = _combine_errors(
                state.final_error,
                state.cleanup_error,
            )

        device = getattr(shared, "current_device", None) or "coins"
        shared.device_results[device] = "pass" if state.success else "fail"
        if not state.success:
            shared.last_error = state.final_error
            shared.stop_event.set()

        _write_coin_metadata(shared, state)
        meta = shared.device_meta["coins"]
        shared.log(
            "operator coins final summary: "
            f"success={state.success} | error={state.final_error!r} | "
            f"inserted={len(state.attempts)} | "
            f"detected={state.total_coins_detected} | "
            f"progress={meta['total_coins_credited']}/{meta['total_coins_required']} | "
            f"allow_rejected={state.allow_rejected} | "
            f"elapsed_time={meta['elapsed_time']} | "
            f"cleanup_success={state.cleanup_success}"
        )
        shared.log(
            "operator coins final journal details: "
            f"polls={state.journal_poll_count} | "
            f"entries={state.journal_entries_processed} | "
            f"read_errors={state.journal_read_error_count} | "
            f"initial_cursor={state.initial_journal_cursor!r} | "
            f"current_cursor={state.current_journal_cursor!r}"
        )
        shared.log(f"operator coins final collected attempts: {state.attempts}")
        _broadcast_coin_state(
            meter,
            shared,
            state,
            status="pass" if state.success else "fail",
            error=state.final_error,
        )

    if caught_exception is not None:
        raise caught_exception.with_traceback(caught_traceback)
    if not state.cleanup_success:
        raise StopAutomation(state.final_error)
