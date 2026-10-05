"""Interactive, per-meter virtual peripherals. Loaded only by mock paths."""
from collections import deque
from copy import deepcopy
import math
import threading
import time
from uuid import uuid4

from lib.automation.helpers import check_stop_event, StopAutomation
from lib.automation.operator_feedback import publish_operator_feedback

# Denominations: usmint.gov/learn/coins-and-medals/circulating-coins/coin-specifications
# and royalmint.com/globalassets/consumer/_campaigns/2023/definitives/mintlings/definitives-mintlings-booklet.pdf
COINS = [
    {"id": f"{currency}-{value}", "kind": "coin", "country": country,
     "currency": currency, "value": value, "label": label, "tone": tone}
    for country, currency, denominations in [
        ("United States", "USD", [(1, "1¢", "copper"), (5, "5¢", "silver"), (10, "10¢", "silver"), (25, "25¢", "silver"), (50, "50¢", "silver"), (100, "$1", "gold")]),
        ("United Kingdom", "GBP", [(1, "1p", "copper"), (2, "2p", "copper"), (5, "5p", "silver"), (10, "10p", "silver"), (20, "20p", "silver"), (50, "50p", "silver"), (100, "£1", "gold"), (200, "£2", "gold")]),
        ("Canada", "CAD", [(100, "$1", "gold")]),
        ("Japan", "JPY", [(100, "¥100", "silver")]),
        ("Mexico", "MXN", [(1000, "$10", "gold")]),
        ("Australia", "AUD", [(200, "$2", "gold")]),
        ("Switzerland", "CHF", [(100, "1 Fr", "silver")]),
        ("India", "INR", [(500, "₹5", "gold")]),
        ("South Africa", "ZAR", [(500, "R5", "silver")]),
        ("Brazil", "BRL", [(100, "R$1", "gold")]),
        ("South Korea", "KRW", [(100, "₩100", "silver")]),
        ("New Zealand", "NZD", [(200, "$2", "gold")]),
    ] for value, label, tone in denominations
]
CARDS = [
    {"id": f"{brand}-{int(nfc)}", "kind": "card", "brand": brand,
     "label": label, "nfc": nfc, "accepted": brand in {"visa", "mastercard"}}
    for brand, label in [("visa", "Visa"), ("mastercard", "Mastercard"), ("amex", "American Express"), ("discover", "Discover")]
    for nfc in (True, False)
]
ITEMS = {item["id"]: item for item in COINS + CARDS}
TITLES = {
    "coins": "Coin detection test", "touchscreen": "Touchscreen test",
    "card_reader": "Card reader test", "contactless": "Contactless card test",
    "screen_test": "Screen cycle test", "display_brightness": "Display brightness test",
    "keypad": "Keypad test",
}
INSTRUCTIONS = {
    "coins": "Insert the required coins into the coin reader.",
    "touchscreen": "Touch the virtual meter screen.",
    "card_reader": "Insert a Visa or Mastercard, then double-click the reader to remove and read it.",
    "contactless": "Tap a contactless Visa or Mastercard on the NFC reader.",
    "screen_test": "Watch the screen cycle through the test colors.",
}


class VirtualMeter:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = deque(maxlen=100)
        self.state = {"session": None, "device": None, "screen_color": None,
                      "brightness": 99, "inserted_card": None, "message": "Ready for testing",
                      "printed": 0}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def update(self, **kwargs):
        with self.lock:
            self.state.update(kwargs)

    def begin(self, device):
        with self.lock:
            self.events.clear()
            self.state.update(session=str(uuid4()), device=device, screen_color=None,
                              message=TITLES[device])

    def finish(self, success):
        with self.lock:
            self.events.clear()
            self.state.update(session=None, device=None, screen_color=None,
                              message="Test passed" if success else "Test stopped or failed")

    def pop(self):
        with self.lock:
            return self.events.popleft() if self.events else None

    def interact(self, payload):
        with self.lock:
            kind = payload.get("kind")
            event = None
            if kind == "remove_card":
                item = ITEMS.get(self.state["inserted_card"])
                if item is None:
                    return {"consumed": False, "message": "No card inserted"}
                self.state["inserted_card"] = None
                self.state["message"] = f"{item['label']} — {'accepted' if item['accepted'] else 'not accepted'}"
                event = {"kind": "stripe", "item": item}
            elif kind == "touch":
                x, y = payload.get("x"), payload.get("y")
                if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
                    raise ValueError("Touch coordinates must be between 0 and 1")
                event = {"kind": "touch", "x": x, "y": y}
            elif kind == "drop":
                item = ITEMS.get(payload.get("item"))
                target = payload.get("target")
                if not item or target not in {"coin", "stripe", "nfc"}:
                    raise ValueError("Unknown item or reader")
                if item["kind"] == "coin" and target == "coin":
                    known = item["currency"] == "USD"
                    self.state["message"] = f"Detected {item['label']} USD" if known else "Unknown coin — returned"
                    event = {"kind": "coin", "item": item, "accepted": known}
                elif item["kind"] == "card" and target == "stripe":
                    if self.state["inserted_card"]:
                        return {"consumed": False, "message": "Remove the inserted card first"}
                    self.state["inserted_card"] = item["id"]
                    self.state["message"] = f"{item['label']} inserted — remove the card to read it"
                elif item["kind"] == "card" and target == "nfc" and item["nfc"]:
                    self.state["message"] = f"{item['label']} — {'accepted' if item['accepted'] else 'not accepted'}"
                    event = {"kind": "nfc", "item": item}
                else:
                    return {"consumed": False, "message": "No read"}
            else:
                raise ValueError("Unknown interaction")
            # Inputs from a stale tab/test can animate but never credit a new test.
            if event and self.state["session"] and payload.get("session") == self.state["session"]:
                self.events.append(event)
            return {"consumed": True, "message": self.state["message"]}


