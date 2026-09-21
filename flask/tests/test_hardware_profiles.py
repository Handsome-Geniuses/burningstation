import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


FLASK_DIR = Path(__file__).resolve().parents[1]


class HardwareProfileSmokeTests(unittest.TestCase):
    def run_python(self, source: str, *, profile: str, mock: str):
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(FLASK_DIR),
            "HARDWARE_PROFILE": profile,
            "MOCK": mock,
        })
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=FLASK_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_portable_imports_app_without_station_io(self):
        result = self.run_python(
            """
            import app
            print("import-ok")
            """,
            profile="portable",
            mock="0",
        )
        self.assertIn("import-ok", result.stdout)

    def test_portable_hardware_endpoint_reports_disabled_station_capabilities(self):
        result = self.run_python(
            """
            from app import app

            client = app.test_client()
            payload = client.get("/api/system/hardware").get_json()
            assert payload["hardware"]["profile"] == "portable", payload
            capabilities = payload["hardware"]["capabilities"]
            for name in ("belt", "motor_control", "i2c", "meter_detection", "tower", "lamp", "auto_mode"):
                assert capabilities[name] is False, (name, capabilities)
            print("hardware-ok")
            """,
            profile="portable",
            mock="0",
        )
        self.assertIn("hardware-ok", result.stdout)

    def test_device_ip_endpoint_reports_request_host_ip(self):
        result = self.run_python(
            """
            from app import app

            client = app.test_client()
            response = client.get(
                "/api/system/device/ip-addresses",
                headers={"Host": "192.0.2.10:8010"},
            )
            payload = response.get_json()
            assert response.status_code == 200, response.get_data(as_text=True)
            assert payload["request_host"] == "192.0.2.10", payload
            assert isinstance(payload["hostname"], str), payload
            assert isinstance(payload["addresses"], list), payload
            assert any(
                address["address"] == "192.0.2.10" and address["source"] == "request"
                for address in payload["addresses"]
            ), payload
            print("device-ip-ok")
            """,
            profile="portable",
            mock="0",
        )
        self.assertIn("device-ip-ok", result.stdout)

    def test_portable_station_actions_return_capability_unavailable(self):
        result = self.run_python(
            """
            from app import app

            client = app.test_client()
            checks = [
                ("/api/system/override/motor", {"value_list": [1, 0, 0]}, "motor_control"),
                ("/api/system/station/load", {"type": "L"}, "belt"),
                ("/api/system/station/mode", {"value": "auto"}, "auto_mode"),
            ]
            for path, payload, capability in checks:
                response = client.post(path, json=payload)
                body = response.get_json()
                assert response.status_code == 409, (path, response.status_code, response.get_data(as_text=True))
                assert body["capability"] == capability, (path, body)
            print("unavailable-ok")
            """,
            profile="portable",
            mock="0",
        )
        self.assertIn("unavailable-ok", result.stdout)

    def test_full_mock_allows_simulated_motor_override(self):
        result = self.run_python(
            """
            from app import app

            client = app.test_client()
            payload = client.get("/api/system/hardware").get_json()
            assert payload["hardware"]["profile"] == "full", payload
            assert payload["hardware"]["capabilities"]["motor_control"] is True, payload

            response = client.post("/api/system/override/motor", json={"value_list": [1, 0, 0]})
            assert response.status_code == 200, response.get_data(as_text=True)
            print("full-mock-ok")
            """,
            profile="full",
            mock="1",
        )
        self.assertIn("full-mock-ok", result.stdout)

    def test_portable_mock_still_rejects_disabled_belt_actions(self):
        result = self.run_python(
            """
            from app import app

            client = app.test_client()
            response = client.post("/api/system/station/load", json={"type": "L"})
            body = response.get_json()
            assert response.status_code == 409, (response.status_code, response.get_data(as_text=True))
            assert body["capability"] == "belt", body
            print("portable-mock-unavailable-ok")
            """,
            profile="portable",
            mock="1",
        )
        self.assertIn("portable-mock-unavailable-ok", result.stdout)

    def test_devwo_wipe_sim_action_works_with_or_without_mock(self):
        source = """
        import os

        from lib import database
        from lib.system import sim

        if os.environ["MOCK"] == "1":
            import tools.mock

        calls = []
        database.delete_meter_jobs_for_work_order = lambda work_order: calls.append(work_order) or 7

        payload, status = sim.on_action("wipe_devwo_jobs")
        assert status == 200, (status, payload)
        assert payload == {"status": "deleted", "work_order": 999999999, "count": 7}, payload
        assert calls == [999999999], calls
        print(f"devwo-wipe-ok-mock-{os.environ['MOCK']}")
        """

        for mock in ("0", "1"):
            with self.subTest(mock=mock):
                result = self.run_python(source, profile="portable", mock=mock)
                self.assertIn(f"devwo-wipe-ok-mock-{mock}", result.stdout)


if __name__ == "__main__":
    unittest.main()
