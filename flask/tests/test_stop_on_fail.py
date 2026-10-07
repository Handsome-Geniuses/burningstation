"""Full-run continuation keeps subtest failures separate from abort requests."""
import unittest
from importlib import import_module
from unittest.mock import Mock, patch

from lib.automation.helpers import StopAutomation
from lib.automation.shared_state import SharedState
from lib.automation.listener import Listener

cycle_all = import_module("lib.automation.tests.cycle_all")
operator_cycle_all = import_module("lib.automation.tests.operator_cycle_all")
physical_cycle_all = import_module("lib.automation.tests.physical_cycle_all")


class FullRunStopOnFailTests(unittest.TestCase):
    def test_critical_listener_fault_is_an_abort(self):
        shared = SharedState()
        shared.last_error = None
        listener = object.__new__(Listener)
        listener.shared = shared
        listener.verbose = False
        fault = Mock(severity="critical", device="coin shutter", message="fault")
        listener._emit_faults([fault])
        self.assertTrue(shared.abort_event.is_set())
        self.assertTrue(shared.stop_event.is_set())
        self.assertFalse(shared.continue_after_failure(False))

    def _run(self, module, entrypoint, stop_on_fail, abort=False, cycles=1):
        shared = SharedState()
        shared.last_error = None
        calls = []

        def first(meter, shared, **kwargs):
            calls.append("first")
            shared.stop_event.set()
            if abort:
                with shared.lock:
                    shared.abort_event.set()
            raise StopAutomation("first failed")

        def second(meter, shared, **kwargs):
            calls.append("second")

        meter = Mock(host="mock", is_mock=False)
        meter.device_firmware.return_value = True
        meter.in_diagnostics.return_value = True
        kwargs = {
            "numBurnCycles": cycles,
            "numBurnDelay": 0,
            "stop_on_fail": stop_on_fail,
            "first": {"job_count": 1},
            "second": {"job_count": 1},
        }
        patches = [
            patch.object(module, "time"),
            patch.object(module, "DEVICES" if module is cycle_all else
                         "OPERATOR_TESTS" if module is operator_cycle_all else
                         "PHYSICAL_DEVICES", [("first", first, {}), ("second", second, {})]),
        ]
        if module is physical_cycle_all:
            kwargs["charuco_frame"] = [0] * 6
            patches += [patch.object(module, "RobotClient"),
                        patch.object(module, "_combined_solar_keypad_enabled", return_value=False)]
        if module is cycle_all:
            # The runner's virtual dispatch is covered by test_mock_passive.
            meter.is_mock = False

        with patches[0], patches[1]:
            if module is physical_cycle_all:
                with patches[2], patches[3]:
                    outcome = self._invoke(entrypoint, meter, shared, kwargs)
            else:
                outcome = self._invoke(entrypoint, meter, shared, kwargs)
        return shared, calls, outcome

    @staticmethod
    def _invoke(entrypoint, meter, shared, kwargs):
        try:
            entrypoint(meter, shared, **kwargs)
        except StopAutomation:
            return "stopped"
        return "completed"

    def test_continue_or_stop_for_each_full_run(self):
        for module, entrypoint in (
            (cycle_all, cycle_all.test_cycle_all),
            (operator_cycle_all, operator_cycle_all.operator_cycle_all),
            (physical_cycle_all, physical_cycle_all.physical_cycle_all),
        ):
            with self.subTest(run=module.__name__):
                shared, calls, outcome = self._run(module, entrypoint, False, cycles=2)
                self.assertEqual(outcome, "completed")
                self.assertEqual(calls, ["first", "second", "first", "second"])
                self.assertEqual(shared.device_results, {"first": "fail", "second": "pass"})
                self.assertFalse(shared.stop_event.is_set())

                shared, calls, outcome = self._run(module, entrypoint, True)
                self.assertEqual(outcome, "stopped")
                self.assertEqual(calls, ["first"])

                shared, calls, outcome = self._run(module, entrypoint, False, abort=True)
                self.assertEqual(outcome, "stopped")
                self.assertEqual(calls, ["first"])
                self.assertTrue(shared.stop_event.is_set())


if __name__ == "__main__":
    unittest.main()
