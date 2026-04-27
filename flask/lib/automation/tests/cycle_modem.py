from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event
import time
import inspect
from typing import Optional
import re

DEFAULT_MODEM_CONNECT_TIMEOUT_S = 35.0
DEFAULT_MODEM_DISCONNECT_TIMEOUT_S = 30.0
MODEM_PRECHECK_TIMEOUT_S = 100.0
MODEM_PRECHECK_POLL_S = 3.0
MODEM_STATE_POLL_S = 2.0
MODEM_INFO_LOOKBACK_LEAD_S = 2.0
MODEM_CONNECTED_STATE = "S4_CONNECTED"
MODEM_IDLE_STATE = "S1_IDLE"
MODEM_ERROR_STATE = "S7_ERROR"
MODEM_DISCONNECTED_STATES = (MODEM_IDLE_STATE, MODEM_ERROR_STATE)
MODEM_CSQ_RE = re.compile(r"\bcsq\s*:\s*(?P<rssi>\d+)\s*,\s*(?P<ber>\d+)\b", re.IGNORECASE)
MODEM_BUSY_STATES = {
    "S0_START",
    "S2_POWERING_UP",
    "S3_CONNECTING",
    "S4_CONNECTED",
    "S5_WAITING_TO_SHUT_DOWN",
    "S6_SHUTTING_DOWN",
    "S8_BOUNCING",
    "(unknown:-1)", # observed during meter boot/initialization
}


def _sleep_with_stop(shared: SharedState, seconds: float, poll_interval: float = 0.25) -> None:
    deadline = time.time() + max(0.0, seconds)
    while True:
        check_stop_event(shared)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(poll_interval, remaining))


def _get_modem_meta(shared: SharedState) -> dict:
    return shared.device_meta.setdefault("modem", {})


def _journal_since_now(meter: SSHMeter) -> str:
    return meter.cli("date '+%Y-%m-%d %H:%M:%S'")


def _parse_modem_signal_line(line: str) -> Optional[dict]:
    match = MODEM_CSQ_RE.search(line or "")
    if not match:
        return None
    return {
        "rssi": int(match.group("rssi")),
        "ber": int(match.group("ber")),
    }


def _get_latest_modem_signal_info(meter: SSHMeter, since: str) -> tuple[Optional[dict], str]:
    # journalctl -u MS3_Platform.service --since "<since>" --no-pager -r | grep -m 1 -F 'csq:'
    #   -r = newest first
    #   grep -m 1 = stop after first match
    cmd = (
        f"journalctl -u MS3_Platform.service --since \"{since}\" -n 800 --no-pager | "
        "grep -F 'csq:' | tail -n 1"
    )
    result = meter.cli(cmd)
    if not result:
        return None, ""

    for line in reversed(result.splitlines()):
        modem_info = _parse_modem_signal_line(line)
        if modem_info:
            return modem_info, line

    return None, result.strip()


def _stop_modem_after_error(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    reason: str,
    timeout_s: float,
    poll_s: float,
) -> None:
    shared.log(f"{meter.host} modem cycle {cycle_num}: attempting modem OFF after {reason}")
    try:
        meter.toggle_modem(False)
    except Exception as exc:
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: failed to send modem OFF after {reason} ({exc})",
        )
        return

    try:
        _, disconnect_elapsed_s = _wait_for_modem_state(
            meter,
            shared,
            cycle_num=cycle_num,
            phase="disconnect cleanup",
            expected_states=MODEM_DISCONNECTED_STATES,
            timeout_s=timeout_s,
            poll_s=poll_s,
        )
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: cleanup reached "
            f"{MODEM_IDLE_STATE} or {MODEM_ERROR_STATE} in {disconnect_elapsed_s:.1f}s",
        )
    except Exception as exc:
        shared.log(
            f"{meter.host} modem cycle {cycle_num}: cleanup failed after {reason} ({exc})",
        )


def _wait_for_modem_ready(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    timeout_s: float,
    poll_s: float,
) -> tuple[bool, Optional[str], float]:
    started = time.time()
    deadline = time.time() + max(0.0, timeout_s)
    last_state: Optional[str] = None

    while True:
        check_stop_event(shared)

        try:
            modem_state = meter.get_modem_state()
        except Exception as exc:
            shared.log(
                f"{meter.host} modem pre-check {cycle_num}: unable to read modem state ({exc}); proceeding",
            )
            return True, None, time.time() - started

        if modem_state != last_state:
            shared.log(
                f"{meter.host} modem pre-check {cycle_num}: state={modem_state or 'unknown'}",
            )
            last_state = modem_state

        if not modem_state or modem_state not in MODEM_BUSY_STATES:
            return True, modem_state, time.time() - started

        remaining = deadline - time.time()
        if remaining <= 0:
            return False, modem_state, time.time() - started

        _sleep_with_stop(shared, min(poll_s, remaining))


def _wait_for_modem_state(
    meter: SSHMeter,
    shared: SharedState,
    cycle_num: int,
    phase: str,
    expected_states: tuple[str, ...],
    timeout_s: float,
    poll_s: float,
) -> tuple[str, float]:
    started = time.time()
    deadline = started + max(0.0, timeout_s)
    last_state: Optional[str] = None

    while True:
        check_stop_event(shared)

        try:
            modem_state = meter.get_modem_state()
        except Exception as exc:
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: unable to read modem state ({exc}); retrying",
            )
            modem_state = None

        if modem_state != last_state:
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: state={modem_state or 'unknown'}",
            )
            last_state = modem_state

        if modem_state in expected_states:
            elapsed_s = time.time() - started
            shared.log(
                f"{meter.host} modem {phase} wait {cycle_num}: reached {modem_state} in {elapsed_s:.1f}s",
            )
            return modem_state, elapsed_s

        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Modem {phase} cycle {cycle_num} timed out waiting for "
                f"{' or '.join(expected_states)}; "
                f"last_state={modem_state or 'unknown'} after {timeout_s:.1f}s"
            )

        _sleep_with_stop(shared, min(poll_s, remaining))


