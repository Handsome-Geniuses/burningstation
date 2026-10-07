"""Automatic passive simulation through the normal job lifecycle."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

FLASK_DIR = Path(__file__).resolve().parents[1]
SETUP = '''
import time
from copy import deepcopy
from unittest.mock import Mock, patch
import tools.mock as mock
from lib.automation import jobs, mock_meter
from lib.automation.tests import cycle_all
from lib.meter.meter_manager import METERMANAGER as mm
from lib.sse.sse_queue_manager import SSEQM
host = "192.168.69.900"
meter = mock.SSHMeter(host)
meter.db_id = 42
mm.meters[host] = meter
names = [name for name, _, _ in cycle_all.DEVICES]
configs = {name: {"job_count": 1} for name in names}
configs.update(numBurnCycles=1, numBurnDelay=0)
def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for job state"
        time.sleep(.01)
'''


class MockPassiveTests(unittest.TestCase):
    def run_python(self, source):
        result = subprocess.run(
            [sys.executable, "-c", SETUP + textwrap.dedent(source)], cwd=FLASK_DIR,
            env={**os.environ, "PYTHONPATH": str(FLASK_DIR), "HARDWARE_PROFILE": "portable", "MOCK": "1"},
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fail_button_fails_current_call_in_and_records_reason(self):
        self.run_python('''
            from app import app
            for name in names: configs[name]["job_count"] = int(name == "call in")
            client = app.test_client()
            with patch.object(jobs, "build_passive_kwargs", return_value=configs), \\
                 patch.object(jobs, "insert_meter_jobs") as save, \\
                 patch.object(jobs, "_handle_auto_job_done"), \\
                 patch.object(mock_meter, "PASSIVE_STAGE_SECONDS", .1):
                assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": "old"}).status_code == 409
                mock._mock_start_passive_job(host)
                wait_for(lambda: meter.virtual_meter.snapshot()["device"] == "call in")
                session = meter.virtual_meter.snapshot()["session"]
                assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": "old"}).status_code == 409
                response = client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": session})
                assert response.status_code == 200
                jobs._threads[host].join(5)
                assert not jobs._threads[host].is_alive()
                assert jobs._state(host).device_results["call in"] == "fail"
                assert jobs._state(host).result == "fail"
                row = save.call_args.args[1][0]
                assert row["status"] == "fail"
                assert "Mock failure injected for call in" in row["data"]["failure_reason"]
                assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": session}).status_code == 409
        ''')

    def test_fail_button_targets_only_the_active_operator_session(self):
        self.run_python('''
            import threading
            from app import app
            from lib.automation.mock_meter import run_virtual_test
            from lib.automation.helpers import StopAutomation
            second = mock.SSHMeter("192.168.69.901")
            mm.meters[second.host] = second
            second.virtual_meter.begin("touchscreen")
            other_session = second.virtual_meter.snapshot()["session"]
            other_state = jobs._state(second.host)
            other_state.status = "running"
            state = jobs._state(host)
            state.reset()
            state.status = "running"
            errors = []
            def run():
                try:
                    run_virtual_test(meter, state, "touchscreen", lambda *a, **k: None,
                        {"job_count": 1, "expected_touch_count": 5, "max_duration_s": 5})
                except StopAutomation as exc:
                    errors.append(str(exc))
            worker = threading.Thread(target=run)
            worker.start()
            wait_for(lambda: meter.virtual_meter.snapshot()["device"] == "touchscreen")
            client = app.test_client()
            session = meter.virtual_meter.snapshot()["session"]
            assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": other_session}).status_code == 409
            assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": session}).status_code == 200
            worker.join(3)
            assert not worker.is_alive()
            assert errors == ["Mock failure injected for touchscreen"]
            assert second.virtual_meter.snapshot()["session"] == other_session
            assert not other_state.stop_event.is_set()
        ''')

    def test_injected_failure_continues_full_passive_when_configured(self):
        self.run_python('''
            from app import app
            for name in names: configs[name]["job_count"] = int(name in {"nfc", "printer"})
            configs["stop_on_fail"] = False
            client = app.test_client()
            with patch.object(jobs, "build_passive_kwargs", return_value=configs), \\
                 patch.object(jobs, "insert_meter_jobs") as save, \\
                 patch.object(jobs, "_handle_auto_job_done"), \\
                 patch.object(mock_meter, "PASSIVE_STAGE_SECONDS", .1):
                mock._mock_start_passive_job(host)
                wait_for(lambda: meter.virtual_meter.snapshot()["device"] == "nfc")
                session = meter.virtual_meter.snapshot()["session"]
                assert client.post(f"/api/system/mockmeter/{host}", json={"kind": "fail", "session": session}).status_code == 200
                jobs._threads[host].join(5)
                assert not jobs._threads[host].is_alive()
                assert jobs._state(host).device_results["nfc"] == "fail"
                assert jobs._state(host).device_results["printer"] == "pass"
                assert jobs._state(host).result == "fail"
                assert save.call_args.args[1][0]["status"] == "fail"
        ''')

    def test_normal_route_runs_all_subtests_counts_cycles_and_records_job(self):
        self.run_python('''
            from app import app
            configs["numBurnCycles"] = 2
            configs["numBurnDelay"] = .05
            for name in names: configs[name]["job_count"] = 2
            events = []
            def broadcast(event, payload): events.append((event, deepcopy(payload)))
            with patch.object(jobs, "build_passive_kwargs", return_value=configs), \
                 patch.object(jobs, "insert_meter_jobs") as save, \
                 patch.object(jobs, "_handle_auto_job_done") as auto, \
                 patch.object(SSEQM, "broadcast", side_effect=broadcast), \
                 patch.object(mock_meter, "PASSIVE_STAGE_SECONDS", .001), \
                 patch.object(meter, "safe_exec_command", side_effect=AssertionError("Real hardware accessed")):
                response = app.test_client().post("/api/system/program/manual", json={"program": "start_passive_job", "meter_ip": host})
                assert response.status_code in (200, 202)
                wait_for(lambda: host in jobs._threads and jobs._threads[host].ident is not None)
                jobs._threads[host].join(12)
                assert not jobs._threads[host].is_alive()
                assert meter.status == "ready"
                save.assert_called_once()
                auto.assert_called_once_with(host, "cycle_all")
                row = save.call_args.args[1][0]
                assert row["name"] == "cycle_all" and row["status"] == "pass", row
                assert row["data"]["duration_s"] > 0
                assert all(row["data"]["results"][name]["status"] == "pass" for name in names)
                assert all(row["data"]["device_meta"][name]["completed"] == 2 for name in names)
                assert meter.virtual_meter.snapshot()["printed"] == 4
                completed = [p for e, p in events if e == "operator_feedback" and p["status"] == "pass"]
                assert [p["test"] for p in completed] == [f"passive_{name.replace(' ', '_')}" for name in names] * 2
                assert all(p["current"] == p["total"] == 2 for p in completed)
                assert any(e == "activity" and p["name"] == "cycle_all" for e, p in events)
                assert meter.virtual_meter.snapshot()["passive_phase"] is None
                assert meter.virtual_meter.snapshot()["session"] is None
        ''')

    def test_disabled_and_missing_subtests_and_real_dispatch(self):
        self.run_python('''
            configs["coin shutter"]["job_count"] = 0
            firmware = meter.device_firmware
            meter.device_firmware = lambda device: "" if device == "nfc" else firmware(device)
            shared = jobs.JobState(host)
            with patch.object(mock_meter, "PASSIVE_STAGE_SECONDS", .001), patch.object(cycle_all, "_cycle_wait") as wait:
                cycle_all.test_cycle_all(meter, shared, **configs)
            assert shared.device_results["coin shutter"] == "n/a"
            assert shared.device_results["nfc"] == "missing"
            assert all(shared.device_results[name] == "pass" for name in names[2:])
            assert "coin shutter" not in shared.device_meta and "nfc" not in shared.device_meta
            assert wait.call_args_list[-2].args[-1] == configs["numBurnDelay"]
            meter.is_mock = False
            real_test = Mock()
            with patch.object(mock_meter, "run_virtual_passive_test") as virtual:
                cycle_all._run_device(meter, shared, "printer", real_test, {"job_count": 3})
                real_test.assert_called_once()
                assert real_test.call_args.kwargs["job_count"] == 3
                virtual.assert_not_called()
        ''')

    def test_stop_and_disconnect_clear_visuals_without_running_next_subtest(self):
        self.run_python('''
            from app import app
            for disconnect in (False, True):
                with patch.object(jobs, "build_passive_kwargs", return_value=configs), \
                     patch.object(jobs, "insert_meter_jobs") as save, \
                     patch.object(jobs, "_handle_auto_job_done"):
                    mock._mock_start_passive_job(host)
                    wait_for(lambda: meter.virtual_meter.snapshot()["passive_phase"] == "opening")
                    if disconnect:
                        with patch.object(mm, "stale_meter"): mock.disconnect_mock_meter(host)
                    else:
                        response = app.test_client().post("/api/system/program/manual", json={"program": "stop_passive_job", "meter_ip": host})
                        assert response.status_code in (200, 202)
                    jobs._threads[host].join(2)
                    assert not jobs._threads[host].is_alive()
                    assert jobs._state(host).device_results["coin shutter"] == "fail"
                    assert jobs._state(host).device_results["nfc"] == "pending"
                    assert save.call_args.args[1][0]["status"] == "fail"
                    state = meter.virtual_meter.snapshot()
                    assert state["device"] is None and state["passive_phase"] is None
                    assert state["screen_color"] is None and state["session"] is None
        ''')

    def test_inputs_cannot_advance_passive_and_meters_are_isolated(self):
        self.run_python('''
            second = mock.SSHMeter("192.168.69.901")
            mm.meters[second.host] = second
            initial = second.virtual_meter.snapshot()
            with patch.object(jobs, "build_passive_kwargs", return_value=configs), \
                 patch.object(jobs, "insert_meter_jobs"), patch.object(jobs, "_handle_auto_job_done"):
                mock._mock_start_passive_job(host)
                wait_for(lambda: meter.virtual_meter.snapshot()["passive_phase"] == "opening")
                state = meter.virtual_meter.snapshot()
                for payload in ({"kind": "touch", "x": .5, "y": .5}, {"kind": "drop", "item": "USD-25", "target": "coin"}, {"kind": "drop", "item": "visa-1", "target": "nfc"}):
                    meter.virtual_meter.interact({**payload, "session": state["session"]})
                assert meter.virtual_meter.pop() is None
                assert jobs._state(host).extras["operator_feedback_state"]["current"] == 0
                assert second.virtual_meter.snapshot() == initial
                mock._mock_stop_passive_job(host)
                jobs._threads[host].join(2)
        ''')

    def test_cancel_during_cycle_delay_does_not_start_another_cycle(self):
        self.run_python('''
            configs["numBurnCycles"] = 2
            configs["numBurnDelay"] = 60
            for name in names[1:]: configs[name]["job_count"] = 0
            with patch.object(jobs, "build_passive_kwargs", return_value=configs), \
                 patch.object(jobs, "insert_meter_jobs"), patch.object(jobs, "_handle_auto_job_done"), \
                 patch.object(mock_meter, "PASSIVE_STAGE_SECONDS", .001):
                mock._mock_start_passive_job(host)
                wait_for(lambda: jobs._state(host).device_results.get("call in") == "n/a")
                mock._mock_stop_passive_job(host)
                jobs._threads[host].join(2)
                assert not jobs._threads[host].is_alive()
                assert jobs._state(host).result == "fail"
                assert meter.virtual_meter.snapshot()["message"] == "Test stopped or failed"
        ''')


if __name__ == "__main__": unittest.main()
