"""
Shared pay-to-park UI automation for burn-in / validation runs.

This module drives the customer-facing parking flow by repeatedly:
1. reading the current `UIPage.php` HTML from the meter,
2. classifying that HTML into a coarse `ParkingUIState`,
3. planning the next action needed to reach a successful payment, and
4. executing that action until the flow completes or fails.

Important assumptions for future revisions:
- The heuristics in this file are region-aware and currently target the
  pay-to-park flows captured for US and UK meters (`meter_region` of `us` or
  `uk`). If new regions are added, extend the classifier instead of hardcoding
  one-off button scripts.
- The logic intentionally tolerates small text/layout changes by looking for
  stable phrases and title codes instead of exact full-page matches.
- This flow is meant to be reused across passive and physical programs, so new
  payment or monitor combinations should generally be added here rather than by
  creating a separate screen-test implementation.
- `_wait_for_q_press` is a local/manual debugging hook only. It is not intended
  for unattended production runs.
"""

from dataclasses import dataclass
from enum import Enum
from html import unescape
from typing import Any, Callable, Optional
import inspect
import random
import re
import string
import time

from lib.automation.helpers import check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import COIN_VALUE_TO_INDEX_BY_REGION, SSHMeter
from lib.robot.robot_client import RobotClient

try:
    import msvcrt
except ImportError:
    msvcrt = None


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TITLE_RE = re.compile(r"<title>\s*([^<]+)\s*</title>", re.I)
VALUEBOX_RE = re.compile(r"<div class=valuebox>(.*?)</div>", re.I | re.S)
MONEY_RE = re.compile("(?:\\$|\\u00a3)\\s*([0-9]+(?:\\.[0-9]{1,2})?)")
CARD_MASKED_RE = re.compile(r"Card read:\s*([Xx*\d ]+)", re.I)
PAN_MASKED_RE = re.compile(r"\bPAN\s+([Xx*\d ]{4,})", re.I)
CARD_REF_RE = re.compile(r"refStr=(\d{4})", re.I)
LAST4_RE = re.compile(r"\blast4=([Xx*\d ]{4,})", re.I)
HEX_BYTE_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")
PAN_FROM_TRACK_RE = re.compile(r"(\d{12,19})(?=[=^D])")
LONG_CARD_RE = re.compile(r"(?<!\d)(\d{12,19})(?!\d)")
PRE_CARD_SEND_DELAY_S = 4.0


class PaymentType(Enum):
    """Supported high-level payment modes for the pay-to-park flow."""

    AUTO = 0
    COINS = 1
    CONTACT_CREDIT_CARD = 2
    ROBOT_CONTACTLESS = 3


@dataclass
class ParkingUIState:
    """Normalized snapshot of the currently displayed pay-to-park UI page."""

    kind: str
    title: str
    html: str
    text: str
    region: str = ""
    plate_value: str = ""
    cost_cents: Optional[int] = None
    amount_due_cents: Optional[int] = None
    coins_inserted_cents: Optional[int] = None
    payment_complete: bool = False

    @property
    def summary(self) -> str:
        parts = [self.kind]
        if self.region:
            parts.append(f"region={self.region}")
        if self.title:
            parts.append(f"title={self.title}")
        if self.plate_value:
            parts.append(f"plate={self.plate_value}")
        if self.cost_cents is not None:
            parts.append(f"cost={self.cost_cents}")
        if self.amount_due_cents is not None:
            parts.append(f"due={self.amount_due_cents}")
        if self.coins_inserted_cents is not None:
            parts.append(f"paid={self.coins_inserted_cents}")
        if self.payment_complete:
            parts.append("complete")
        return " ".join(parts)

    @property
    def snippet(self) -> str:
        if len(self.text) <= 220:
            return self.text
        return self.text[:217] + "..."


@dataclass
class PaySessionContext:
    """
    Mutable state carried through a single parking session attempt.

    This keeps planner memory such as:
    - which payment mode is active,
    - whether we already accepted the amount or sent a card,
    - how many retries/unknown pages have occurred,
    - and any robot/card-journal bookkeeping needed after success.
    """

    requested_payment_type: PaymentType
    effective_payment_type: PaymentType
    plate: str
    allow_coin_fallback: bool
    has_left_home: bool = False
    saw_success: bool = False
    retry_count: int = 0
    max_retries: int = 0
    home_start_attempts: int = 0
    duration_confirm_attempts: int = 0
    duration_plus_target: Optional[int] = None
    duration_plus_presses: int = 0
    payment_amount_accepted: bool = False
    payment_confirm_accepted: bool = False
    payment_entry_attempts: int = 0
    payment_method_selected: bool = False
    card_prompt_started: bool = False
    card_sent: bool = False
    card_journal_since: str = ""
    robot: Optional[RobotClient] = None
    robot_payment_job_id: Optional[str] = None
    charuco_frame: Any = None
    card_read_waits: int = 0
    error_count: int = 0
    fallback_to_coins_used: bool = False
    unknown_count: int = 0

    def reset_for_retry(self) -> None:
        self.has_left_home = False
        self.home_start_attempts = 0
        self.duration_confirm_attempts = 0
        self.duration_plus_target = None
        self.duration_plus_presses = 0
        self.payment_amount_accepted = False
        self.payment_confirm_accepted = False
        self.payment_entry_attempts = 0
        self.payment_method_selected = False
        self.card_prompt_started = False
        self.card_sent = False
        self.robot_payment_job_id = None
        self.card_read_waits = 0
        self.unknown_count = 0


