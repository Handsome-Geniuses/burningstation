"""Printer journal verification without a physical meter."""

import json
import importlib.util
from pathlib import Path
import shlex
import threading
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "lib/automation/tests/cycle_print.py"
spec = importlib.util.spec_from_file_location("printer_cycle_under_test", MODULE_PATH)
printer_cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(printer_cycle)
run_print_cycle = printer_cycle.test_cycle_print


class FakeShared:
    def __init__(self):
        self.stop_event = threading.Event()
        self.logs = []

    def log(self, message):
        self.logs.append(message)

    def broadcast_progress(self, *_args):
        pass


class FakePrinterMeter:
    host = "192.0.2.10"
    meter_type = "msx"

    def __init__(self, responses):
        self.responses = responses
        self.prints = 0
        self.entries = [("0", "earlier PRINT_TICKET_REPLY: result=SUCCEEDED")]

    def exec_parse(self, command):
        args = shlex.split(command)
        if "-n" in args:
            entries = self.entries[-1:]
        else:
            cursor = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--after-cursor="))
            entries = [(key, msg) for key, msg in self.entries if int(key) > int(cursor)]
        output = "\n".join(json.dumps({"__CURSOR": key, "MESSAGE": msg}) for key, msg in entries)
        return 0, output, ""

    def printer_test(self):
        messages = self.responses[self.prints]
        self.prints += 1
        for message in messages:
            self.entries.append((str(len(self.entries)), message))


START = "IPSBusDev:IPSBusDevSendPrintMessageVA: IN IPSBusDevSendPrintMessageVA"
SUCCESS = "Meter:sProcessIPSBusMessage: PRINT_TICKET_REPLY: ticketNumber=68, result=SUCCEEDED"
PENDING = "Meter:sProcessIPSBusMessage: PRINT_TICKET_REPLY: ticketNumber=68, result=PENDING"
READY = "Meter:sProcessIPSBusMessage: PRINTER_STATUS_REPLY: status=DETECTED+TICKET_COMPLETE, isCanPrint=true"


class PrinterCycleTests(unittest.TestCase):
    def test_one_wait_setting_covers_legacy_names_and_keeps_eight_second_minimum(self):
        self.assertEqual(printer_cycle._configured_wait_s({}), 8.0)
        self.assertEqual(printer_cycle._configured_wait_s({"delay": 12, "timeout_s": 12}), 12.0)
        self.assertEqual(printer_cycle._configured_wait_s({"wait_s": 4}), 8.0)
        with self.assertRaisesRegex(ValueError, "must agree"):
            printer_cycle._configured_wait_s({"delay": 8, "timeout_s": 12})

    def test_each_print_uses_its_own_request_reply_and_ready_status(self):
        meter = FakePrinterMeter([[START, SUCCESS, READY], [START, SUCCESS, READY]])
        shared = FakeShared()
        run_print_cycle(meter, shared, job_count=2, poll_s=0.001)
        self.assertEqual(meter.prints, 2)
        self.assertEqual(sum("success confirmed; printer ready" in line for line in shared.logs), 2)

    def test_pending_reply_fails_immediately(self):
        meter = FakePrinterMeter([[START, PENDING, READY]])
        with self.assertRaisesRegex(RuntimeError, "returned PENDING"):
            run_print_cycle(meter, FakeShared(), job_count=1, poll_s=0.001)

    def test_fault_status_does_not_change_monitor_result(self):
        meter = FakePrinterMeter([[
            START, SUCCESS,
            "PRINTER_STATUS_REPLY: status=DETECTED+PAPER_OUT+NOT_READY+ERROR, isCanPrint=false",
        ]])
        shared = FakeShared()
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01):
            run_print_cycle(meter, shared, job_count=1, poll_s=0.001)
        self.assertTrue(any("completed legacy delay" in line for line in shared.logs))

    def test_missing_ready_status_uses_legacy_delay_without_failure(self):
        meter = FakePrinterMeter([[START, SUCCESS]])
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01):
            run_print_cycle(meter, FakeShared(), job_count=1, poll_s=0.001)

    def test_result_without_request_does_not_arm_a_watch(self):
        meter = FakePrinterMeter([[SUCCESS, READY]])
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01):
            run_print_cycle(meter, FakeShared(), job_count=1, poll_s=0.001)

    def test_unknown_result_cancels_watch_without_fault(self):
        meter = FakePrinterMeter([[START, "PRINT_TICKET_REPLY: result=FAILED"]])
        shared = FakeShared()
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01):
            run_print_cycle(meter, shared, job_count=1, poll_s=0.001)
        self.assertTrue(any("unknown result=FAILED" in line for line in shared.logs))

    def test_no_reply_after_request_times_out(self):
        meter = FakePrinterMeter([[START]])
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01), \
             self.assertRaisesRegex(RuntimeError, "timed out"):
            run_print_cycle(meter, FakeShared(), job_count=1, poll_s=0.001)

    def test_ready_status_alone_does_not_cancel_print_watch(self):
        meter = FakePrinterMeter([[START, READY]])
        with patch.object(printer_cycle, "PRINT_WAIT_S", 0.01), \
             self.assertRaisesRegex(RuntimeError, "timed out"):
            run_print_cycle(meter, FakeShared(), job_count=1, poll_s=0.001)

    def test_reply_on_timeout_boundary_is_processed_before_timeout(self):
        clock = [0.0]

        class BoundaryMeter(FakePrinterMeter):
            def exec_parse(self, command):
                if "--after-cursor=" in command and clock[0] >= 8 and len(self.entries) == 2:
                    self.entries.extend([("2", SUCCESS), ("3", READY)])
                return super().exec_parse(command)

        meter = BoundaryMeter([[START]])
        with patch.object(printer_cycle.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(printer_cycle.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            run_print_cycle(meter, FakeShared(), job_count=1)
        self.assertEqual(clock[0], 8.0)

    def test_debug_records_cursor_and_polled_lines(self):
        meter = FakePrinterMeter([[START, SUCCESS, READY]])
        shared = FakeShared()
        run_print_cycle(meter, shared, job_count=1, poll_s=0.001, debug=True)
        self.assertTrue(any("initial journal cursor=" in line for line in shared.logs))
        self.assertTrue(any("polled 3 journal entries" in line for line in shared.logs))
        self.assertTrue(any("journal: " in line for line in shared.logs))


if __name__ == "__main__":
    unittest.main()
