import queue
import importlib
import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


FLASK_DIR = Path(__file__).resolve().parents[1]
if str(FLASK_DIR) not in sys.path:
    sys.path.insert(0, str(FLASK_DIR))

class StopAutomation(Exception):
    pass


class SharedState:
    def __init__(self):
        self.logs = []
        self.last_error = ""
        self.device_results = {}
        self.device_meta = {}
        self.stop_event = threading.Event()
        self.end_listener = threading.Event()
        self.logfile_path = "test.log"

    def log(self, message, **_kwargs):
        self.logs.append(message)

    def broadcast_progress(self, *_args, **_kwargs):
        pass


helpers_module = types.ModuleType("lib.automation.helpers")
helpers_module.StopAutomation = StopAutomation
helpers_module.check_stop_event = lambda _shared: None
shared_module = types.ModuleType("lib.automation.shared_state")
shared_module.SharedState = SharedState
meter_module = types.ModuleType("lib.meter.ssh_meter")
meter_module.SSHMeter = object
robot_module = types.ModuleType("lib.robot.robot_client")
robot_module.RobotClient = object
solar_module = types.ModuleType("lib.automation.tests.test_solar")
solar_module.test_solar = lambda *_args, **_kwargs: None
sys.modules.update(
    {
        "lib.automation.helpers": helpers_module,
        "lib.automation.shared_state": shared_module,
        "lib.meter.ssh_meter": meter_module,
        "lib.robot.robot_client": robot_module,
        "lib.automation.tests.test_solar": solar_module,
    }
)

MODULE_PATH = FLASK_DIR / "lib" / "automation" / "tests" / "test_robot_keypad.py"
spec = importlib.util.spec_from_file_location("robot_keypad_under_test", MODULE_PATH)
keypad = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = keypad
spec.loader.exec_module(keypad)


