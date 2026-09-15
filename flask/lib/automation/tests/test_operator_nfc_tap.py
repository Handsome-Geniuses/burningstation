import inspect

from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


#TODO: Need an updated meter for this
def test_operator_nfc_tap(meter: SSHMeter, shared: SharedState, **kwargs):
    """Operator-guided NFC tap test."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    max_duration_s = float(kwargs.get("max_duration_s", 60.0))

    shared.log(f"{meter.host} test_operator_nfc_tap placeholder")
    print("hi from test_operator_nfc_tap")
