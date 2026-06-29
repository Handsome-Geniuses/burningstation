from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time
from lib.system import states



def test_dummy(meter: SSHMeter, shared: SharedState = None, **kwargs):
    # print(f"This is a dummy test function\n\t{kwargs}")
    # burn_count = kwargs.get("numBurnCycles", 1)
    # burn_delay = kwargs.get("numBurnDelay", 1)
    # print_count = kwargs.get("numPrintCycles", 1)
    # shutter_count = kwargs.get("numShutterCycles", 1)
    # blink_count = kwargs.get("numBlinkCount", 1)
    # nfc_count = kwargs.get("numNfcCycles", 1)
    # modem_count = kwargs.get("numModemCycles", 1)

    # print(f"Burning {burn_count} times with {burn_delay} seconds delay...")
    # print(f"Printing {print_count} times...")
    # print(f"Shuttering {shutter_count} times...")
    # print(f"Blinking {blink_count} times...")
    # print(f"NFC cycling {nfc_count} times...")
    # print(f"Modem cycling {modem_count} times...")

    dummy_key = meter.host
    states['dummy'].setdefault(dummy_key, {})['dummy'] = True

    start = time.time()
    passed = 0
    while True:
        passed = time.time() - start
        fake = states['dummy'].get(dummy_key, {}).get('dummy', False)
        if passed > 120 or not fake: break

        time.sleep(0.2)
    
    if not fake: print("[fake_dummy_playground_test]!faked")
    if passed > 120: print("[fake_dummy_playground_test]!passed")
    check_stop_event(shared)

    states['dummy'].setdefault(dummy_key, {})['dummy'] = False