class RobotKeypadPlanTests(unittest.TestCase):
    def test_plan_expands_offsets_and_centered_probes_in_order(self):
        buttons, plan, required = keypad._build_press_plan(
            ["BACK", "POUND", "ENTER"],
            job_count=1,
            verify_stuck=True,
            back_enter_offsets_mm=[[-5, 1], [-5, 1], [0, 0]],
        )

        self.assertEqual(buttons, ["BACK", "POUND", "ENTER"])
        self.assertEqual(
            [(step["button_name"], step["role"], step["offset_mm"]) for step in plan],
            [
                ("BACK", "target", [-5.0, 1.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
                ("BACK", "target", [-5.0, 1.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
                ("BACK", "target", [0.0, 0.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
                ("POUND", "standard", [0.0, 0.0]),
                ("ENTER", "target", [-5.0, 1.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
                ("ENTER", "target", [-5.0, 1.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
                ("ENTER", "target", [0.0, 0.0]),
                ("POUND", "stuck_probe", [0.0, 0.0]),
            ],
        )
        self.assertEqual(required, {"BACK": 3, "POUND": 1, "ENTER": 3})
        self.assertEqual([step["logical_index"] for step in plan], list(range(1, 14)))
        self.assertTrue(all(step["planned_total"] == 13 for step in plan))

    def test_offsets_still_expand_when_verification_is_disabled(self):
        _, plan, required = keypad._build_press_plan(
            ["BACK"],
            job_count=2,
            verify_stuck=False,
            back_enter_offsets_mm=[[-5, 0], [5, 0]],
        )
        self.assertEqual([step["button_name"] for step in plan], ["BACK"] * 4)
        self.assertFalse(any(step["role"] == "stuck_probe" for step in plan))
        self.assertEqual(required, {"BACK": 4})

    def test_offset_validation_rejects_malformed_and_boundary_values(self):
        invalid_values = [
            [],
            [[0]],
            [[0, 0, 0]],
            [[12.75, 0]],
            [[-12.75, 0]],
            [[0, 5]],
            [[0, -5]],
            [[float("nan"), 0]],
            [[True, 0]],
        ]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                keypad._validate_back_enter_offsets(value)

    def test_page_state_and_maintenance_prime_or_recover(self):
        meter = Mock(host="192.0.2.1")
        shared = SharedState()
        html = f"<div>{keypad.KEYPAD_PAGE}</div>{keypad.KEYPAD_EXIT_PRIME_TEXT}"
        response = Mock(text=html)
        response.raise_for_status.return_value = None
        with patch.object(keypad.requests, "get", return_value=response):
            state = keypad._maintain_keypad_page(meter, shared)
        self.assertTrue(state.is_keypad_page)
        self.assertTrue(state.requires_back_prime)
        meter.press.assert_called_once_with("BACK")
        meter.goto_keypad.assert_not_called()

        meter.reset_mock()
        response.text = "not the keypad page"
        with patch.object(keypad.requests, "get", return_value=response):
            state = keypad._maintain_keypad_page(meter, shared)
        self.assertFalse(state.is_keypad_page)
        meter.goto_keypad.assert_called_once_with()

        meter.reset_mock()
        response.text = f"<div>{keypad.KEYPAD_PAGE}</div>"
        with patch.object(keypad.requests, "get", return_value=response):
            state = keypad._maintain_keypad_page(meter, shared)
        self.assertTrue(state.is_keypad_page)
        self.assertFalse(state.requires_back_prime)
        meter.press.assert_not_called()
        meter.goto_keypad.assert_not_called()

        meter.reset_mock()
        with patch.object(keypad.requests, "get", side_effect=TimeoutError("fetch failed")):
            state = keypad._maintain_keypad_page(meter, shared)
        self.assertFalse(state.is_keypad_page)
        meter.goto_keypad.assert_called_once_with()

    @staticmethod
    def _make_state():
        buttons, plan, required = keypad._build_press_plan(
            ["BACK"],
            job_count=1,
            verify_stuck=True,
            back_enter_offsets_mm=[[5, 0]],
        )
        return keypad.KeypadRunState(
            expected_buttons=buttons,
            required_per_button=1,
            start_epoch_s=time.time(),
            start_monotonic_s=time.monotonic(),
            initial_journal_cursor="cursor-0",
            stop_on_failure=False,
            journal_after_buffer_s=0,
            press_plan=plan,
            requested_required_counts=required,
        )

    @staticmethod
    def _feed_group_events(state):
        events = queue.Queue()
        old_mono = time.monotonic() - 10
        old_epoch = time.time() - 10
        for step in state.press_plan:
            common = {
                "step_id": step["step_id"],
                "group_id": step["group_id"],
                "group_attempt": 1,
                "button_name": step["button_name"],
                "role": step["role"],
                "offset_mm": step["offset_mm"],
                "job_count_number": 1,
                "logical_index": step["logical_index"],
                "attempt": 1,
            }
            events.put({"received_epoch_s": old_epoch, "received_monotonic_s": old_mono, "data": {**common, "action": "pressing"}})
            events.put({"received_epoch_s": old_epoch, "received_monotonic_s": old_mono, "data": {**common, "action": "pressed", "pressed": True}})
            if step["role"] == "stuck_probe":
                events.put(
                    {
                        "received_epoch_s": old_epoch,
                        "received_monotonic_s": old_mono,
                        "data": {**common, "action": "awaiting_group_resolution"},
                    }
                )
        keypad._handle_structured_robot_events(events, SharedState(), state)

    @staticmethod
    def _entry(button, number):
        return {
            "entry_id": f"entry-{number}",
            "button_name": button,
            "src": "KEY_PAD_2",
            "journal_cursor": f"cursor-{number}",
            "timestamp_text": f"timestamp-{number}",
            "message": f"KEY_PRESSED: {button}, isAutoRepeat=false, from KEY_PAD_2",
            "raw_line": f"raw-{button}-{number}",
        }

    def test_successful_group_counts_target_but_not_probe_pound(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("BACK", 1), self._entry("POUND", 2)]
        shared = SharedState()
        robot = Mock()
        robot.resolve_button_group.return_value = {"accepted": True}

        keypad._match_structured_batches(
            Mock(), shared, state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        self.assertEqual(state.progress_current, 2)
        self.assertEqual(state.confirmed_counts, {"BACK": 1})
        self.assertEqual(len(state.completed_group_ids), 1)
        self.assertEqual(robot.resolve_button_group.call_args.kwargs["resolution"], "pass")

    def test_probe_reported_as_back_fails_as_stuck(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("BACK", 1), self._entry("BACK", 2)]
        shared = SharedState()

        with self.assertRaises(StopAutomation):
            keypad._match_structured_batches(
                Mock(), shared, state, robot=Mock(), job_id="1",
                per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
            )
        self.assertIn("STUCK KEYPAD BUTTON DETECTED", state.final_error)
        self.assertIn("[5.0, 0.0]", state.final_error)

    def test_missing_target_with_pound_retries_the_whole_group(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("POUND", 1)]
        shared = SharedState()
        robot = Mock()
        robot.resolve_button_group.return_value = {"accepted": True}

        keypad._match_structured_batches(
            Mock(), shared, state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        kwargs = robot.resolve_button_group.call_args.kwargs
        self.assertEqual(kwargs["resolution"], "retry")
        self.assertEqual(kwargs["group_id"], state.press_plan[0]["group_id"])
        self.assertEqual(state.group_retry_counts[kwargs["group_id"]], 1)
        self.assertEqual(state.progress_current, 0)

    def test_registered_target_with_obstructed_probe_retries_without_false_stuck(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("BACK", 1)]
        robot = Mock()
        robot.resolve_button_group.return_value = {"accepted": True}

        keypad._match_structured_batches(
            Mock(), SharedState(), state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        kwargs = robot.resolve_button_group.call_args.kwargs
        self.assertEqual(kwargs["resolution"], "retry")
        self.assertEqual(state.attempt_history[0].result, "group_retry_queued")
        self.assertNotIn("STUCK KEYPAD BUTTON DETECTED", state.final_error)

    def test_obstructed_probe_fails_when_group_retry_budget_is_exhausted(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("BACK", 1)]
        robot = Mock()

        with self.assertRaises(StopAutomation):
            keypad._match_structured_batches(
                Mock(), SharedState(), state, robot=robot, job_id="1",
                per_button_timeout_s=5, max_retries_per_group=0, retry_command_timeout_s=1,
            )
        robot.resolve_button_group.assert_not_called()

    def test_group_waits_for_full_settle_window_before_pass(self):
        state = self._make_state()
        state.journal_after_buffer_s = 3.5
        self._feed_group_events(state)
        batch = next(iter(state.attempt_batches.values()))
        batch["barrier_received_monotonic_s"] = time.monotonic() - 1
        for attempt in batch["attempts"].values():
            attempt.pressed_monotonic_s = time.monotonic() - 10
        state.journal_backlog = [self._entry("BACK", 1), self._entry("POUND", 2)]
        robot = Mock()

        keypad._match_structured_batches(
            Mock(), SharedState(), state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        robot.resolve_button_group.assert_not_called()
        self.assertEqual(state.progress_current, 0)

    def test_delayed_target_after_confirmed_probe_is_stuck(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [
            self._entry("BACK", 1),
            self._entry("POUND", 2),
            self._entry("BACK", 3),
        ]

        with self.assertRaises(StopAutomation):
            keypad._match_structured_batches(
                Mock(), SharedState(), state, robot=Mock(), job_id="1",
                per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
            )

    def test_group_resolution_command_timeout_retries_idempotently(self):
        state = self._make_state()
        self._feed_group_events(state)
        state.journal_backlog = [self._entry("BACK", 1), self._entry("POUND", 2)]
        robot = Mock()
        robot.resolve_button_group.side_effect = [
            TimeoutError("response lost"),
            {"accepted": True, "already_resolved": True},
        ]

        keypad._match_structured_batches(
            Mock(), SharedState(), state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        self.assertEqual(robot.resolve_button_group.call_count, 2)
        self.assertEqual(state.progress_current, 2)
        self.assertTrue(state.group_barrier_history[0]["response"]["already_resolved"])

    def test_missing_barrier_event_fails_instead_of_matching_future_evidence(self):
        state = self._make_state()
        self._feed_group_events(state)
        batch = next(iter(state.attempt_batches.values()))
        batch["barrier_waiting"] = False
        batch["barrier_received_monotonic_s"] = None
        state.group_barrier_history.clear()
        state.journal_backlog = [self._entry("BACK", 1), self._entry("POUND", 2)]

        with self.assertRaises(StopAutomation):
            keypad._match_structured_batches(
                Mock(), SharedState(), state, robot=Mock(), job_id="1",
                per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
            )

    def test_standard_step_retry_remains_on_legacy_retry_command(self):
        buttons, plan, required = keypad._build_press_plan(
            ["1"], job_count=1, verify_stuck=True, back_enter_offsets_mm=[[0, 0]]
        )
        state = keypad.KeypadRunState(
            expected_buttons=buttons,
            required_per_button=1,
            start_epoch_s=time.time(),
            start_monotonic_s=time.monotonic(),
            initial_journal_cursor="cursor-0",
            stop_on_failure=False,
            journal_after_buffer_s=0,
            press_plan=plan,
            requested_required_counts=required,
        )
        self._feed_group_events(state)
        robot = Mock()
        robot.request_button_retry.return_value = {"accepted": True}

        keypad._match_structured_batches(
            Mock(), SharedState(), state, robot=robot, job_id="1",
            per_button_timeout_s=5, max_retries_per_group=1, retry_command_timeout_s=1,
        )

        robot.request_button_retry.assert_called_once()
        robot.resolve_button_group.assert_not_called()


if __name__ == "__main__":
    unittest.main()
