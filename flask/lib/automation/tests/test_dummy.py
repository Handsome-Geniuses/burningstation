from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
import time

def test_dummy(meter: SSHMeter, shared: SharedState = None, **kwargs):
    print(f"This is a dummy test function\n\t{kwargs}")
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