def test_cycle_modem(meter: SSHMeter, shared: SharedState, **kwargs):
    """ Toggle ON/OFF Modem N times. Stops early if shared.stop_event is set. """
    func_name = inspect.currentframe().f_code.co_name
    count = int(kwargs.get("count", 3))
    connect_timeout_s = float(kwargs.get("connect_timeout_s", kwargs.get("delay_on", DEFAULT_MODEM_CONNECT_TIMEOUT_S)))
    disconnect_timeout_s = float(kwargs.get("disconnect_timeout_s", kwargs.get("delay_off", DEFAULT_MODEM_DISCONNECT_TIMEOUT_S)))
    precheck_timeout_s = float(kwargs.get("precheck_timeout_s", MODEM_PRECHECK_TIMEOUT_S))
    precheck_poll_s = float(kwargs.get("precheck_poll_s", MODEM_PRECHECK_POLL_S))
    state_poll_s = float(kwargs.get("state_poll_s", MODEM_STATE_POLL_S))
    modem_info_lookback_lead_s = float(
        kwargs.get("modem_info_lookback_lead_s", MODEM_INFO_LOOKBACK_LEAD_S)
    )
    subtest = bool(kwargs.get("subtest", False))

    meter.goto_callin()

    for i in range(count):
        cycle_num = i + 1
        shared.log(f"{meter.host} {func_name} {i+1}/{count}")
        if not subtest:
            shared.broadcast_progress(meter.host, 'modem', cycle_num, count)

        shared.set_allowed(set(), reason="Modem pre-check in progress")
        ready, modem_state, precheck_elapsed_s = _wait_for_modem_ready(
            meter,
            shared,
            cycle_num=cycle_num,
            timeout_s=precheck_timeout_s,
            poll_s=precheck_poll_s,
        )
        shared.log(
            f"{meter.host} modem pre-check {cycle_num}: "
            f"{'ready' if ready else 'busy'} after {precheck_elapsed_s:.1f}s "
            f"(state={modem_state or 'unknown'})",
        )
        if not ready:
            shared.log(
                f"{meter.host} {func_name} {cycle_num}/{count} skipped; modem stayed busy in {modem_state}",
            )
            continue

        shared.set_allowed({"modem"}, reason="Modem test ready; arm monitor")
        modem_on = False

        try:
            connect_journal_since = _journal_since_now(meter)
            if modem_info_lookback_lead_s > 0:
                _sleep_with_stop(shared, modem_info_lookback_lead_s)

            meter.toggle_modem(True)
            modem_on = True
            connected_state, connect_elapsed_s = _wait_for_modem_state(
                meter,
                shared,
                cycle_num=cycle_num,
                phase="connect",
                expected_states=(MODEM_CONNECTED_STATE,),
                timeout_s=connect_timeout_s,
                poll_s=state_poll_s,
            )

            modem_info, modem_info_line = _get_latest_modem_signal_info(meter, connect_journal_since)
            if modem_info is not None:
                modem_meta = _get_modem_meta(shared)
                modem_meta[cycle_num] = {"rssi": modem_info["rssi"], "ber": modem_info["ber"]}
                shared.log(
                    f"{meter.host} modem cycle {cycle_num}: "
                    f"connected={connected_state} in {connect_elapsed_s:.1f}s | "
                    f"rssi={modem_info['rssi']} ber={modem_info['ber']}",
                )
            else:
                if modem_info_line:
                    shared.log(
                        f"{meter.host} modem cycle {cycle_num}: unable to parse modem info line -> {modem_info_line}",
                    )
                else:
                    shared.log(
                        f"{meter.host} modem cycle {cycle_num}: no modem signal info found since {connect_journal_since}",
                    )
                _stop_modem_after_error(
                    meter,
                    shared,
                    cycle_num=cycle_num,
                    reason="missing modem signal info",
                    timeout_s=disconnect_timeout_s,
                    poll_s=state_poll_s,
                )
                modem_on = False
                raise RuntimeError("Modem Connection Error")

            meter.toggle_modem(False)
            modem_on = False
            disconnected_state, disconnect_elapsed_s = _wait_for_modem_state(
                meter,
                shared,
                cycle_num=cycle_num,
                phase="disconnect",
                expected_states=MODEM_DISCONNECTED_STATES,
                timeout_s=disconnect_timeout_s,
                poll_s=state_poll_s,
            )
            shared.log(
                f"{meter.host} modem cycle {cycle_num}: "
                f"disconnected={disconnected_state} in {disconnect_elapsed_s:.1f}s",
            )
        except Exception as exc:
            if modem_on:
                _stop_modem_after_error(
                    meter,
                    shared,
                    cycle_num=cycle_num,
                    reason=f"{type(exc).__name__}: {exc}",
                    timeout_s=disconnect_timeout_s,
                    poll_s=state_poll_s,
                )
            raise

        check_stop_event(shared)
