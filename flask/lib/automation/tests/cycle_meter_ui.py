from dataclasses import dataclass
from enum import Enum
from html import unescape
from typing import Any, Optional
import inspect
import random
import re
import string
import time

from lib.automation.helpers import check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter
from lib.robot.robot_client import RobotClient


TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TITLE_RE = re.compile(r"<title>\s*([^<]+)\s*</title>", re.I)
VALUEBOX_RE = re.compile(r"<div class=valuebox>(.*?)</div>", re.I | re.S)
MONEY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]{1,2})?)")
CARD_MASKED_RE = re.compile(r"Card read:\s*([Xx*\d ]+)", re.I)
PAN_MASKED_RE = re.compile(r"\bPAN\s+([Xx*\d ]{4,})", re.I)
CARD_REF_RE = re.compile(r"refStr=(\d{4})", re.I)
HEX_BYTE_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")
PAN_FROM_TRACK_RE = re.compile(r"(\d{12,19})(?=[=^D])")
LONG_CARD_RE = re.compile(r"(?<!\d)(\d{12,19})(?!\d)")
PRE_CARD_SEND_DELAY_S = 4.0


class PaymentType(Enum):
    AUTO = 0
    COINS = 1
    CONTACT_CREDIT_CARD = 2
    ROBOT_CONTACTLESS = 3


@dataclass
class ParkingUIState:
    kind: str
    title: str
    html: str
    text: str
    plate_value: str = ""
    cost_cents: Optional[int] = None
    amount_due_cents: Optional[int] = None

    @property
    def summary(self) -> str:
        parts = [self.kind]
        if self.title:
            parts.append(f"title={self.title}")
        if self.plate_value:
            parts.append(f"plate={self.plate_value}")
        if self.cost_cents is not None:
            parts.append(f"cost={self.cost_cents}")
        if self.amount_due_cents is not None:
            parts.append(f"due={self.amount_due_cents}")
        return " ".join(parts)

    @property
    def snippet(self) -> str:
        if len(self.text) <= 220:
            return self.text
        return self.text[:217] + "..."


@dataclass
class PaySessionContext:
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
        self.card_sent = False
        self.robot_payment_job_id = None
        self.card_read_waits = 0
        self.unknown_count = 0


@dataclass
class PayUIAction:
    kind: str
    detail: str
    button: str = ""
    coin_value: Optional[int] = None
    card_value: str = ""
    robot_program: str = ""
    delay: float = 0.6


def random_plate(length: int = 7) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


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

    masked_match = CARD_MASKED_RE.search(line) or PAN_MASKED_RE.search(line)
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
    cmd = (
        f"journalctl -u MS3_Platform.service --since \"{since}\" -n 800 --no-pager | "
        "grep -E 'CARD_READ_DATA|refStr=|Card read:|receiptText=|PAN [Xx*0-9 ]+' | tail -n 60"
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
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def _title_code(html: str) -> str:
    match = TITLE_RE.search(html)
    return match.group(1).strip().lower() if match else ""


def _parse_money_cents(value: str) -> Optional[int]:
    match = MONEY_RE.search(value)
    if not match:
        return None
    return int(round(float(match.group(1)) * 100))


def _money_after(label: str, text: str) -> Optional[int]:
    match = re.search(rf"{label}\s*:\s*\$([0-9]+(?:\.[0-9]{{1,2}})?)", text, re.I)
    if not match:
        return None
    return int(round(float(match.group(1)) * 100))


def _parse_plate_value(html: str) -> str:
    match = VALUEBOX_RE.search(html)
    return _strip_html(match.group(1)) if match else ""


def get_parking_ui_state(meter: SSHMeter, timeout: float = 3.0) -> ParkingUIState:
    html = meter.get_ui_page_html(timeout=timeout)
    text = _strip_html(html)
    text_lower = text.lower()
    title = _title_code(html)
    cost_cents = _money_after("cost", text)
    amount_due_cents = _money_after("amount due", text)
    plate_value = ""

    if "diagtitle" in html.lower() or "diagcontent" in html.lower():
        kind = "diagnostics"
    elif "out of order" in text_lower:
        kind = "out_of_order"
    elif "available languages" in text_lower or "select language" in text_lower or title == "64":
        kind = "language"
    elif "payment required" in text_lower or "press any key to start" in text_lower or title == "00":
        kind = "home"
    elif "enter your plate number below" in text_lower or "plate #" in text_lower or title == "09":
        kind = "plate_entry"
        plate_value = _parse_plate_value(html)
    elif "select parking duration" in text_lower or (
        title == "12" and "parking duration" in text_lower
    ):
        kind = "duration_select"
    elif "credit card confirmation" in text_lower or "confirm $" in text_lower or title == "99":
        kind = "payment_confirm"
    elif "credit card not accepted" in text_lower or "declined" in text_lower or title == "69":
        kind = "payment_error"
    elif "please tap or insert/remove card" in text_lower:
        kind = "payment_card_ready"
    elif "card read ok, remove card" in text_lower:
        kind = "payment_card_read"
    elif "authorizing" in text_lower or "please wait" in text_lower or (
        "emv" in text_lower and "welcome" in text_lower
    ) or title in {"24", "74", "nn"}:
        kind = "payment_loading"
    elif "accepting payment" in text_lower or "amount due" in text_lower:
        kind = "payment_amount"
    elif "approved" in text_lower or "transaction complete" in text_lower or "thank you" in text_lower or title == "23":
        kind = "success"
    else:
        kind = "other"

    return ParkingUIState(
        kind=kind,
        title=title,
        html=html,
        text=text,
        plate_value=plate_value,
        cost_cents=cost_cents,
        amount_due_cents=amount_due_cents,
    )


def resolve_payment_type(meter: SSHMeter, requested: PaymentType, shared: SharedState = None) -> PaymentType:
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
    deadline = time.time() + timeout_s
    last_signature = None

    while time.time() < deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter)
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