@dataclass
class PayUIAction:
    """Planner output describing the next meter or robot action to perform."""

    kind: str
    detail: str
    button: str = ""
    coin_value: Optional[int] = None
    card_value: str = ""
    robot_program: str = ""
    delay: float = 0.6


class PayToParkSessionError(RuntimeError):
    """
    Failure raised after collecting any session metadata we still want to keep.

    This lets `run_pay_to_park_session()` preserve the existing "fail this run
    immediately" behavior while still handing `test_cycle_meter_ui()` the
    per-session metadata it needs to record in `shared.device_meta`, such as the
    detected card `last4`.
    """

    def __init__(self, detail: str, *, session_result: Optional[dict[str, Any]] = None):
        super().__init__(detail)
        self.session_result = session_result or {}


def random_plate(length: int = 7) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _clear_screen_test_coin_tallies(
    meter: SSHMeter,
    shared: Optional[SharedState],
    *,
    reason: str,
) -> None:
    try:
        coin_tally_reset = meter.clear_coin_tallies()
    except Exception as exc:
        if shared:
            shared.log(f"{meter.host} screen test clear_coin_tallies warning ({reason}) | {exc}")
        return

    if shared:
        shared.log(f"{meter.host} screen test clear_coin_tallies result = {coin_tally_reset} ({reason})")


