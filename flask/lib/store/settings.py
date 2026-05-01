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
    coin_shutter: int = Field(1, ge=0, le=10)
    nfc_gui: int = Field(1, ge=0, le=10)
    robot_keypad: int = Field(1, ge=0, le=10)


class PhysicalSettings(BaseModel):
    cycles: int = Field(1, ge=1, le=10, description="number of full test runs")
    test_delay: int = Field(5, ge=1, le=60, description="delay(s) between tests")
    job_counts: PhyiscalJobs = Field(default_factory=PhyiscalJobs)


# ==================================================================
# Handsome Settings - more elusive secret settings!
# ==================================================================
class PhysicalKeys(BaseModel):
    key_pad_2: list[str] = Field(default_factory=lambda: ['1', '2', '3', '4', '5', 'ASTERISK', '6', '7', '8', '9', '0', 'POUND', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'BACK', 'Y', 'Z', 'ENTER'])
    kbd_controller: list[str] = Field(default_factory=lambda: ['help', 'up', 'down', 'cancel', 'accept', 'max'])

class HandsomeSettings(BaseModel):
    physical_keys: PhysicalKeys = Field(default_factory=PhysicalKeys)


# ==================================================================
# Settings Settings
# ==================================================================
class Settings(BaseModel):
    dummy: DummySettings = Field(default_factory=DummySettings)
    passive: PassiveSettings = Field(default_factory=PassiveSettings)
    physical: PhysicalSettings = Field(default_factory=PhysicalSettings)
    # handsome: HandsomeSettings = Field(default_factory=HandsomeSettings)




