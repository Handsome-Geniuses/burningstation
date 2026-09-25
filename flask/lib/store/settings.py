from typing import Any, Literal
import math

from pydantic import BaseModel, Field, field_validator


# ==================================================================
# DUMMY Settings
# ==================================================================
class DummySettings(BaseModel):
    state: bool = Field(False, description="this is a boolean")
    number: int = Field(5, ge=0, le=100, description="this is a integer")


# ==================================================================
# Passive Settings
# ==================================================================
class PassiveJobs(BaseModel):
    nfc: int = Field(1, ge=0, le=10)
    modem: int = Field(1, ge=0, le=10)
    call_in: int = Field(1, ge=0, le=10)
    printer: int = Field(1, ge=0, le=10)
    coin_shutter: int = Field(1, ge=0, le=10)
    screen_test: int = Field(1, ge=0, le=10)


class PassiveSettings(BaseModel):
    cycles: int = Field(1, ge=1, le=10, description="number of full test runs")
    test_delay: int = Field(10, ge=1, le=60, description="delay(s) between tests")
    job_counts: PassiveJobs = Field(default_factory=PassiveJobs)


# ==================================================================
# Physical Settings
# ==================================================================
class PhyiscalJobs(BaseModel):
    solar: int = Field(1, ge=0, le=10)
    display_brightness: int = Field(1, ge=0, le=10)
    coin_shutter: int = Field(1, ge=0, le=10)
    nfc_gui: int = Field(1, ge=0, le=10)
    robot_keypad: int = Field(1, ge=0, le=10)


class PhysicalRobotKeypadSettings(BaseModel):
    verify_stuck: bool = Field(
        True,
        description="Follow each robot BACK/ENTER scenario with a centered POUND stuck-key probe",
    )
    back_enter_offsets_mm: list[list[float]] = Field(
        default_factory=lambda: [[0.0, 0.0]],
        description=(
            "Ordered [x, y] millimetre offsets for robot BACK/ENTER presses; "
            "requires abs(x) < 12.75 and abs(y) < 5.0"
        ),
    )
    max_retries_per_group: int = Field(
        1,
        ge=0,
        le=10,
        description="Retry budget for each job-count/offset keypad scenario",
    )

    @field_validator("back_enter_offsets_mm")
    @classmethod
    def validate_back_enter_offsets(cls, value):
        if not isinstance(value, list) or not value:
            raise ValueError("must be a non-empty list of [x, y] pairs")
        validated = []
        for index, pair in enumerate(value):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError(f"item {index} must contain exactly [x, y]")
            if any(isinstance(component, bool) for component in pair):
                raise ValueError(f"item {index} values must be finite numbers")
            try:
                x, y = float(pair[0]), float(pair[1])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"item {index} values must be finite numbers") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"item {index} values must be finite numbers")
            if abs(x) >= 12.75:
                raise ValueError(f"item {index} x must satisfy abs(x) < 12.75")
            if abs(y) >= 5.0:
                raise ValueError(f"item {index} y must satisfy abs(y) < 5.0")
            validated.append([x, y])
        return validated


class PhysicalSettings(BaseModel):
    cycles: int = Field(1, ge=1, le=10, description="number of full test runs")
    test_delay: int = Field(5, ge=1, le=60, description="delay(s) between tests")
    job_counts: PhyiscalJobs = Field(default_factory=PhyiscalJobs)
    robot_keypad: PhysicalRobotKeypadSettings = Field(
        default_factory=PhysicalRobotKeypadSettings,
        description="Robot-driven keypad test options",
    )


# ==================================================================
# Operator-assisted Settings
# ==================================================================
class OperatorJobs(BaseModel):
    screen_test: int = Field(1, ge=0, le=10)
    coins: int = Field(1, ge=0, le=10)
    touchscreen: int = Field(1, ge=0, le=10)
    display_brightness: int = Field(1, ge=0, le=10)
    keypad: int = Field(1, ge=0, le=10)
    contactless: int = Field(1, ge=0, le=10)
    card_reader: int = Field(1, ge=0, le=10)


class OperatorSettings(BaseModel):
    cycles: int = Field(1, ge=1, le=10, description="number of full test runs")
    test_delay: int = Field(1, ge=0, le=60, description="delay(s) between test runs")
    job_counts: OperatorJobs = Field(default_factory=OperatorJobs)


# ==================================================================
# Version Checker Settings
# ==================================================================
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ComparisonOperator = Literal["eq", "gt", "gte", "lt", "lte"]


class VersionConstraint(BaseModel):
    value: int = Field(0, ge=0, le=MAX_SAFE_INTEGER, strict=True)
    operator: ComparisonOperator | None = None


class FirmwareVersionCheck(BaseModel):
    version: VersionConstraint = Field(default_factory=VersionConstraint)
    mod: VersionConstraint = Field(default_factory=VersionConstraint)


def version_check_field(
    description: str,
    *,
    module_aliases: tuple[str, ...] = (),
):
    return Field(
        default_factory=FirmwareVersionCheck,
        description=description,
        json_schema_extra={"module_aliases": list(module_aliases)},
    )


