import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from lib.store.settings import (
    MAX_SAFE_INTEGER,
    Settings,
    VersionChecks,
    VersionConstraint,
)
from lib.store.store import SettingsStore


EXPECTED_FIRMWARE_KEYS = {
    "ms3_via",
    "sys_sub",
    "mspm_pwr",
    "xe910",
    "bg95",
    "bg91_uk",
    "keypad",
    "coin_us",
    "coin_uk",
    "keypad2",
    "emvr",
    "rfid",
    "m7_validator",
    "reject_validator",
    "printer",
    "contactless",
    "nfc_neo",
    "coin_escrow",
    "bna_bus_mei",
}


class VersionSettingsTests(unittest.TestCase):
    def test_defaults_include_only_existing_firmware_with_both_constraints_off(self):
        checks = VersionChecks()

        self.assertEqual(set(VersionChecks.model_fields), EXPECTED_FIRMWARE_KEYS)
        for firmware in VersionChecks.model_fields:
            requirement = getattr(checks, firmware)
            self.assertEqual(requirement.version.value, 0)
            self.assertIsNone(requirement.version.operator)
            self.assertEqual(requirement.mod.value, 0)
            self.assertIsNone(requirement.mod.operator)

    def test_all_comparison_operators_are_valid(self):
        for operator in (None, "eq", "gt", "gte", "lt", "lte"):
            with self.subTest(operator=operator):
                constraint = VersionConstraint(value=48_794, operator=operator)
                self.assertEqual(constraint.operator, operator)

    def test_version_and_mod_are_independent(self):
        checks = VersionChecks.model_validate({
            "ms3_via": {
                "version": {"value": 48_794, "operator": "gte"},
                "mod": {"value": 2, "operator": None},
            }
        })

        self.assertEqual(checks.ms3_via.version.operator, "gte")
        self.assertIsNone(checks.ms3_via.mod.operator)
        self.assertEqual(checks.ms3_via.mod.value, 2)

    def test_constraint_value_boundaries(self):
        self.assertEqual(VersionConstraint(value=0).value, 0)
        self.assertEqual(
            VersionConstraint(value=MAX_SAFE_INTEGER).value,
            MAX_SAFE_INTEGER,
        )

        for value in (-1, MAX_SAFE_INTEGER + 1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                VersionConstraint(value=value)

    def test_invalid_operator_is_rejected(self):
        with self.assertRaises(ValidationError):
            VersionConstraint(value=1, operator="ne")

    def test_existing_settings_without_version_checks_receive_defaults(self):
        settings = Settings.model_validate({"flow": {"load_check": False}})

        self.assertFalse(settings.flow.load_check)
        self.assertIsNone(settings.version_checks.ms3_via.version.operator)
        self.assertIsNone(settings.version_checks.ms3_via.mod.operator)

    def test_off_constraint_retains_value_across_store_reload(self):
        previous_instance = SettingsStore._instance
        previous_initialized = SettingsStore._initialized

        try:
            SettingsStore._instance = None
            SettingsStore._initialized = False

            with tempfile.TemporaryDirectory() as directory:
                store = SettingsStore(Path(directory) / "settings.json")
                payload = Settings().model_dump()
                payload["version_checks"]["ms3_via"] = {
                    "version": {"value": 48_794, "operator": "gte"},
                    "mod": {"value": 2, "operator": None},
                }

                store.set_from_dict(payload)
                reloaded = store.reload()

                self.assertEqual(reloaded.version_checks.ms3_via.version.value, 48_794)
                self.assertEqual(reloaded.version_checks.ms3_via.version.operator, "gte")
                self.assertEqual(reloaded.version_checks.ms3_via.mod.value, 2)
                self.assertIsNone(reloaded.version_checks.ms3_via.mod.operator)
        finally:
            SettingsStore._instance = previous_instance
            SettingsStore._initialized = previous_initialized


if __name__ == "__main__":
    unittest.main()
