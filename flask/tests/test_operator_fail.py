"""Operator-requested failures belong to the active full-run subtest."""
from importlib import import_module
import threading
import unittest
from unittest.mock import Mock, patch

from lib.automation import jobs
from lib.automation.helpers import StopAutomation, check_stop_event


operator_cycle = import_module("lib.automation.tests.operator_cycle_all")


class OperatorFailureTests(unittest.TestCase):
    def _run_case(self, failing_device, stop_on_fail, abort_after_fail=False):
        host = f"operator-fail-{failing_device}-{stop_on_fail}-{abort_after_fail}"
        state = jobs.JobState(host)
        state.status = "running"
        state.current_program = "operator_cycle_all"
        meter = Mock(host=host, is_mock=False)
        meter.in_diagnostics.return_value = True
        waiting = threading.Event()
        allow_exit = threading.Event()
        calls = []
        errors = []

        def test(device):
            def run(meter, shared, **kwargs):
                calls.append(device)
                if device == failing_device:
                    waiting.set()
                    self.assertTrue(shared.stop_event.wait(3))
                    self.assertTrue(allow_exit.wait(3))
                    check_stop_event(shared)
            return run

        rows = [(name, test(name), {}) for name in ("coins", "keypad", "contactless")]
        config = {name: {"job_count": 1} for name, _, _ in rows}
        config.update(numBurnCycles=1, numBurnDelay=0, stop_on_fail=stop_on_fail)

        def run_cycle():
            try:
                operator_cycle.operator_cycle_all(meter, state, **config)
            except StopAutomation as exc:
                errors.append(str(exc))

        with jobs._registry_lock:
            jobs._states[host] = state
        try:
            with patch.object(operator_cycle, "OPERATOR_TESTS", rows), patch.object(operator_cycle, "time"):
                worker = threading.Thread(target=run_cycle)
                worker.start()
                self.assertTrue(waiting.wait(3))
                self.assertFalse(jobs.fail_operator_subtest("missing-meter", failing_device))
                self.assertFalse(jobs.fail_operator_subtest(host, "wrong-test"))
                self.assertTrue(jobs.fail_operator_subtest(host, failing_device))
                self.assertFalse(jobs.fail_operator_subtest(host, failing_device))
                if abort_after_fail:
                    with state.lock:
                        state.abort_event.set()
                        state.stop_event.set()
                allow_exit.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
        finally:
            allow_exit.set()
            with jobs._registry_lock:
                jobs._states.pop(host, None)
        return state, calls, errors

    def test_fail_coins_and_keypad_follow_stop_on_fail(self):
        for device in ("coins", "keypad"):
            for stop_on_fail in (True, False):
                with self.subTest(device=device, stop_on_fail=stop_on_fail):
                    state, calls, errors = self._run_case(device, stop_on_fail)
                    self.assertEqual(state.device_results[device], "fail")
                    self.assertEqual(state.device_meta[device]["error"], f"Operator marked {device} failed")
                    self.assertEqual(state.last_error, f"Operator marked {device} failed")
                    self.assertEqual(bool(errors), stop_on_fail)
                    if stop_on_fail:
                        self.assertNotIn("contactless", calls)
                    else:
                        self.assertIn("contactless", calls)
                        self.assertFalse(state.stop_event.is_set())

    def test_stop_during_failure_still_aborts(self):
        state, calls, errors = self._run_case("coins", False, abort_after_fail=True)
        self.assertTrue(state.abort_event.is_set())
        self.assertTrue(state.stop_event.is_set())
        self.assertNotIn("keypad", calls)
        self.assertTrue(errors)

    def test_idle_and_standalone_jobs_reject_fail(self):
        host = "operator-fail-idle"
        state = jobs.JobState(host)
        with jobs._registry_lock:
            jobs._states[host] = state
        try:
            state.current_device = "coins"
            self.assertFalse(jobs.fail_operator_subtest(host, "coins"))
            state.status = "running"
            state.current_program = "operator_coins"
            self.assertFalse(jobs.fail_operator_subtest(host, "coins"))
        finally:
            with jobs._registry_lock:
                jobs._states.pop(host, None)


if __name__ == "__main__":
    unittest.main()
