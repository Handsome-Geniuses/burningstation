"""NFC cycle journal verification without a physical meter."""

import ast
import importlib.util
import json
from pathlib import Path
import shlex
import threading
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "lib/automation/tests/cycle_nfc.py"
spec = importlib.util.spec_from_file_location("nfc_cycle_under_test", MODULE_PATH)
nfc_cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nfc_cycle)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeShared:
    def __init__(self):
        self.stop_event = threading.Event()
        self.logs = []

    def log(self, message):
        self.logs.append(message)

    def broadcast_progress(self, *_args):
        pass


def request(verb, payload, module="KIOSK_NEO"):
    return f"IPSBusLib: GENERIC_TERMINAL.NONE->{module}.APPLICATION_MSG {verb} F=0 seq=0 L=4 D={payload}"


def reply(payload, module="KIOSK_NEO"):
    return f"IPSBusLib: {module}.REMOTE_MSG->GENERIC_TERMINAL.NONE EMV_POWER_REPLY F=0 seq=1 L=4 D={payload}"


ON_REQUEST = request("EMV_POWER", "01 01 2D 00")
OFF_REQUEST = request("EMV_POWER", "01 00 3C 00")
ON_REPLY = reply("01 01 2D 00")
OFF_REPLY = reply("01 00 00 00")


class FakeNFCMeter:
    host = "192.0.2.11"

    def __init__(self, on_messages, off_messages):
        self.messages = {"plus": on_messages, "minus": off_messages}
        self.presses = []
        self.entries = [("0", "earlier EMV_POWER_REPLY F=0 D=01 01 00 00")]
        self.diagnostics = False

    def goto_nfc(self):
        # Navigation-generated OFF requests were suppressed by the monitor.
        self.entries.append((str(len(self.entries)), OFF_REQUEST))

    def press(self, button):
        self.presses.append(button)
        for message in self.messages[button]:
            self.entries.append((str(len(self.entries)), message))

    def force_diagnostics(self):
        self.diagnostics = True

    def exec_parse(self, command):
        args = shlex.split(command)
        if "-n" in args:
            entries = self.entries[-1:]
        else:
            cursor = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--after-cursor="))
            entries = [(key, msg) for key, msg in self.entries if int(key) > int(cursor)]
        output = "\n".join(json.dumps({"__CURSOR": key, "MESSAGE": msg}) for key, msg in entries)
        return 0, output, ""


