"""Local modem journal watches and their integration with state polling."""

import ast
import importlib.util
import json
from pathlib import Path
import shlex
import threading
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lib/automation/tests/cycle_modem.py"
spec = importlib.util.spec_from_file_location("modem_cycle_under_test", MODULE_PATH)
modem_cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(modem_cycle)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def tick(self, seconds):
        self.now += seconds


class FakeShared:
    def __init__(self):
        self.stop_event = threading.Event()
        self.logs = []
        self.device_meta = {}

    def log(self, message):
        self.logs.append(message)

    def broadcast_progress(self, *_args):
        pass


CONNECT = "modemLib:sSendMessage: MODEM: SendRemote: CMD.CONNECT"
DISCONNECT = "modemLib:sSendMessage: MODEM: SendRemote: CMD.DISCONNECT"
CONNECTED = "ConnectionServer:sProcessModemMessage: Handling modem event: type=EVENT_TYPE_STATE, state=S4_CONNECTED"
IDLE = "ConnectionServer:sProcessModemMessage: Handling modem event: type=EVENT_TYPE_STATE, state=S1_IDLE"
ERROR = "ConnectionServer:sProcessModemMessage: Handling modem event: type=EVENT_TYPE_STATE, state=S7_ERROR"


class FakeModemMeter:
    host = "192.0.2.12"

    def __init__(self):
        self.entries = [("0", "old modem event: state=S4_CONNECTED")]
        self.modem_state = "S1_IDLE"
        self.polls = 0
        self.commands = []

    def add(self, message):
        self.entries.append((str(len(self.entries)), message))

    def exec_parse(self, command):
        args = shlex.split(command)
        if "-n" in args:
            entries = self.entries[-1:]
        else:
            self.polls += 1
            cursor = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--after-cursor="))
            entries = [(key, msg) for key, msg in self.entries if int(key) > int(cursor)]
        output = "\n".join(json.dumps({"__CURSOR": key, "MESSAGE": msg}) for key, msg in entries)
        return 0, output, ""

    def get_modem_state(self):
        return self.modem_state

    def goto_callin(self):
        pass

    def toggle_modem(self, enabled):
        self.commands.append(enabled)
        if enabled:
            self.add(CONNECT)
            self.add(CONNECTED)
            self.modem_state = "S4_CONNECTED"
        else:
            self.add(DISCONNECT)
            self.add(IDLE)
            self.modem_state = "S1_IDLE"