class VersionChecks(BaseModel):
    ms3_via: FirmwareVersionCheck = version_check_field(
        "MS3 VIA System Version",
        module_aliases=("system_version",),
    )
    sys_sub: FirmwareVersionCheck = version_check_field(
        "System Sub Version",
        module_aliases=("system_sub_version",),
    )
    mspm_pwr: FirmwareVersionCheck = version_check_field("MSPM PWR")
    xe910: FirmwareVersionCheck = version_check_field(
        "XE910 Bus Modem",
        module_aliases=("MK7_XE910",),
    )
    bg95: FirmwareVersionCheck = version_check_field("BG 95")
    bg91_uk: FirmwareVersionCheck = version_check_field("BG 91 (UK)")
    keypad: FirmwareVersionCheck = version_check_field(
        "1x6/1x7 Keypad/KBD_Controller",
        module_aliases=("KBD_CONTROLLER",),
    )
    coin_us: FirmwareVersionCheck = version_check_field(
        "Coin Shutter (US)",
        module_aliases=("COIN_SHUTTER",),
    )
    coin_uk: FirmwareVersionCheck = version_check_field(
        "Coin Shutter (UK)",
        module_aliases=("COIN_SHUTTER",),
    )
    keypad2: FirmwareVersionCheck = version_check_field(
        "KEYPAD 2 (ALPHA)",
        module_aliases=("KEY_PAD_2",),
    )
    emvr: FirmwareVersionCheck = version_check_field(
        "EMV Contact Reader",
        module_aliases=("EMV_CONTACT",),
    )
    rfid: FirmwareVersionCheck = version_check_field(
        "RFID",
        module_aliases=("MK7_RFID",),
    )
    m7_validator: FirmwareVersionCheck = version_check_field(
        "M7 Validator (MS3)",
        module_aliases=("MK7_VALIDATOR",),
    )
    reject_validator: FirmwareVersionCheck = version_check_field(
        "Reject Validator (MS3)"
    )
    printer: FirmwareVersionCheck = version_check_field("Printer")
    contactless: FirmwareVersionCheck = version_check_field(
        "Contactless Reader (iDtech) Kiosk V",
        module_aliases=("KIOSK_NFC",),
    )
    nfc_neo: FirmwareVersionCheck = version_check_field(
        "Kiosk V NFC (NEO)",
        module_aliases=("KIOSK_NEO",),
    )
    coin_escrow: FirmwareVersionCheck = version_check_field(
        "Coin Escrow",
        module_aliases=("ESCROW_28",),
    )
    bna_bus_mei: FirmwareVersionCheck = version_check_field(
        "BNA Bus MEI",
        module_aliases=("BNA",),
    )


# ==================================================================
# Other Settings
# ==================================================================
class OtherSettings(BaseModel):
    auto_print_fw: bool = Field(False, description="print fw after passive test")
    auto_unload_r: int = Field(
        0, ge=0, le=2, description="will attempt to move the meter into unload position"
    )


# ==================================================================
# Flow Settings
# ==================================================================
class FlowSettings(BaseModel):
    load_check: bool = Field(
        True, description="blink to confirm correct meter for loading"
    )
    physical_check: bool = Field(
        True, description="blink meters to confirm middle meter for physical test"
    )


# ==================================================================
# Handsome Settings - more elusive secret settings!
# ==================================================================
class PhysicalKeys(BaseModel):
    key_pad_2: list[str] = Field(
        default_factory=lambda: [
            "1",
            "2",
            "3",
            "4",
            "5",
            "ASTERISK",
            "6",
            "7",
            "8",
            "9",
            "0",
            "POUND",
            "A",
            "B",
            "C",
            "D",
            "E",
            "F",
            "G",
            "H",
            "I",
            "J",
            "K",
            "L",
            "M",
            "N",
            "O",
            "P",
            "Q",
            "R",
            "S",
            "T",
            "U",
            "V",
            "W",
            "X",
            "BACK",
            "Y",
            "Z",
            "ENTER",
        ]
    )
    kbd_controller: list[str] = Field(
        default_factory=lambda: ["help", "up", "down", "cancel", "accept", "max"]
    )


class HandsomeSettings(BaseModel):
    # physical_keys: PhysicalKeys = Field(default_factory=PhysicalKeys)
    allow_auto_switch: bool = Field(
        False, description="allow auto mode switching with meters on belt?"
    )


# ==================================================================
# Settings Settings
# ==================================================================
class Settings(BaseModel):
    # dummy: DummySettings = Field(default_factory=DummySettings)
    handsome: HandsomeSettings = Field(
        default_factory=HandsomeSettings, description="secret settings"
    )
    flow: FlowSettings = Field(
        default_factory=FlowSettings, description="flow related options"
    )
    other: OtherSettings = Field(
        default_factory=OtherSettings, description="miscellaneous"
    )
    passive: PassiveSettings = Field(
        default_factory=PassiveSettings,
        description="parameters or testing locally on meter",
    )
    physical: PhysicalSettings = Field(
        default_factory=PhysicalSettings,
        description="parameters for testing with robot and tools",
    )
    operator: OperatorSettings = Field(
        default_factory=OperatorSettings,
        description="parameters for operator-assisted testing",
    )
    version_checks: VersionChecks = Field(
        default_factory=VersionChecks,
        description="firmware version and MOD requirements",
    )
