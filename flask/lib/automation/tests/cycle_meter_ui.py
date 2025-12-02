from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
import random
import string
import requests
import re
from enum import Enum, auto
from datetime import datetime
import inspect

class PaymentType(Enum):
    COINS = 1
    CONTACT_CREDIT_CARD = 2
    CONTACTLESS_CARD = 3

MSX_TITLE_MAP = {
    "00": "welcome",
    "09": "plate_entry",
    "12": "duration_select",
    "23": "thank_you_receipt",
    "24": "authorizing",
    "99": "credit_card_confirmation",
}

def random_plate(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def get_msx_ui_page(meter) -> str:
    """ Return a simple page name based on the <title> code. Always a string. """
    url = f"http://{meter.host}:8005/UIPage.php"
    try:
        html = requests.get(url, timeout=3).text
    except Exception:
        return "error_fetch"

    if "UIPage.php" in html and "Warning" in html:
        return "error_php_warning"

    m = re.search(r"<title>\s*([0-9A-Za-z]+)\s*</title>", html, re.I)
    if not m:
        return "unknown"

    code = m.group(1)
    return MSX_TITLE_MAP.get(code, f"page_{code}")

def __test_cycle_ms25_ui(meter: SSHMeter, shared: SharedState, payment_type: str, count: int):
    func_name = inspect.currentframe().f_code.co_name

    for i in range(count):
        print(f"{meter.host} {func_name} {i+1}/{count}")
        if shared:
            shared.broadcast_progress(meter.host, 'cycle_ui', i+1, count)
        
        meter.press('a')
        check_stop_event(shared)

        # License plate entry
        meter.press('back', 1)
        plate = random_plate()
        for char in plate:
            meter.press(char, 0.5)
        meter.press('Enter', 1)
        check_stop_event(shared)

        # Time entry
        for _ in range(random.randint(3, 10)):
            meter.press('plus', 0.5)
        time.sleep(0.25)
        meter.press('enter', 1)
        time.sleep(0.25)
        check_stop_event(shared)

        # Payment logic
        if payment_type == PaymentType.COINS:
            # Simulate dropping in coins of various values
            for v in [100, 25, 25, 25, 10, 10, 25, 25, 100, 100]:
                meter.insert_coin(v, 0.5)
        elif payment_type == PaymentType.CONTACT_CREDIT_CARD:
            meter.custom_busdev("CONTACT", "Contact Credit Card")
            time.sleep(1)
            meter.press('Enter', 2)
        else:
            raise ValueError(f"Unknown payment type: {payment_type}")

        time.sleep(10) # give enough time for print
        check_stop_event(shared)

def __test_cycle_msx_ui(meter: SSHMeter, shared: SharedState, payment_type: str, count: int):
    func_name = inspect.currentframe().f_code.co_name

    for i in range(count):        
        print(f"{meter.host} {func_name} {i+1}/{count}")
        if shared:
            shared.broadcast_progress(meter.host, 'cycle_ui', i+1, count)
        
        meter.press('a')
        check_stop_event(shared)

        # License plate entry
        meter.press('back', 0.5)
        plate = random_plate()
        for char in plate:
            meter.press(char, 0.5)
        meter.press('Enter', 1)
        check_stop_event(shared)

        # Time entry
        for _ in range(random.randint(3, 10)):
            meter.press('plus', 0.5)
        meter.press('enter', 1)
        check_stop_event(shared)

        # Payment logic
        if payment_type == PaymentType.COINS:
            for v in [100, 25, 25, 25, 10, 10, 25, 25, 100, 100]:
                meter.insert_coin(v, 0.5)
            time.sleep(5)

            end = time.time() + 15 # wait ~10 seconds for end of qr receipt page
            while time.time() < end:
                page = get_msx_ui_page(meter)
                if page != 'thank_you_receipt':
                    # print(f'breaking out bc page={page} {datetime.now().strftime("%H:%M:%S.%f")[:-3]}')
                    break
                if shared:
                    check_stop_event(shared)
                time.sleep(1)

        elif payment_type == PaymentType.CONTACT_CREDIT_CARD:
            time.sleep(1)
            meter.custom_busdev("CONTACT", "Contact Credit Card")
            time.sleep(5)
            meter.press('Enter')
            time.sleep(1)

            end = time.time() + 40 # wait ~25 seconds for transaction and ~10 seconds for end of qr receipt page
            while time.time() < end:
                page = get_msx_ui_page(meter)
                if page not in ("authorizing", "thank_you_receipt"):
                    # print(f'breaking out bc page={page} {datetime.now().strftime("%H:%M:%S.%f")[:-3]}')
                    break
                if shared:
                    check_stop_event(shared)
                time.sleep(1)

        else:
            raise ValueError(f"Unknown payment type: {payment_type}")

        check_stop_event(shared)

def test_cycle_meter_ui(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """Runs a full simulated payment UI cycle."""
    payment_type = kwargs.get("payment_type", "coins")
    count = int(kwargs.get("count", 1))

    if not isinstance(payment_type, PaymentType):
        try:
            payment_type = PaymentType[payment_type.strip().upper()]
        except (KeyError, AttributeError):
            payment_type = PaymentType.COINS

    if meter.in_diagnostics():
        meter.press('diagnostics')

    if meter.meter_type in ['ms2.5', 'ms3']:
        __test_cycle_ms25_ui(meter, shared, payment_type, count)
    elif meter.meter_type == 'msx':
        __test_cycle_msx_ui(meter, shared, payment_type, count)

    check_stop_event(shared)
    time.sleep(1)
    if not meter.in_diagnostics():
        meter.press('diagnostics')
    
    end = time.time() + 40 # give modem a chance to properly disconnect and go to its idle state
    while time.time() < end:
        check_stop_event(shared)
        time.sleep(5)