def run_virtual_test(meter, shared, device, test_func, kwargs):
    virtual = meter.virtual_meter
    virtual.begin(device)
    success = False
    error = ""
    started = time.monotonic()
    try:
        if device in {"keypad", "display_brightness"}:
            test_func(meter, shared=shared, **kwargs)
        else:
            _run_inputs(meter, shared, device, kwargs, started)
        check_stop_event(shared)
        success = True
    except Exception as exc:
        error = str(exc)
        shared.last_error = error
        if device not in {"keypad", "display_brightness"}:
            publish_operator_feedback(meter, shared, test=device, title=TITLES[device],
                instruction="Test stopped or failed.", status="fail", active=False, error=error)
        raise
    finally:
        virtual.finish(success)
        shared.device_meta.setdefault(device, {}).update(mock=True, error=error,
            duration_s=round(time.monotonic() - started, 3))


def _run_inputs(meter, shared, device, kwargs, started):
    virtual = meter.virtual_meter
    count = max(1, int(kwargs.get("job_count", 1)))
    total = count
    current = 0
    details = {}
    timeout = float(kwargs.get("max_duration_s", 180))
    if timeout <= 0:
        raise ValueError("max_duration_s must be greater than zero")
    if device == "coins":
        from lib.automation.tests.test_operator_coins import _default_coin_requirements, _normalize_coin_requirements
        raw = kwargs.get("coin_requirements", _default_coin_requirements("us"))
        requirements = _normalize_coin_requirements(raw)
        details["detections"] = {name: {"currency_code": req.currency_code, "value_minor": req.value_minor,
            "required": req.quantity * count, "credited": 0, "detected": 0, "accepted": 0, "rejected": 0}
            for name, req in requirements.items()}
        details["unknown"] = 0
        total = sum(row["required"] for row in details["detections"].values())
    elif device == "touchscreen":
        total = max(1, int(kwargs.get("expected_touch_count", 5))) * count
        details["touches"] = []
    elif device == "card_reader":
        details["reads"] = []
    elif device == "contactless":
        details.update(attempts=[], reader_state="ready")
    elif device == "screen_test":
        total = 7 * count

    def publish(status="running", active=True):
        publish_operator_feedback(meter, shared, test=device, title=TITLES[device],
            instruction=INSTRUCTIONS[device] if active else "Test complete.",
            status=status, current=current, total=total, details=deepcopy(details), active=active)
        shared.broadcast_progress(meter.host, device, current, total)

    publish()
    while current < total:
        check_stop_event(shared)
        if time.monotonic() - started >= timeout:
            raise StopAutomation(f"{device.replace('_', ' ')} timed out after {timeout:g}s ({current}/{total})")
        if device == "screen_test":
            virtual.update(screen_color=["#ef4444", "#f97316", "#facc15", "#22c55e", "#3b82f6", "#4f46e5", "#a855f7"][current % 7])
            if shared.stop_event.wait(0.5):
                check_stop_event(shared)
            current += 1
            publish()
            continue
        event = virtual.pop()
        if not event:
            shared.stop_event.wait(0.05)
            continue
        if device == "coins" and event["kind"] == "coin":
            item = event["item"]
            if not event["accepted"]:
                details["unknown"] += 1
            for row in details["detections"].values():
                if event["accepted"] and (row["currency_code"], row["value_minor"]) == (item["currency"], item["value"]):
                    row["detected"] += 1
                    row["accepted"] += 1
                    row["credited"] = min(row["required"], row["credited"] + 1)
            current = sum(row["credited"] for row in details["detections"].values())
        elif device == "touchscreen" and event["kind"] == "touch":
            current += 1
            details["touches"].append({"number": current, "x": round(event["x"] * 800), "y": round(event["y"] * 480),
                                      "physical_x": event["x"], "physical_y": event["y"]})
        elif device == "card_reader" and event["kind"] == "stripe":
            item = event["item"]
            current += int(item["accepted"])
            details["reads"].append({"read_number": len(details["reads"]) + 1,
                "classification": "pass" if item["accepted"] else "retry", "read_type_name": "Magnetic stripe",
                "card_type_name": item["label"], "card_hash_hex": "MOCK", "is_card_accepted": item["accepted"],
                "retry_reasons": [] if item["accepted"] else ["Card brand not accepted"]})
        elif device == "contactless" and event["kind"] == "nfc":
            item = event["item"]
            current += int(item["accepted"])
            details["attempts"].append({"attempt_number": len(details["attempts"]) + 1,
                "status": "pass" if item["accepted"] else "retry", "card_masked": item["label"],
                "retry_reason": "" if item["accepted"] else "Card brand not accepted"})
        publish()
    shared.device_meta.setdefault(device, {}).update(deepcopy(details))
    publish("pass", False)
