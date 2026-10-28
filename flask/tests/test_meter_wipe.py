"""Wipe policy checks in an isolated process without station hardware."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class MeterWipeTests(unittest.TestCase):
    def test_wipe_policy_and_cleanup(self):
        flask_dir = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent('''
                from unittest.mock import Mock, patch
                from lib.meter.meter_manager import METERMANAGER as mm
                from lib.system.states import states
                from lib.system.bay_guess import empty_bay_guess

                statuses = {
                    "connected-busy": "busy", "connected-idle": "ready",
                    "disconnected-busy": "busy", "disconnected-idle": "ready",
                }
                meters = {ip: Mock(status=status, hostname=ip) for ip, status in statuses.items()}
                mm.meters = meters.copy()
                mm._METERMANAGER__meters = set(meters)
                mm._METERMANAGER__stale_counts = dict.fromkeys(meters, 1)
                mm._METERMANAGER__attempts = dict.fromkeys(meters, 2)
                mm._METERMANAGER__splash = set(meters)
                states["bayGuess"] = empty_bay_guess()
                states["bayGuess"][2] = "disconnected-busy"

                with patch("ip_scanner.get_ips", return_value=["connected-busy", "connected-idle", "new-meter"]) as scan, \
                     patch.object(mm, "_METERMANAGER__on_fresh") as fresh, \
                     patch("lib.meter.meter_manager.SSEQM.broadcast") as broadcast:
                    result = mm.wipe()
                    assert result["preserved"] == ["connected-busy"], result
                    assert set(result["removed"]) == set(meters) - {"connected-busy"}, result
                    assert mm.list_meters() == ["connected-busy"]
                    assert list(mm.meters) == ["connected-busy"]
                    meters["connected-busy"].close.assert_not_called()
                    for ip in result["removed"]:
                        meters[ip].close.assert_called_once()
                        assert ip not in mm._METERMANAGER__attempts
                        assert ip not in mm._METERMANAGER__splash
                    assert not mm._METERMANAGER__stale_counts
                    assert "disconnected-busy" not in states["bayGuess"]
                    removed_events = [call.args[1]["ip"] for call in broadcast.call_args_list
                                      if call.args[0] == "meter" and not call.args[1]["alive"]]
                    assert set(removed_events) == set(result["removed"])
                    fresh.assert_not_called()
                    scan.assert_called_once()

                # A failed reachability check must leave all retained meters intact.
                with patch("ip_scanner.get_ips", side_effect=RuntimeError("scan failed")):
                    try:
                        mm.wipe()
                        raise AssertionError("Expected scan failure")
                    except RuntimeError:
                        pass
                assert list(mm.meters) == ["connected-busy"]
                meters["connected-busy"].close.assert_not_called()
                mm.meters.clear()
                mm._METERMANAGER__meters.clear()
                with patch("ip_scanner.get_ips") as scan:
                    assert mm.wipe() == {"removed": [], "preserved": []}
                    scan.assert_not_called()
            ''')],
            cwd=flask_dir,
            env={**os.environ, "PYTHONPATH": str(flask_dir), "HARDWARE_PROFILE": "portable", "MOCK": "1"},
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
