from typing import Any
from pydantic import BaseModel, Field


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


class PhysicalSettings(BaseModel):
    cycles: int = Field(1, ge=1, le=10, description="number of full test runs")
    test_delay: int = Field(5, ge=1, le=60, description="delay(s) between tests")
    job_counts: PhyiscalJobs = Field(default_factory=PhyiscalJobs)


# ==================================================================
# Operator-assisted Settings
# ==================================================================
class OperatorJobs(BaseModel):
    screen_test: int = Field(1, ge=0, le=10)
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
class VersionChecks(BaseModel):
    ms3_via: int = Field(0, description="MS3 VIA System Version")
    sys_sub: int = Field(0, description="System Sub Version")
    mspm_pwr: int = Field(0, description="MSPM PWR")
    xe910: int = Field(0, description="XE910 Bus Modem")
    bg95: int = Field(0, description="BG 95")
    bg91_uk: int = Field(0, description="BG 91 (UK)")
    keypad: int = Field(0, description="1x6/1x7 Keypad/KBD_Controller")
    coin_us: int = Field(0, description="Coin Shutter (US)")
    coin_uk: int = Field(0, description="Coin Shutter (UK)")
    keypad2: int = Field(0, description="KEYPAD 2 (ALPHA)")
    emvr: int = Field(0, description="EMV Contact Reader")
    rfid: int = Field(0, description="RFID")
    m7_validator: int = Field(0, description="M7 Validator (MS3)")
    reject_validator: int = Field(0, description="Reject Validator (MS3)")
    printer: int = Field(0, description="Printer")
    contactless: int = Field(0, description="Contactless Reader (iDtech) Kiosk V")
    nfc_neo: int = Field(0, description="Kiosk V NFC (NEO)")
    coin_escrow: int = Field(0, description="Coin Escrow")
    bna_bus_mei: int = Field(0, description="BNA Bus MEI")


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