def _select_coin_value(amount_due_cents: Optional[int]) -> int:
    due = amount_due_cents if amount_due_cents is not None else 25
    for value in (100, 25, 10, 5, 1):
        if due >= value:
            return value
    return 25


def _log_ui_transition(shared: SharedState, meter: SSHMeter, state: ParkingUIState) -> None:
    if shared:
        shared.log(f"{meter.host} screen test ui -> {state.summary}")


def _debug_log(shared: SharedState, meter: SSHMeter, debug_ui: bool, message: str) -> None:
    if shared:
        shared.log(message)

    if debug_ui:
        print(f"\n{message}")


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
        state = get_parking_ui_state(meter)
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
    print(f"_uses_direct_card_from_payment_amount -> {b}, meter_type={meter.meter_type}")
    return b


def _switch_to_coin_fallback(context: PaySessionContext, shared: SharedState, meter: SSHMeter, reason: str) -> None:
    context.effective_payment_type = PaymentType.COINS
    context.card_sent = False
    context.card_read_waits = 0
    context.payment_amount_accepted = False
    context.payment_entry_attempts = 0
    context.fallback_to_coins_used = True
    if shared:
        shared.log(f"switching to coin payment: {reason}")


def plan_pay_ui_action(
    meter: SSHMeter,
    state: ParkingUIState,
    context: PaySessionContext,
    shared: SharedState = None,
) -> PayUIAction:
    if state.kind not in {"home", "diagnostics", "language"}:
        context.has_left_home = True

    if state.kind != "payment_card_read":
        context.card_read_waits = 0

    if state.kind != "other":
        context.unknown_count = 0

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
            context.duration_plus_target = random.randint(3, 10)
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
            coin_value = _select_coin_value(state.amount_due_cents or state.cost_cents)
            return PayUIAction("insert_coin", f"insert {coin_value} cents", coin_value=coin_value, delay=0.6)

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
        return PayUIAction("fail", f"Unknown UI page persisted: {state.text[:200]}")
    return PayUIAction("wait", "waiting for unknown page to resolve", delay=0.8)