def _coerce_bool(value, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False

    return bool(value)


def _parse_payment_type(value) -> PaymentType:
    """Accept enum values plus the string variants used by jobs/tests."""

    if isinstance(value, PaymentType):
        return value

    normalized = str(value or "auto").strip().upper().replace("-", "_").replace(" ", "_")
    if normalized == "CONTACTLESS_CARD":
        return PaymentType.CONTACT_CREDIT_CARD

    return PaymentType[normalized]


def _journal_since_now(meter: SSHMeter) -> str:
    return meter.cli("date '+%Y-%m-%d %H:%M:%S'")


def _decode_card_payload(line: str) -> str:
    if " D=" not in line:
        return ""

    payload = line.split(" D=", 1)[1]
    tokens = HEX_BYTE_RE.findall(payload)
    if not tokens:
        return ""

    raw = bytes(int(token, 16) for token in tokens)
    return "".join(chr(value) if 32 <= value < 127 else " " for value in raw)


def _extract_last4_from_card_line(line: str) -> Optional[str]:
    ref_match = CARD_REF_RE.search(line)
    if ref_match:
        return ref_match.group(1)

    masked_match = CARD_MASKED_RE.search(line) or PAN_MASKED_RE.search(line) or LAST4_RE.search(line)
    if masked_match:
        digits = re.sub(r"\D", "", masked_match.group(1))
        if len(digits) >= 4:
            return digits[-4:]

    decoded = _decode_card_payload(line)
    if decoded:
        pan_matches = PAN_FROM_TRACK_RE.findall(decoded)
        if pan_matches:
            return pan_matches[-1][-4:]

        long_matches = LONG_CARD_RE.findall(decoded)
        if long_matches:
            return long_matches[-1][-4:]

    return None


def _get_latest_card_last4(meter: SSHMeter, since: str) -> Optional[str]:
    """
    Search a narrow journalctl window for the most recent card read.

    The search intentionally uses a bounded `--since` timestamp and a capped
    line count so we do not accidentally pull card data from an older cycle or
    overload the SSH session by reading too much journal output at once.
    """

    cmd = (
        f"journalctl -u MS3_Platform.service --since \"{since}\" -n 800 --no-pager | "
        "grep -E 'CARD_READ_DATA|refStr=|Card read:|receiptText=|PAN [Xx*0-9 ]+|EMV_TRANS_RESULT|last4=' | tail -n 80"
    )
    res = meter.cli(cmd)
    if not res:
        return None

    for line in reversed(res.splitlines()):
        last4 = _extract_last4_from_card_line(line)
        if last4:
            return last4

    return None


def _strip_html(value: str) -> str:
    text = unescape(value or "")
    text = text.replace("\xa0", " ")
    text = text.replace("\u00c2\u00a3", "\u00a3")
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text.replace("\u00c2\u00a3", "\u00a3")


def _title_code(html: str) -> str:
    match = TITLE_RE.search(html)
    return match.group(1).strip().lower() if match else ""


def _parse_money_cents(value: str) -> Optional[int]:
    match = MONEY_RE.search(value)
    if not match:
        return None
    return int(round(float(match.group(1)) * 100))


def _money_after(label: str, text: str) -> Optional[int]:
    match = re.search(
        rf"{re.escape(label)}\s*:\s*(?:\$|\u00a3)\s*([0-9]+(?:\.[0-9]{{1,2}})?)",
        text,
        re.I,
    )
    if not match:
        return None
    return int(round(float(match.group(1)) * 100))


def _parse_plate_value(html: str) -> str:
    match = VALUEBOX_RE.search(html)
    return _strip_html(match.group(1)) if match else ""


def _truncate_log_value(value: str, limit: int = 500) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _normalize_meter_region(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"us", "uk"}:
        return normalized
    return ""


def _meter_region(meter: SSHMeter) -> str:
    return _normalize_meter_region(getattr(meter, "meter_region", "")) or "us"


def _supported_coin_values(meter_region: str) -> tuple[int, ...]:
    region = _normalize_meter_region(meter_region) or "us"
    value_to_index = COIN_VALUE_TO_INDEX_BY_REGION.get(region)
    if not value_to_index:
        value_to_index = COIN_VALUE_TO_INDEX_BY_REGION["us"]
    return tuple(sorted(value_to_index.keys(), reverse=True))


def _candidate_regions(region_hint: str) -> list[str]:
    region = _normalize_meter_region(region_hint)
    candidates = []
    if region:
        candidates.append(region)
    for fallback in ("us", "uk"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _classify_us_parking_kind(title: str, html_lower: str, text_lower: str) -> str:
    if "available languages" in text_lower or "select language" in text_lower or title == "64":
        return "language"
    if "payment required" in text_lower or "press any key to start" in text_lower or title == "00":
        return "home"
    if "enter your plate number below" in text_lower or "plate #" in text_lower or title == "09":
        return "plate_entry"
    if "select parking duration" in text_lower or (
        title == "12" and "parking duration" in text_lower
    ):
        return "duration_select"
    if "credit card confirmation" in text_lower or "confirm $" in text_lower or title == "99":
        return "payment_confirm"
    if "credit card not accepted" in text_lower or "declined" in text_lower or title == "69":
        return "payment_error"
    if "please tap or insert/remove card" in text_lower:
        return "payment_card_ready"
    if "card read ok, remove card" in text_lower:
        return "payment_card_read"
    if (
        "authorizing" in text_lower
        or "please wait" in text_lower
        or ("emv" in text_lower and "welcome" in text_lower)
        or title in {"24", "74", "nn"}
    ):
        return "payment_loading"
    if "accepting payment" in text_lower or "amount due" in text_lower:
        return "payment_amount"
    if (
        "approved" in text_lower
        or "transaction complete" in text_lower
        or "thank you" in text_lower
        or title == "23"
    ):
        return "success"
    return "other"


def _classify_uk_parking_kind(title: str, html_lower: str, text_lower: str) -> str:
    if "available languages" in text_lower or "select language" in text_lower:
        return "language"
    if (
        title == "00"
        or "payment for parking required" in text_lower
        or ("press power" in text_lower and "start" in text_lower)
    ):
        return "home"
    if title == "76" or "select your parking duration" in text_lower:
        return "duration_select"
    if (
        title == "22"
        or "select payment type" in text_lower
        or "coins inserted" in text_lower
        or "balance required" in text_lower
    ):
        return "payment_amount"
    if title == "73" or ("confirmation" in text_lower and "print ticket" in text_lower):
        return "payment_confirm"
    if (
        title == "74"
        or (
            "credit card payment" in text_lower
            and "when green light shows" in text_lower
        )
    ):
        return "payment_card_start"
    if title == "pc" and ("please insert or tap card" in text_lower or "insert or tap card" in text_lower):
        return "payment_card_ready"
    if title == "27" or "declined" in text_lower or "please try another payment method" in text_lower:
        return "payment_error"
    if title == "79" and ("timing out" in text_lower or "transaction cancelled" in text_lower):
        return "payment_error"
    if title == "23" or "your ticket is printing" in text_lower or (title == "pc" and "approved" in text_lower):
        return "success"
    if (
        title in {"72", "pc"}
        or "please wait" in text_lower
        or "preparing emv read" in text_lower
        or "contacting bank" in text_lower
        or ("credit card payment" in text_lower and "welcome" in text_lower)
    ):
        return "payment_loading"
    return "other"


def classify_parking_ui_html(
    html: str,
    meter_region: str = "",
    log: Optional[Callable[[str], None]] = None,
) -> ParkingUIState:
    """
    Convert raw `UIPage.php` HTML into a normalized UI state.

    The region hint is used first, but we fall back across the known region
    classifiers so the state machine can still recover if the hint is missing.
    """

    html = html or ""
    text = _strip_html(html)
    text_lower = text.lower()
    html_lower = html.lower()
    title = _title_code(html)
    cost_cents = _money_after("cost", text)
    amount_due_cents = _money_after("amount due", text)
    if amount_due_cents is None:
        amount_due_cents = _money_after("balance required", text)
    coins_inserted_cents = _money_after("coins inserted", text)
    plate_value = ""
    payment_complete = "pmtcomplete" in html_lower
    region = _normalize_meter_region(meter_region)

    if "diagtitle" in html_lower or "diagcontent" in html_lower:
        kind = "diagnostics"
    elif "out of order" in text_lower:
        kind = "out_of_order"
    else:
        kind = "other"
        for candidate in _candidate_regions(region):
            if candidate == "uk":
                kind = _classify_uk_parking_kind(title, html_lower, text_lower)
            else:
                kind = _classify_us_parking_kind(title, html_lower, text_lower)
            if kind != "other":
                if not region:
                    region = candidate
                break

        if not region and kind == "other" and log:
            log(
                "screen test classifier unknown page with no meter_region hint -> "
                f"title={title or '<none>'} | "
                f"text_lower={_truncate_log_value(text_lower)} | "
                f"html_lower={_truncate_log_value(html_lower)}"
            )

    if kind == "plate_entry":
        plate_value = _parse_plate_value(html)

    if payment_complete and amount_due_cents is None:
        amount_due_cents = 0

    return ParkingUIState(
        kind=kind,
        title=title,
        html=html,
        text=text,
        region=region,
        plate_value=plate_value,
        cost_cents=cost_cents,
        amount_due_cents=amount_due_cents,
        coins_inserted_cents=coins_inserted_cents,
        payment_complete=payment_complete,
    )


def get_parking_ui_state(
    meter: SSHMeter,
    timeout: float = 3.0,
    shared: SharedState = None,
    debug_ui: bool = False,
) -> ParkingUIState:
    """
    Classify the current pay-to-park page into a simplified UI state.

    This is intentionally heuristic-based. Different meter regions, meter
    types, firmware revisions, and customizations can show slightly different
    HTML/text for the same logical step, so the classifier relies on a mix of
    title codes and stable phrases instead of exact page templates.
    """

    html = meter.get_ui_page_html(timeout=timeout)
    meter_region = _normalize_meter_region(getattr(meter, "meter_region", ""))
    log = None
    if shared or debug_ui:
        log = lambda message: _debug_log(shared, meter, debug_ui, message)
    return classify_parking_ui_html(html, meter_region=meter_region, log=log)


def resolve_payment_type(meter: SSHMeter, requested: PaymentType, shared: SharedState = None) -> PaymentType:
    """
    Resolve the caller-requested payment mode into the actual mode to use.

    Today `AUTO` intentionally defaults to coins. If future revisions broaden
    that behavior, keep the fallback choice explicit and easy to trace in logs.
    """

    if requested == PaymentType.AUTO:
        return PaymentType.COINS

    if requested in {
        PaymentType.COINS,
        PaymentType.CONTACT_CREDIT_CARD,
        PaymentType.ROBOT_CONTACTLESS,
    }:
        return requested

    raise RuntimeError(f"Requested payment type '{requested.name}' is not available on this meter")


def reset_to_parking_home(
    meter: SSHMeter,
    shared: SharedState = None,
    timeout_s: float = 10.0,
    debug_ui: bool = False,
) -> ParkingUIState:
    """
    Return the meter to the pay-to-park home page before starting a new session.

    This matters because the meter will resume an in-progress parking session
    after leaving diagnostics, so each cycle should start from a clean home
    screen rather than assuming the prior session already ended.
    """

    deadline = time.time() + timeout_s
    last_signature = None

    while time.time() < deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter, shared=shared, debug_ui=debug_ui)
        signature = (state.summary, state.snippet)

        if signature != last_signature:
            _debug_log(
                shared,
                meter,
                debug_ui,
                f"reset page -> {state.summary} | text={state.snippet}",
            )
            last_signature = signature

        if state.kind == "out_of_order":
            _debug_log(shared, meter, debug_ui, "reset abort -> meter is showing out-of-order")
            raise RuntimeError("Meter is showing an out-of-order screen")

        if state.kind == "home":
            _debug_log(shared, meter, debug_ui, "reset complete -> reached pay-to-park home")
            return state

        if state.kind == "diagnostics":
            _debug_log(
                shared,
                meter,
                debug_ui,
                "reset action -> kind=press | detail=exit diagnostics | button=diagnostics | delay=0.80s",
            )
            meter.press("diagnostics", delay=0.8)
        else:
            _debug_log(
                shared,
                meter,
                debug_ui,
                "reset action -> kind=press | detail=cancel active parking session | button=cancel | delay=0.80s",
            )
            meter.press("cancel", delay=0.8)

        time.sleep(0.4)

    raise TimeoutError("Timed out trying to return the meter to the pay-to-park home screen")


def _select_coin_value(amount_due_cents: Optional[int], meter_region: str = "us") -> int:
    supported_values = _supported_coin_values(meter_region)
    due = amount_due_cents if amount_due_cents is not None else supported_values[-1]

    for value in supported_values:
        if due >= value:
            return value
    return supported_values[-1]


def _log_ui_transition(shared: SharedState, meter: SSHMeter, state: ParkingUIState) -> None:
    if shared:
        shared.log(f"{meter.host} screen test ui -> {state.summary}")


def _build_pay_session_result(context: PaySessionContext, card_last4: Optional[str]) -> dict[str, Any]:
    """
    Build the small session summary shared by both success and failure paths.

    Keeping this shape centralized avoids subtle drift between the normal return
    path and the failure path that raises `PayToParkSessionError`.
    """
    return {
        "requested_payment_type": context.requested_payment_type.name,
        "effective_payment_type": context.effective_payment_type.name,
        "card_last4": card_last4,
    }


def _store_cycle_meter_ui_meta(
    shared: SharedState,
    run_number: int,
    session_result: Optional[dict[str, Any]],
) -> None:
    """
    Persist per-run card metadata for the outer `job_count` loop.

    The caller owns the run number, so we store the session's `card_last4`
    here instead of inside `run_pay_to_park_session()`. This helper is used for
    both successful runs and failures that surface a `session_result` payload.
    """
    if not shared or not session_result:
        return
    if session_result.get("effective_payment_type", "") == PaymentType.COINS.name:
        return

    card_meta = shared.device_meta.setdefault("nfc_gui_cards", {})
    card_meta[str(run_number)] = session_result.get("card_last4")


def _debug_log(shared: SharedState, meter: SSHMeter, debug_ui: bool, message: str) -> None:
    if shared:
        shared.log(message)

    if debug_ui:
        print(f"\n{message}")


def _wait_for_q_press(
    meter: SSHMeter,
    shared: SharedState = None,
    debug_ui: bool = False,
    poll_seconds: float = 0.25,
) -> None:
    """
    Local/manual debug gate used to pause a run until the operator presses `q`.

    This helper exists for interactive troubleshooting from a Windows console.
    It is not intended for production or unattended automation flows.
    """

    if msvcrt is None:
        raise RuntimeError("wait_for_q_press is only supported when running from a Windows console")

    message = f"{meter.host} screen test wait_for_q_press enabled. Press 'q' to continue."
    if shared:
        shared.log(message)
    if debug_ui:
        print(f"\n{message}")

    while True:
        check_stop_event(shared)

        if msvcrt.kbhit():
            key = msvcrt.getwch().lower()
            if key == "q":
                if shared:
                    shared.log(f"{meter.host} screen test detected 'q'; resuming cycle_all")
                if debug_ui:
                    print(f"\n{meter.host} screen test detected 'q'; resuming cycle_all")
                return

        time.sleep(poll_seconds)


def _format_pay_ui_action(action: PayUIAction) -> str:
    parts = [f"kind={action.kind}", f"detail={action.detail}"]
    if action.button:
        parts.append(f"button={action.button}")
    if action.coin_value is not None:
        parts.append(f"coin={action.coin_value}")
    if action.card_value:
        parts.append(f"card={action.card_value}")
    if action.robot_program:
        parts.append(f"robot_program={action.robot_program}")
    parts.append(f"delay={action.delay:.2f}s")
    return " | ".join(parts)


def _cleanup_to_parking_home(
    meter: SSHMeter,
    shared: SharedState = None,
    max_cancels: int = 3,
) -> str:
    last_kind = ""

    for attempt in range(max_cancels + 1):
        state = get_parking_ui_state(meter, shared=shared)
        last_kind = state.kind

        if shared:
            shared.log(
                f"{meter.host} screen test cleanup state -> {state.summary} "
                f"(attempt {attempt}/{max_cancels})"
            )

        if state.kind in {"home", "diagnostics"}:
            return state.kind

        if attempt >= max_cancels:
            break

        if shared:
            shared.log(
                f"{meter.host} screen test cleanup -> press cancel "
                f"({attempt + 1}/{max_cancels})"
            )
        meter.press("cancel", delay=0.25)

    return last_kind


def _card_value() -> str:
    return "Contact Credit Card"


def _build_card_payment_action(context: PaySessionContext, detail: str) -> PayUIAction:
    """Map card-style payment modes to the concrete action the executor runs."""

    if context.effective_payment_type == PaymentType.ROBOT_CONTACTLESS:
        return PayUIAction(
            "run_robot_card",
            detail,
            robot_program="run_nfc_card",
            delay=1.0,
        )

    return PayUIAction(
        "send_card",
        detail,
        card_value=_card_value(),
        delay=1.0,
    )


def _uses_direct_card_from_payment_amount(meter: SSHMeter) -> bool:
    b = meter.meter_type in {"msx", "ms2.5"}
    return b


def _requires_robot_nfc_payment_amount_accept(meter: SSHMeter, context: PaySessionContext) -> bool:
    return (
        meter.meter_type == "ms2.5"
        and context.effective_payment_type == PaymentType.ROBOT_CONTACTLESS
    )


def _switch_to_coin_fallback(context: PaySessionContext, shared: SharedState, meter: SSHMeter, reason: str) -> None:
    context.effective_payment_type = PaymentType.COINS
    context.card_sent = False
    context.card_read_waits = 0
    context.payment_amount_accepted = False
    context.payment_entry_attempts = 0
    context.payment_method_selected = False
    context.card_prompt_started = False
    context.fallback_to_coins_used = True
    if shared:
        shared.log(f"switching to coin payment: {reason}")


def _default_duration_plus_target(meter: SSHMeter) -> int:
    if _meter_region(meter) == "uk":
        return random.randint(1, 6)
    return random.randint(3, 10)


def plan_pay_ui_action(
    meter: SSHMeter,
    state: ParkingUIState,
    context: PaySessionContext,
    shared: SharedState = None,
) -> PayUIAction:
    """
    Convert the current classified page into the next action to perform.

    The planner is the main compatibility layer for meter-to-meter UI variation.
    When future versions add/rename pages, this is usually the first place that
    should be updated.
    """

    if state.kind not in {"home", "diagnostics", "language"}:
        context.has_left_home = True

    if state.kind != "payment_card_read":
        context.card_read_waits = 0

    if state.kind != "other":
        context.unknown_count = 0

    meter_region = _meter_region(meter)

    if state.kind == "diagnostics":
        return PayUIAction("press", "exit diagnostics", button="diagnostics", delay=0.8)

    if state.kind == "out_of_order":
        return PayUIAction("fail", "Meter is showing an out-of-order screen")

    if state.kind == "language":
        return PayUIAction("press", "leave language page", button="cancel", delay=0.8)

    if state.kind == "home":
        if context.has_left_home and not context.saw_success:
            if context.retry_count >= context.max_retries:
                return PayUIAction("fail", "Meter returned to the home screen before completing payment")
            context.retry_count += 1
            context.reset_for_retry()
            if shared:
                shared.log(f"screen test retrying after unexpected return to home")

        safe_buttons = ["cancel", "ok"]
        if meter_region == "uk":
            safe_buttons = ["ok", "cancel"]
        index = min(context.home_start_attempts, len(safe_buttons) - 1)
        button = safe_buttons[index]
        context.home_start_attempts += 1
        return PayUIAction("press", f"start session with {button}", button=button, delay=0.8)

    if state.kind == "plate_entry":
        current_plate = re.sub(r"[^A-Z0-9]", "", state.plate_value.upper())
        target_plate = context.plate

        if current_plate and (len(current_plate) > len(target_plate) or not target_plate.startswith(current_plate)):
            return PayUIAction("press", "clear plate character", button="back", delay=0.5)

        if len(current_plate) < len(target_plate):
            return PayUIAction(
                "press",
                f"type plate character {target_plate[len(current_plate)]}",
                button=target_plate[len(current_plate)],
                delay=0.25,
            )

        return PayUIAction("press", "submit plate", button="enter", delay=0.8)

    if state.kind == "duration_select":
        if context.duration_plus_target is None:
            context.duration_plus_target = _default_duration_plus_target(meter)
            context.duration_plus_presses = 0

        if context.duration_plus_presses < context.duration_plus_target:
            context.duration_plus_presses += 1
            return PayUIAction(
                "press",
                f"increase parking time {context.duration_plus_presses}/{context.duration_plus_target}",
                button="plus",
                delay=0.25,
            )

        context.duration_confirm_attempts += 1
        return PayUIAction(
            "press",
            f"confirm parking duration after {context.duration_plus_presses} plus presses",
            button="enter",
            delay=0.8,
        )

    if state.kind == "payment_amount":
        if context.effective_payment_type == PaymentType.COINS:
            due_cents = state.amount_due_cents
            if meter_region == "uk":
                due_cents = due_cents if due_cents is not None else state.cost_cents
                if state.payment_complete or (due_cents is not None and due_cents <= 0):
                    if not context.payment_amount_accepted:
                        context.payment_amount_accepted = True
                        return PayUIAction(
                            "press",
                            "confirm fully paid coin transaction",
                            button="enter",
                            delay=0.8,
                        )
                    return PayUIAction("wait", "waiting for coin-paid transaction to print", delay=1.0)

            coin_value = _select_coin_value(due_cents or state.cost_cents, meter_region=meter_region)
            return PayUIAction("insert_coin", f"insert {coin_value} cents", coin_value=coin_value, delay=0.6)

        if meter_region == "uk":
            if not context.payment_method_selected:
                context.payment_method_selected = True
                return PayUIAction("press", "select card payment method", button="plus", delay=0.8)
            return PayUIAction("wait", "waiting for the UK card payment page", delay=1.0)

        if _requires_robot_nfc_payment_amount_accept(meter, context):
            if not context.payment_amount_accepted:
                context.payment_amount_accepted = True
                return PayUIAction(
                    "press",
                    "accept ms2.5 payment amount before NFC prompt",
                    button="enter",
                    delay=1.0,
                )
            return PayUIAction("wait", "waiting for ms2.5 NFC prompt after accepting payment amount", delay=1.0)

        if _uses_direct_card_from_payment_amount(meter):
            if not context.card_sent:
                context.card_sent = True
                return _build_card_payment_action(
                    context,
                    "send payment card from payment amount screen",
                )

            return PayUIAction("wait", "waiting for card confirmation screen", delay=1.0)

        if not context.payment_amount_accepted:
            context.payment_amount_accepted = True
            return PayUIAction("press", "accept payment amount before EMV prompt", button="enter", delay=1.0)

        return PayUIAction("wait", "waiting for EMV prompt after accepting payment amount", delay=1.0)

    if state.kind == "payment_confirm":
        if not context.payment_confirm_accepted:
            context.payment_confirm_accepted = True
            return PayUIAction("press", "confirm payment amount", button="enter", delay=1.0)
        return PayUIAction("wait", "waiting for confirmed payment flow to advance", delay=1.0)

    if state.kind == "payment_card_start":
        if not context.card_prompt_started:
            context.card_prompt_started = True
            return PayUIAction("press", "open the EMV card prompt", button="plus", delay=1.0)
        return PayUIAction("wait", "waiting for the EMV prompt to become ready", delay=1.0)

    if state.kind == "payment_card_ready":
        if not context.card_sent:
            context.card_sent = True
            return _build_card_payment_action(context, "send payment card from EMV prompt")

        return PayUIAction("wait", "waiting for card to be read", delay=1.0)

    if state.kind == "payment_card_read":
        return PayUIAction("wait", "waiting for post-card processing or confirmation page", delay=1.0)

    if state.kind == "payment_loading":
        return PayUIAction("wait", "waiting for payment flow to advance", delay=1.0)

    if state.kind == "payment_error":
        context.error_count += 1
        if context.allow_coin_fallback and context.effective_payment_type != PaymentType.COINS:
            _switch_to_coin_fallback(context, shared, meter, "card payment failed")
            return PayUIAction("wait", "waiting for card error page to clear", delay=1.5)

        if context.retry_count < context.max_retries:
            context.retry_count += 1
            context.reset_for_retry()
            return PayUIAction("press", "cancel failed payment session", button="cancel", delay=0.9)

        return PayUIAction("fail", "Payment failed and no recovery path remains")

    if state.kind == "success":
        context.saw_success = True
        return PayUIAction("done", "transaction completed")

    context.unknown_count += 1
    if context.unknown_count >= 4:
        return PayUIAction(
            "fail",
            f"Unknown UI page persisted: title={state.title or '<none>'} | "
            f"region={state.region or '<none>'} | text={state.text[:200]}",
        )
    return PayUIAction("wait", "waiting for unknown page to resolve", delay=0.8)


def execute_pay_ui_action(
    meter: SSHMeter,
    shared: SharedState,
    action: PayUIAction,
    context: PaySessionContext,
    debug_ui: bool = False,
    robot_ready_timeout: float = 20.0,
) -> None:
    """
    Execute a single planned action against the meter or robot.

    Keep this function focused on execution only. Page interpretation belongs in
    `get_parking_ui_state`, and decision-making belongs in `plan_pay_ui_action`.
    """

    if action.kind == "press":
        _debug_log(shared, meter, debug_ui, f">> meter.press({action.button}, delay={action.delay})")
        meter.press(action.button, delay=action.delay)
    elif action.kind == "insert_coin":
        _debug_log(shared, meter, debug_ui, f">> meter.insert_coin({action.coin_value}, delay={action.delay})")
        meter.insert_coin(action.coin_value, delay=action.delay)
    elif action.kind == "send_card":
        _debug_log(shared, meter, debug_ui, f">> time.sleep({PRE_CARD_SEND_DELAY_S})")
        time.sleep(PRE_CARD_SEND_DELAY_S)
        _debug_log(shared, meter, debug_ui, f'>> meter.custom_busdev("CONTACT", {action.card_value}, delay={action.delay})')
        meter.custom_busdev("CONTACT", action.card_value, delay=action.delay)
    elif action.kind == "run_robot_card":
        if context.robot is None:
            raise RuntimeError("robot_contactless payment requested without an initialized RobotClient")
        ## time.sleep(PRE_CARD_SEND_DELAY_S) # skip bc the robot will take a few seconds to move into position, so we can start the card action req immediately
        context.robot.wait_until_ready(robot_ready_timeout)
        context.robot.flush_event_queue()
        job_args = {
            "meter_type": meter.meter_type,
            "meter_id": meter.hostname,
            "charuco_frame": context.charuco_frame,
            "config_idx": "nfc_gui"
        }
        _debug_log(shared, meter, debug_ui, f'>> robot.run_program("{action.robot_program}", {job_args})')
        job_id = context.robot.run_program(action.robot_program, job_args)
        if not job_id:
            raise RuntimeError(f"Robot did not accept program '{action.robot_program}'")
        context.robot_payment_job_id = job_id
    elif action.kind == "wait":
        _debug_log(shared, meter, debug_ui, f">> time.sleep({action.delay})")
        time.sleep(action.delay)
    elif action.kind in {"done", "fail"}:
        return
    else:
        raise ValueError(f"Unknown pay UI action: {action.kind}")


def run_pay_to_park_session(
    meter: SSHMeter,
    shared: SharedState = None,
    payment_type: PaymentType = PaymentType.AUTO,
    allow_coin_fallback: bool = False,
    timeout_s: float = 90.0,
    debug_ui: bool = True,
    robot: Optional[RobotClient] = None,
    charuco_frame: Any = None,
    robot_ready_timeout: float = 20.0,
) -> dict:
    """
    Run one full pay-to-park attempt from home page to success/failure.

    On success this returns a small summary dict, including the effective
    payment type and any card `last4` extracted from journal logs.

    On failure this raises `PayToParkSessionError` after collecting the same
    summary payload. The caller uses that attached `session_result` to record
    metadata for the current `job_count` iteration before re-raising and stopping
    further screen-test runs.
    """

    meter.set_ui_mode("banner")
    reset_to_parking_home(meter, shared=shared, debug_ui=debug_ui)
    cycle_journal_since = _journal_since_now(meter)

    effective_payment_type = resolve_payment_type(meter, payment_type, shared=shared)
    context = PaySessionContext(
        requested_payment_type=payment_type,
        effective_payment_type=effective_payment_type,
        plate=random_plate(),
        allow_coin_fallback=allow_coin_fallback,
        card_journal_since=cycle_journal_since,
        robot=robot,
        charuco_frame=charuco_frame,
    )

    if shared:
        shared.log(
            f"{meter.host} screen test using payment_type={context.effective_payment_type.name} "
            f"plate={context.plate}"
        )
    _debug_log(
        shared,
        meter,
        debug_ui,
        "context -> "
        f"requested={context.requested_payment_type.name} | "
        f"effective={context.effective_payment_type.name} | "
        f"plate={context.plate} | "
        f"allow_coin_fallback={context.allow_coin_fallback}",
    )

    deadline = time.time() + timeout_s
    last_summary = ""
    last_debug_signature = None
    failure_detail = ""

    while time.time() < deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter, shared=shared, debug_ui=debug_ui)
        debug_signature = (state.summary, state.snippet)

        if state.summary != last_summary:
            _log_ui_transition(shared, meter, state)
            last_summary = state.summary
        if debug_signature != last_debug_signature:
            _debug_log(shared, meter, debug_ui, f"page -> {state.summary} | text={state.snippet}")
            last_debug_signature = debug_signature

        action = plan_pay_ui_action(meter, state, context, shared=shared)
        _debug_log(
            shared,
            meter,
            debug_ui,
            "action -> "
            f"{_format_pay_ui_action(action)} | "
            f"retries={context.retry_count}/{context.max_retries} | "
            f"unknowns={context.unknown_count} | "
            f"card_sent={context.card_sent} | "
            f"fallback_to_coins={context.fallback_to_coins_used}",
        )
        if action.kind == "fail":
            failure_detail = action.detail
            break
        if action.kind == "done":
            break

        if action.kind in {"send_card", "run_robot_card"} and context.card_journal_since == cycle_journal_since:
            context.card_journal_since = _journal_since_now(meter)
            _debug_log(shared, meter, debug_ui, f"card journal window -> since {context.card_journal_since}")

        execute_pay_ui_action(
            meter,
            shared,
            action,
            context,
            debug_ui=debug_ui,
            robot_ready_timeout=robot_ready_timeout,
        )

    else:
        raise TimeoutError("Timed out while trying to complete the pay-to-park flow")

    card_last4 = None
    if context.effective_payment_type != PaymentType.COINS:
        try:
            if failure_detail:
                # Declined flows can emit EMV_TRANS_RESULT a few seconds after the
                # UI already shows the failure page, so give the journal one brief
                # settle window before reading it once.
                time.sleep(4.0)
            card_last4 = _get_latest_card_last4(
                meter,
                context.card_journal_since or cycle_journal_since,
            )
        except Exception as exc:
            if shared:
                shared.log(f"screen test warning: failed to read card last4 from journalctl | {exc}")
        else:
            if shared:
                shared.log(
                    f"screen test card last4 -> {card_last4!r} "
                    f"(payment_type={context.effective_payment_type.name}, since={context.card_journal_since or cycle_journal_since})"
                )

    session_result = _build_pay_session_result(context, card_last4)
    if failure_detail:
        raise PayToParkSessionError(failure_detail, session_result=session_result)

    # Future reference: the UI can hit success here and still fall into
    # Out Of Order a few seconds later if receipt printing stays PENDING long
    # enough to trigger UXAppSetPrintResult(... false) / Fault PRINTER, which
    # then flips PAYANDDISPLAY to isCanPrint=false. If we need to catch the
    # cause in the same run, this post-success window is the place to watch it.
    # Helpful references:
    # - run_pay_to_park_session() / reset_to_parking_home()
    # - flask/logs/2026-04-27/13-56-00_30004201_physical_cycle_all.log
    # - flask/logs/2026-04-27/14-41-07_30004201_cycle_all.log
    # - flask/logs/2026-04-27/14-54-08_30004201_cycle_all.log
    # - flask/logs/2026-04-27/14-58-34_30004201_physical_cycle_all.log
    # - flask/logs/2026-04-27/14-58-34_30004201_out_of_order_page.log
    post_success_deadline = time.time() + (8.0 if meter.device_firmware("printer") else 4.0)
    last_post_success_signature = None
    while time.time() < post_success_deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter, shared=shared, debug_ui=debug_ui)
        post_success_signature = (state.summary, state.snippet)
        if post_success_signature != last_post_success_signature:
            _debug_log(shared, meter, debug_ui, f"post-success page -> {state.summary} | text={state.snippet}")
            last_post_success_signature = post_success_signature
        if state.kind == "home":
            return session_result
        time.sleep(0.5)

    return session_result