class ModemCycleTests(unittest.TestCase):
    def test_default_monitor_registration_is_removed_from_modem_flows(self):
        tree = ast.parse((MODULE_PATH.parent / "__init__.py").read_text(encoding="utf-8"))
        registry = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_PROGRAM_MONITORS" for target in node.targets)
        )
        self.assertEqual(registry["cycle_modem"], [])
        self.assertNotIn("modem", [name for name, _ in registry["cycle_all"]])

    def clock_patches(self, clock):
        return (
            patch.object(modem_cycle.time, "time", side_effect=lambda: clock.now),
            patch.object(modem_cycle.time, "monotonic", side_effect=lambda: clock.now),
            patch.object(modem_cycle.time, "sleep", side_effect=clock.tick),
        )

    def test_request_and_matching_state_cancel_watches(self):
        meter, shared = FakeModemMeter(), FakeShared()
        watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=True)
        meter.add(CONNECT)
        watch.poll()
        self.assertEqual(watch.pending, "connect")
        meter.add(CONNECTED)
        watch.poll()
        self.assertIsNone(watch.pending)
        meter.add(DISCONNECT)
        watch.poll()
        self.assertEqual(watch.pending, "disconnect")
        meter.add(IDLE)
        watch.poll()
        self.assertIsNone(watch.pending)
        self.assertTrue(any("initial journal cursor=" in line for line in shared.logs))
        self.assertTrue(any("journal: " in line for line in shared.logs))

    def test_new_request_replaces_opposite_watch(self):
        meter, shared = FakeModemMeter(), FakeShared()
        watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=False)
        meter.add(CONNECT)
        meter.add(DISCONNECT)
        watch.poll()
        self.assertEqual(watch.pending, "disconnect")
        meter.add(CONNECTED)
        watch.poll()
        self.assertEqual(watch.pending, "disconnect")
        meter.add(IDLE)
        watch.poll()
        self.assertIsNone(watch.pending)

    def test_error_state_does_not_cancel_idle_watch(self):
        meter, shared = FakeModemMeter(), FakeShared()
        watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=False)
        meter.add(DISCONNECT)
        meter.add(ERROR)
        watch.poll()
        self.assertEqual(watch.pending, "disconnect")

    def test_state_line_without_request_creates_no_watch(self):
        meter, shared = FakeModemMeter(), FakeShared()
        watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=False)
        meter.add(CONNECTED)
        meter.add(IDLE)
        watch.poll()
        self.assertIsNone(watch.pending)

    def test_journal_read_error_fails_local_verification(self):
        class ReadErrorMeter(FakeModemMeter):
            def exec_parse(self, command):
                if "--after-cursor=" in command:
                    return 1, "", "journal unavailable"
                return super().exec_parse(command)

        meter, shared = ReadErrorMeter(), FakeShared()
        watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=False)
        with self.assertRaisesRegex(RuntimeError, "journal unavailable"):
            watch.poll()

    def test_journal_watch_times_out_during_slower_state_polling(self):
        meter, shared, clock = FakeModemMeter(), FakeShared(), FakeClock()
        patches = self.clock_patches(clock)
        with patches[0], patches[1], patches[2]:
            watch = modem_cycle._ModemJournalWatch(meter, shared, cycle_num=1, debug=False)
            meter.add(CONNECT)
            with self.assertRaisesRegex(RuntimeError, "failed to reach CONNECTED within 35.0s"):
                modem_cycle._wait_for_modem_state(
                    meter, shared, cycle_num=1, phase="connect",
                    expected_states=("S4_CONNECTED",), timeout_s=100,
                    poll_s=2, journal_watch=watch, journal_poll_s=0.5,
                )
        self.assertEqual(clock.now, 35.0)
        self.assertGreaterEqual(meter.polls, 70)

    def test_complete_cycle_retains_state_and_signal_checks(self):
        meter, shared, clock = FakeModemMeter(), FakeShared(), FakeClock()
        patches = self.clock_patches(clock)
        with patches[0], patches[1], patches[2], \
             patch.object(modem_cycle, "_wait_for_startup_call_in_guard"), \
             patch.object(modem_cycle, "_wait_for_modem_ready", return_value=(True, "S1_IDLE", 0)), \
             patch.object(modem_cycle, "_journal_since_now", return_value="2026-11-04 08:00:00"), \
             patch.object(modem_cycle, "_get_latest_modem_signal_info", return_value=({"rssi": 25, "ber": 99}, "csq: 25,99")):
            modem_cycle.test_cycle_modem(
                meter, shared, job_count=1, modem_info_lookback_lead_s=0,
                state_poll_s=2, poll_s=0.5,
            )
        self.assertEqual(meter.commands, [True, False])
        self.assertEqual(shared.device_meta["modem"][1], {"rssi": 25, "ber": 99})
        self.assertTrue(any("CONNECTED; watch cancelled" in line for line in shared.logs))
        self.assertTrue(any("DISCONNECTED/IDLE; watch cancelled" in line for line in shared.logs))

    def test_busy_precheck_still_skips_without_arming_journal_watch(self):
        meter, shared = FakeModemMeter(), FakeShared()
        with patch.object(modem_cycle, "_wait_for_startup_call_in_guard"), \
             patch.object(modem_cycle, "_wait_for_modem_ready", return_value=(False, "S3_CONNECTING", 100)):
            modem_cycle.test_cycle_modem(meter, shared, job_count=1)
        self.assertEqual(meter.commands, [])
        self.assertEqual(meter.polls, 0)

    def test_missing_csq_still_fails_and_attempts_disconnect(self):
        meter, shared, clock = FakeModemMeter(), FakeShared(), FakeClock()
        patches = self.clock_patches(clock)
        with patches[0], patches[1], patches[2], \
             patch.object(modem_cycle, "_wait_for_startup_call_in_guard"), \
             patch.object(modem_cycle, "_wait_for_modem_ready", return_value=(True, "S1_IDLE", 0)), \
             patch.object(modem_cycle, "_journal_since_now", return_value="2026-11-04 08:00:00"), \
             patch.object(modem_cycle, "_get_latest_modem_signal_info", return_value=(None, "")), \
             self.assertRaisesRegex(RuntimeError, "Modem Connection Error"):
            modem_cycle.test_cycle_modem(meter, shared, job_count=1, modem_info_lookback_lead_s=0)
        self.assertEqual(meter.commands, [True, False])

    def test_s7_error_remains_accepted_by_state_poll_but_not_journal_watch(self):
        class ErrorStateMeter(FakeModemMeter):
            def toggle_modem(self, enabled):
                if enabled:
                    super().toggle_modem(True)
                else:
                    self.commands.append(False)
                    self.add(DISCONNECT)
                    self.add(ERROR)
                    self.modem_state = "S7_ERROR"

        meter, shared, clock = ErrorStateMeter(), FakeShared(), FakeClock()
        patches = self.clock_patches(clock)
        with patches[0], patches[1], patches[2], \
             patch.object(modem_cycle, "_wait_for_startup_call_in_guard"), \
             patch.object(modem_cycle, "_wait_for_modem_ready", return_value=(True, "S1_IDLE", 0)), \
             patch.object(modem_cycle, "_journal_since_now", return_value="2026-11-04 08:00:00"), \
             patch.object(modem_cycle, "_get_latest_modem_signal_info", return_value=({"rssi": 25, "ber": 99}, "csq: 25,99")):
            modem_cycle.test_cycle_modem(meter, shared, job_count=1, modem_info_lookback_lead_s=0)
        self.assertEqual(meter.commands, [True, False])
        self.assertTrue(any("disconnected=S7_ERROR" in line for line in shared.logs))
        self.assertFalse(any("DISCONNECTED/IDLE; watch cancelled" in line for line in shared.logs))


if __name__ == "__main__":
    unittest.main()