def execute_pay_ui_action(
    meter: SSHMeter,
    action: PayUIAction,
    context: PaySessionContext,
    robot_ready_timeout: float = 20.0,
) -> None:
    if action.kind == "press":
        print(f">> meter.press({action.button}, delay={action.delay})")
        meter.press(action.button, delay=action.delay)
    elif action.kind == "insert_coin":
        print(f">> meter.insert_coin({action.coin_value}, delay={action.delay})")
        meter.insert_coin(action.coin_value, delay=action.delay)
    elif action.kind == "send_card":
        print(f">> time.sleep({PRE_CARD_SEND_DELAY_S})")
        time.sleep(PRE_CARD_SEND_DELAY_S)
        print(f'>> meter.custom_busdev("CONTACT", {action.card_value}, delay={action.delay})')
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
        print(f'>> robot.run_program("{action.robot_program}", {job_args})')
        job_id = context.robot.run_program(action.robot_program, job_args)
        if not job_id:
            raise RuntimeError(f"Robot did not accept program '{action.robot_program}'")
        context.robot_payment_job_id = job_id
    elif action.kind == "wait":
        print(f">> time.sleep({action.delay})")
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

    while time.time() < deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter)
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
            raise RuntimeError(action.detail)
        if action.kind == "done":
            break

        if action.kind in {"send_card", "run_robot_card"} and context.card_journal_since == cycle_journal_since:
            context.card_journal_since = _journal_since_now(meter)
            _debug_log(shared, meter, debug_ui, f"card journal window -> since {context.card_journal_since}")

        execute_pay_ui_action(
            meter,
            action,
            context,
            robot_ready_timeout=robot_ready_timeout,
        )

    else:
        raise TimeoutError("Timed out while trying to complete the pay-to-park flow")

    card_last4 = None
    if context.saw_success and context.effective_payment_type != PaymentType.COINS:
        try:
            card_last4 = _get_latest_card_last4(meter, context.card_journal_since or cycle_journal_since)
        except Exception as exc:
            if shared:
                shared.log(f"screen test warning: failed to read card last4 from journalctl | {exc}")
        else:
            if shared:
                shared.log(
                    f"screen test card last4 -> {card_last4!r} "
                    f"(payment_type={context.effective_payment_type.name}, since={context.card_journal_since or cycle_journal_since})"
                )

    post_success_deadline = time.time() + (8.0 if meter.device_firmware("printer") else 4.0)
    last_post_success_signature = None
    while time.time() < post_success_deadline:
        check_stop_event(shared)
        state = get_parking_ui_state(meter)
        post_success_signature = (state.summary, state.snippet)
        if post_success_signature != last_post_success_signature:
            _debug_log(shared, meter, debug_ui, f"post-success page -> {state.summary} | text={state.snippet}")
            last_post_success_signature = post_success_signature
        if state.kind == "home":
            return {
                "requested_payment_type": context.requested_payment_type.name,
                "effective_payment_type": context.effective_payment_type.name,
                "card_last4": card_last4,
            }
        time.sleep(0.5)

    return {
        "requested_payment_type": context.requested_payment_type.name,
        "effective_payment_type": context.effective_payment_type.name,
        "card_last4": card_last4,
    }


def test_cycle_meter_ui(meter: SSHMeter, shared: SharedState = None, **kwargs):
    func_name = inspect.currentframe().f_code.co_name
    payment_type = kwargs.get("payment_type", "auto")
    allow_coin_fallback = _coerce_bool(kwargs.get("allow_coin_fallback", False))
    count = int(kwargs.get("count", 1))
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

    for i in range(count):
        if shared:
            shared.log(f"{meter.host} {func_name} {i + 1}/{count}")
            if not subtest:
                shared.broadcast_progress(meter.host, "cycle_ui", i + 1, count)

        if meter.meter_type == "ms3":
            if shared:
                shared.log("Toggle printer OFF and back ON to avoid a jam")
            meter.reboot_printer()

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
        except Exception:
            try:
                if not meter.in_diagnostics():
                    cleanup_kind = _cleanup_to_parking_home(meter, shared=shared, max_cancels=3)
                    if shared:
                        shared.log(f"{meter.host} screen test cleanup result -> {cleanup_kind or 'unknown'}")
            except Exception as cleanup_exc:
                if shared:
                    shared.log(f"{meter.host} screen test cleanup warning: failed to cancel active session | {cleanup_exc}")
            raise

        if shared and session_result.get("effective_payment_type", "") != PaymentType.COINS.name:
            card_meta = shared.device_meta.setdefault("nfc_gui_cards", {})
            card_meta[str(i + 1)] = session_result.get("card_last4")

        check_stop_event(shared)

    time.sleep(1)
    if not meter.in_diagnostics():
        meter.press("diagnostics")

    #! KEEP - Sleep is necessary for modem to finish its shutdown
    end = time.time() + 40
    while time.time() < end:
        check_stop_event(shared)
        time.sleep(5)