class NFCCycleTests(unittest.TestCase):
    def test_no_registered_test_requires_a_default_monitor(self):
        registry_path = MODULE_PATH.parent / "__init__.py"
        tree = ast.parse(registry_path.read_text(encoding="utf-8"))
        registry = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_PROGRAM_MONITORS" for target in node.targets)
        )
        self.assertEqual(registry["cycle_nfc"], [])
        self.assertTrue(all(not monitors for monitors in registry.values()))
        self.assertNotIn("test_robot_nfc_read", registry)

    def run_cycle(self, meter, **kwargs):
        clock = FakeClock()
        shared = FakeShared()
        with patch.object(nfc_cycle.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(nfc_cycle.time, "sleep", side_effect=clock.sleep):
            nfc_cycle.test_cycle_nfc(meter, shared, job_count=1, **kwargs)
        return shared, clock

    def test_four_byte_power_replies_cancel_both_watches_and_keep_dwell(self):
        meter = FakeNFCMeter([ON_REQUEST, ON_REPLY], [OFF_REQUEST, OFF_REPLY])
        shared, clock = self.run_cycle(meter)
        self.assertEqual(meter.presses, ["plus", "minus"])
        self.assertTrue(meter.diagnostics)
        self.assertEqual(clock.now, 18.0)  # 2s navigation + 7s ON + 7s OFF + 2s cleanup
        self.assertTrue(any("ON confirmed" in line for line in shared.logs))
        self.assertTrue(any("OFF confirmed" in line for line in shared.logs))

    def test_two_byte_reply_and_card_read_instruction_forms(self):
        meter = FakeNFCMeter(
            [request("CARD_READ_INST", "00 02 00 00", "KIOSK_NFC"), reply("01 00", "KIOSK_NFC")],
            [request("CARD_READ_INST", "00 05 00 00", "KIOSK_NFC"), reply("00 00", "KIOSK_NFC")],
        )
        shared, _ = self.run_cycle(meter)
        self.assertTrue(any("ON confirmed" in line for line in shared.logs))
        self.assertTrue(any("OFF confirmed" in line for line in shared.logs))

    def test_opposite_reply_does_not_cancel_on_watch(self):
        meter = FakeNFCMeter([ON_REQUEST, OFF_REPLY], [OFF_REQUEST, OFF_REPLY])
        clock = FakeClock()
        with patch.object(nfc_cycle.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(nfc_cycle.time, "sleep", side_effect=clock.sleep), \
             self.assertRaisesRegex(RuntimeError, "failed to power ON within 6.0s"):
            nfc_cycle.test_cycle_nfc(meter, FakeShared(), job_count=1)
        self.assertEqual(meter.presses, ["plus", "minus"])  # failure cleanup powers down
        self.assertTrue(meter.diagnostics)

    def test_missing_request_arms_no_watch(self):
        meter = FakeNFCMeter([], [])
        _, clock = self.run_cycle(meter)
        self.assertEqual(clock.now, 18.0)

    def test_missing_off_reply_fails_after_off_watch(self):
        meter = FakeNFCMeter([ON_REQUEST, ON_REPLY], [OFF_REQUEST])
        clock = FakeClock()
        with patch.object(nfc_cycle.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(nfc_cycle.time, "sleep", side_effect=clock.sleep), \
             self.assertRaisesRegex(RuntimeError, "failed to power OFF within 3.0s"):
            nfc_cycle.test_cycle_nfc(meter, FakeShared(), job_count=1)
        self.assertEqual(meter.presses, ["plus", "minus"])
        self.assertTrue(meter.diagnostics)

    def test_unrecognized_request_does_not_arm_watch(self):
        meter = FakeNFCMeter([request("EMV_POWER", "01 03 00 00")], [])
        self.run_cycle(meter)
        self.assertTrue(meter.diagnostics)

    def test_request_during_post_navigation_settling_is_watched(self):
        class SetupRequestMeter(FakeNFCMeter):
            emitted = False

            def exec_parse(self, command):
                if "--after-cursor=" in command and not self.emitted:
                    self.entries.append((str(len(self.entries)), OFF_REQUEST))
                    self.emitted = True
                return super().exec_parse(command)

        meter = SetupRequestMeter([ON_REQUEST, ON_REPLY], [OFF_REQUEST, OFF_REPLY])
        clock = FakeClock()
        with patch.object(nfc_cycle.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(nfc_cycle.time, "sleep", side_effect=clock.sleep), \
             self.assertRaisesRegex(RuntimeError, "failed to power OFF within 3.0s"):
            nfc_cycle.test_cycle_nfc(meter, FakeShared(), job_count=1)
        self.assertTrue(meter.diagnostics)

    def test_journal_read_error_raises_and_powers_down(self):
        class ReadErrorMeter(FakeNFCMeter):
            def exec_parse(self, command):
                if "--after-cursor=" in command and self.presses:
                    return 1, "", "journal unavailable"
                return super().exec_parse(command)

        meter = ReadErrorMeter([ON_REQUEST], [OFF_REQUEST])
        clock = FakeClock()
        with patch.object(nfc_cycle.time, "monotonic", side_effect=clock.monotonic), \
             patch.object(nfc_cycle.time, "sleep", side_effect=clock.sleep), \
             self.assertRaisesRegex(RuntimeError, "journal unavailable"):
            nfc_cycle.test_cycle_nfc(meter, FakeShared(), job_count=1)
        self.assertEqual(meter.presses, ["plus", "minus"])
        self.assertTrue(meter.diagnostics)

    def test_debug_records_cursor_polls_and_matched_lines(self):
        meter = FakeNFCMeter([ON_REQUEST, ON_REPLY], [OFF_REQUEST, OFF_REPLY])
        shared, _ = self.run_cycle(meter, debug=True)
        self.assertTrue(any("initial journal cursor=" in line for line in shared.logs))
        self.assertTrue(any("polled 2 entries" in line for line in shared.logs))
        self.assertTrue(any("journal: " in line for line in shared.logs))


if __name__ == "__main__":
    unittest.main()
