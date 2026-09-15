import inspect

from lib.automation.helpers import check_stop_event
from lib.automation.shared_state import SharedState
from lib.meter.ssh_meter import SSHMeter


def test_operator_display_brightness(
    meter: SSHMeter,
    shared: SharedState,
    **kwargs,
):
    """Operator-guided verification of display brightness changes."""
    func_name = inspect.currentframe().f_code.co_name
    subtest = bool(kwargs.get("subtest", False))
    max_duration_s = float(kwargs.get("max_duration_s", 60.0))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, 'display_brightness', 1, 1)

    stored_brightness = meter.get_brightness()

    try:
        check_stop_event(shared)

        # TODO: create/send out the UI Question "Is display brightness changing? Yes/No"
        # Wait for response while:
        #   checking if elapsed time > max_duration_s
        #   change the display brightness low to high
        #   check_stop_event(shared)

    except Exception as exc:
        # ...
        raise
    finally:
        meter.set_brightness(stored_brightness)
        # log data and wrap up
