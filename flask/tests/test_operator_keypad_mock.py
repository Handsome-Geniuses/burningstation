import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


FLASK_DIR = Path(__file__).resolve().parents[1]


class OperatorKeypadMockTests(unittest.TestCase):
    def run_python(self, source: str, *, profile: str = "full"):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(FLASK_DIR),
            "HARDWARE_PROFILE": profile,
            "MOCK": "1",
        })
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=FLASK_DIR,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"subprocess failed with exit code {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}"
            )
        return result

    def test_operator_keypad_sse_payload_contains_layout_fields(self):
        result = self.run_python(
            """
            import importlib
            import time
            from unittest.mock import patch

            from lib.automation.shared_state import SharedState
            keypad = importlib.import_module("lib.automation.tests.test_operator_keypad")

            class Meter:
                host = "192.168.9.240"

            state = keypad.OperatorKeypadRunState(
                expected_buttons=["1", "ACCEPT"],
                required_per_button=2,
                start_epoch_s=time.time(),
                start_monotonic_s=time.monotonic(),
            )
            state.confirmed_counts["1"] = 1
            state.accepted_presses.append({"button": "1"})
            shared = SharedState()
            shared.last_error = ""

            with patch.object(keypad.SSEQM, "broadcast") as broadcast:
                keypad._broadcast_keypad_state(Meter(), shared, state)

            event, payload = broadcast.call_args.args
            assert event == "operator_keypad", event
            assert payload["expected_buttons"] == ["1", "ACCEPT"], payload
            assert payload["latest_button"] == "1", payload
            assert payload["counts"] == {"1": 1, "ACCEPT": 0}, payload
            assert payload["required_per_button"] == 2, payload
            assert payload["current"] == 1, payload
            assert payload["total"] == 4, payload
            print("payload-ok")
            """
        )
        self.assertIn("payload-ok", result.stdout)

    def test_mock_journal_cursor_path_feeds_existing_keypad_test(self):
        result = self.run_python(
            """
            import threading
            import time

            import tools.mock as mock
            from lib.automation.shared_state import SharedState
            from lib.automation.tests.test_operator_keypad import test_operator_keypad
            from lib.meter.ssh_meter import SSHMeter

            meter = SSHMeter("192.168.9.241")
            shared = SharedState()
            shared.last_error = ""

            def press_buttons():
                deadline = time.time() + 2
                while meter.host not in mock._mock_keypad_page_hosts:
                    if time.time() > deadline:
                        raise AssertionError("keypad page was not reached")
                    time.sleep(0.01)
                mock.append_mock_operator_keypad_press(meter.host, "1")
                mock.append_mock_operator_keypad_press(meter.host, "ACCEPT")

            thread = threading.Thread(target=press_buttons, daemon=True)
            thread.start()
            test_operator_keypad(
                meter,
                shared,
                buttons=["1", "ACCEPT"],
                job_count=1,
                max_duration_s=3,
                poll_s=0.02,
                page_timeout_s=0.1,
            )
            thread.join(timeout=1)
            assert shared.device_meta["keypad"]["status"] == "pass", shared.device_meta
            print("mock-parser-ok")
            """
        )
        self.assertIn("mock-parser-ok", result.stdout)

    def test_kbd_controller_outer_buttons_are_canonicalized(self):
        result = self.run_python(
            """
            import threading
            import time

            import tools.mock as mock
            from lib.automation.shared_state import SharedState
            from lib.automation.tests.test_operator_keypad import (
                _canonical_keypad_button,
                test_operator_keypad,
            )
            from lib.meter.ssh_meter import SSHMeter

            assert _canonical_keypad_button("HELP", "KBD_CONTROLLER") == "MAX"
            assert _canonical_keypad_button("MAX", "KBD_CONTROLLER") == "HELP"
            assert _canonical_keypad_button("HELP", "KEY_PAD_2") == "HELP"

            meter = SSHMeter("192.168.9.249")
            shared = SharedState()
            shared.last_error = ""

            def press_buttons():
                deadline = time.time() + 2
                while meter.host not in mock._mock_keypad_page_hosts:
                    if time.time() > deadline:
                        raise AssertionError("keypad page was not reached")
                    time.sleep(0.01)
                max_press = mock.append_mock_operator_keypad_press(meter.host, "MAX")
                help_press = mock.append_mock_operator_keypad_press(meter.host, "HELP")
                assert max_press["raw_button"] == "HELP", max_press
                assert help_press["raw_button"] == "MAX", help_press

            thread = threading.Thread(target=press_buttons, daemon=True)
            thread.start()
            test_operator_keypad(
                meter,
                shared,
                buttons=["MAX", "HELP"],
                job_count=1,
                max_duration_s=3,
                poll_s=0.02,
                page_timeout_s=0.1,
            )
            thread.join(timeout=1)
            meta = shared.device_meta["keypad"]
            assert meta["status"] == "pass", meta
            assert meta["confirmed_counts"]["MAX"] == 1, meta
            assert meta["confirmed_counts"]["HELP"] == 1, meta
            print("kbd-controller-remap-ok")
            """
        )
        self.assertIn("kbd-controller-remap-ok", result.stdout)

    def test_mock_operator_keypad_job_completes_and_stop_job_cancels_cleanly(self):
        result = self.run_python(
            """
            import time

            import tools.mock as mock
            from lib.automation import jobs
            from lib.meter.meter_manager import METERMANAGER as mm
            from lib.meter.ssh_meter import SSHMeter

            def register_mock_meter(host):
                meter = SSHMeter(host)
                mm.meters[host] = meter
                mock._mock_meter_ips.add(host)
                return meter

            jobs.insert_meter_jobs = lambda *args, **kwargs: []
            original_run_test_job = jobs.run_test_job
            jobs.run_test_job = lambda *args, **kwargs: original_run_test_job(
                *args,
                **{**kwargs, "log": False, "verbose": False},
            )
            jobs.store.load()
            jobs.store.settings.operator.job_counts.keypad = 1

            host = "192.168.9.242"
            meter = register_mock_meter(host)

            ok, msg = jobs.start_operator_keypad_job(host)
            assert ok, msg

            deadline = time.time() + 3
            while host not in mock._mock_keypad_page_hosts:
                if time.time() > deadline:
                    raise AssertionError("operator_keypad did not reach keypad page")
                time.sleep(0.01)

            buttons = [button.upper() for button in jobs.get_default_buttons(meter.module_info, meter.meter_type)]
            for button in buttons:
                mock.append_mock_operator_keypad_press(host, button)

            deadline = time.time() + 5
            while meter.status != "ready":
                if time.time() > deadline:
                    raise AssertionError(f"meter did not return ready: {meter.status}")
                time.sleep(0.02)

            state = jobs._state(host)
            assert state.status == "finished", jobs.job_status(host)
            assert state.result == "pass", jobs.job_status(host)
            assert state.device_results["keypad"] == "pass", state.device_results
            assert meter.results["keypad"] == "pass", meter.results

            cancel_host = "192.168.9.243"
            cancel_meter = register_mock_meter(cancel_host)
            ok, msg = jobs.start_job(
                cancel_host,
                "operator_keypad",
                {"job_count": 1, "buttons": ["1"], "poll_s": 0.02, "max_duration_s": 5},
                log=False,
                verbose=False,
            )
            assert ok, msg
            deadline = time.time() + 2
            while cancel_meter.status != "busy":
                if time.time() > deadline:
                    raise AssertionError("cancel meter did not become busy")
                time.sleep(0.01)

            jobs.stop_job(cancel_host)
            assert cancel_meter.status == "ready", cancel_meter.status
            assert jobs._state(cancel_host).stop_event.is_set()
            print("mock-job-ok")
            """
        )
        self.assertIn("mock-job-ok", result.stdout)

    def test_portable_mock_full_operator_job_is_simulated_and_stoppable(self):
        result = self.run_python(
            """
            import time

            from app import app
            import tools.mock as mock
            from lib.meter.meter_manager import METERMANAGER as mm
            from lib.meter.ssh_meter import SSHMeter

            host = "192.168.9.244"
            meter = SSHMeter(host)
            mm.meters[host] = meter
            mock._mock_meter_ips.add(host)
            client = app.test_client()

            response = client.post(
                "/api/system/program/manual",
                json={"program": "start_operator_job", "meter_ip": host},
            )
            assert response.status_code in (200, 202), response.get_data(as_text=True)
            deadline = time.time() + 2
            while meter.status != "busy":
                if time.time() > deadline:
                    raise AssertionError(f"operator did not start: {meter.status}")
                time.sleep(0.01)
            assert meter.status == "busy", meter.status
            assert host in mock._mock_operator_timers
            assert host not in mock._mock_keypad_page_hosts
            time.sleep(0.1)

            response = client.post(
                "/api/system/program/manual",
                json={"program": "stop_operator_job", "meter_ip": host},
            )
            assert response.status_code in (200, 202), response.get_data(as_text=True)
            deadline = time.time() + 2
            while meter.status != "ready":
                if time.time() > deadline:
                    raise AssertionError(f"operator did not stop: {meter.status}")
                time.sleep(0.01)
            assert meter.status == "ready", meter.status
            assert host not in mock._mock_operator_timers
            print("portable-mock-operator-ok")
            """,
            profile="portable",
        )
        self.assertIn("portable-mock-operator-ok", result.stdout)

    def test_portable_mock_add_meter_registers_without_refresh_discovery(self):
        result = self.run_python(
            """
            import tools.mock as mock
            from lib.meter.meter_manager import METERMANAGER as mm

            payload = mock.add_mock_meter("192.168.9.245")
            meters = mock.list_mock_meters()

            assert payload["status"] == "added", payload
            assert payload["ip"] == "192.168.9.245", payload
            assert "192.168.9.245" in mm.meters
            assert len(meters) == 1, meters
            assert meters[0]["hostname"] == "30000245", meters
            print("portable-mock-add-meter-ok")
            """,
            profile="portable",
        )
        self.assertIn("portable-mock-add-meter-ok", result.stdout)

    def test_standalone_operator_keypad_db_rows_preserve_status_and_reason(self):
        result = self.run_python(
            """
            import tools.mock as mock
            from lib.automation import jobs
            from lib.meter.meter_manager import METERMANAGER as mm
            from lib.meter.ssh_meter import SSHMeter

            captured = []
            jobs.insert_meter_jobs = lambda meter_id, job_rows, jctl: captured.extend(job_rows) or []

            def register_mock_meter(host):
                meter = SSHMeter(host)
                mm.meters[host] = meter
                mock._mock_meter_ips.add(host)
                meter.db_id = mock.MOCK_DB_ID
                return meter

            def write_keypad_row(
                host,
                *,
                result,
                keypad_status,
                stop=False,
                last_error="",
                failure_reason="",
                meta_error="",
            ):
                meter = register_mock_meter(host)
                st = jobs._state(host)
                st.reset()
                st.current_program = "operator_keypad"
                st.result = result
                st.last_error = last_error or None
                st.device_results["keypad"] = keypad_status
                st.device_meta["keypad"] = {
                    "status": keypad_status,
                    "error": meta_error,
                    "expected_buttons": ["1"],
                    "required_per_button": 1,
                    "confirmed_counts": {"1": 0 if keypad_status == "fail" else 1},
                    "missing": {"1": 1} if keypad_status == "fail" else {},
                    "duration_s": 0.1,
                }
                st.extras["kwargs"] = {"buttons": ["1"], "job_count": 1}
                if failure_reason:
                    st.extras["failure_reason"] = failure_reason
                if stop:
                    st.stop_event.set()

                meter.results["operator_keypad"] = result
                meter.results["keypad"] = keypad_status

                captured.clear()
                jobs.job_done(host)
                assert len(captured) == 1, captured
                return captured[0]

            passed = write_keypad_row(
                "192.168.9.246",
                result="pass",
                keypad_status="pass",
            )
            assert passed["name"] == "operator_keypad", passed
            assert passed["status"] == "pass", passed
            assert passed["data"]["results"]["keypad"]["status"] == "pass", passed
            assert "failure_reason" not in passed["data"], passed
            assert "error" not in passed["data"]["results"]["keypad"], passed

            manually_stopped = write_keypad_row(
                "192.168.9.247",
                result="fail",
                keypad_status="fail",
                stop=True,
                last_error="Stop event triggered",
                failure_reason="manually stopped",
                meta_error="Stop event triggered",
            )
            assert manually_stopped["status"] == "fail", manually_stopped
            assert manually_stopped["data"]["failure_reason"] == "manually stopped; missing={'1': 1}", manually_stopped
            assert manually_stopped["data"]["results"]["keypad"]["status"] == "fail", manually_stopped
            assert manually_stopped["data"]["results"]["keypad"]["error"] == "manually stopped; missing={'1': 1}", manually_stopped

            timeout_reason = "max duration exceeded (0.1s); missing={'1': 1}"
            timed_out = write_keypad_row(
                "192.168.9.248",
                result="fail",
                keypad_status="fail",
                stop=True,
                last_error=timeout_reason,
                meta_error=timeout_reason,
            )
            assert timed_out["status"] == "fail", timed_out
            assert timed_out["data"]["failure_reason"].startswith("max duration exceeded"), timed_out
            assert timed_out["data"]["results"]["keypad"]["error"].startswith("max duration exceeded"), timed_out
            assert timed_out["data"]["device_meta"]["keypad"]["missing"] == {"1": 1}, timed_out
            print("operator-keypad-db-status-ok")
            """
        )
        self.assertIn("operator-keypad-db-status-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