def test_cycle_meter_ui(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """
    Public test entrypoint used by both `cycle_all` and `physical_cycle_all`.

    Expected kwargs commonly include:
    - `job_count`
    - `payment_type`
    - `allow_coin_fallback`
    - `debug_ui`
    - `timeout_s`
    - `robot_ready_timeout`
    - `charuco_frame` for robot-assisted physical runs
    - `wait_for_q_press` for local/manual debugging only

    This function intentionally keeps the reusable screen-test behavior in one
    place so future monitor combinations can share the same UI logic.

    Important behavior:
    - a single failed session stops the remaining `job_count` iterations,
    - but any session metadata already collected for that iteration should still
      be written to `shared.device_meta`,
    - so the outer loop records metadata from either a normal `session_result`
      return or from `PayToParkSessionError.session_result` before cleanup and
      re-raising the failure.
    """

    func_name = inspect.currentframe().f_code.co_name
    payment_type = kwargs.get("payment_type", "auto")
    allow_coin_fallback = _coerce_bool(kwargs.get("allow_coin_fallback", False))
    wait_for_q_press = _coerce_bool(kwargs.get("wait_for_q_press", False))
    job_count = int(kwargs.get("job_count", 1))
    timeout_s = float(kwargs.get("timeout_s", 60))
    debug_ui = _coerce_bool(kwargs.get("debug_ui", False))
    robot_ready_timeout = float(kwargs.get("robot_ready_timeout", 20.0))
    subtest = _coerce_bool(kwargs.get("subtest", False))

    try:
        payment_type = _parse_payment_type(payment_type)
    except (KeyError, AttributeError):
        payment_type = PaymentType.AUTO

    robot = None
    if payment_type == PaymentType.ROBOT_CONTACTLESS:
        robot = RobotClient()
        robot.wait_until_ready(robot_ready_timeout)
        # robot.flush_event_queue()
    
    should_clear_coin_tallies = payment_type in {PaymentType.AUTO, PaymentType.COINS}

    for i in range(job_count):
        cycle_num = i + 1
        if shared:
            shared.log(f"{meter.host} {func_name} {cycle_num}/{job_count} kwargs: {kwargs}")
            if not subtest:
                shared.broadcast_progress(meter.host, "cycle_ui", cycle_num, job_count)

        if meter.meter_type == "ms3":
            if shared:
                shared.log("Toggle printer OFF and back ON to avoid a jam")
            meter.reboot_printer()

        if wait_for_q_press:
            _wait_for_q_press(meter, shared=shared, debug_ui=debug_ui)
            check_stop_event(shared)
            continue

        try:
            session_result = run_pay_to_park_session(
                meter,
                shared=shared,
                payment_type=payment_type,
                allow_coin_fallback=allow_coin_fallback,
                timeout_s=timeout_s,
                debug_ui=debug_ui,
                robot=robot,
                charuco_frame=kwargs.get("charuco_frame"),
                robot_ready_timeout=robot_ready_timeout,
            )
        except Exception as exc:
            _store_cycle_meter_ui_meta(shared, i + 1, getattr(exc, "session_result", None))
            try:
                if not meter.in_diagnostics():
                    cleanup_kind = _cleanup_to_parking_home(meter, shared=shared, max_cancels=3)
                    if shared:
                        shared.log(f"{meter.host} screen test cleanup result -> {cleanup_kind or 'unknown'}")
            except Exception as cleanup_exc:
                if shared:
                    shared.log(f"{meter.host} screen test cleanup warning: failed to cancel active session | {cleanup_exc}")
            if should_clear_coin_tallies:
                _clear_screen_test_coin_tallies(
                    meter,
                    shared,
                    reason=f"exception during cycle {cycle_num}/{job_count}",
                )
            raise

        if session_result.get("effective_payment_type", "") == PaymentType.COINS.name:
            should_clear_coin_tallies = True

        _store_cycle_meter_ui_meta(shared, cycle_num, session_result)

        check_stop_event(shared)

    time.sleep(1)
    if should_clear_coin_tallies:
        _clear_screen_test_coin_tallies(
            meter,
            shared,
            reason=f"completed {job_count}/{job_count} cycles",
        )

    time.sleep(1)
    if not meter.in_diagnostics():
        meter.press("diagnostics")

    #! Excpect the modem to be left ON after this test finishes. The meter's session agent will eventually turn it off
