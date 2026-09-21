import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


class HardwareCapabilityUnavailable(RuntimeError):
    def __init__(self, capability: str, profile: str, message: str | None = None):
        self.capability = capability
        self.profile = profile
        super().__init__(
            message
            or f"Hardware capability '{capability}' is unavailable in HARDWARE_PROFILE={profile}"
        )


CAPABILITIES = (
    "station_io",
    "i2c",
    "belt",
    "motor_control",
    "meter_detection",
    "tower",
    "lamp",
    "emergency_gpio",
    "robot_remote_power",
    "auto_mode",
)


PROFILE_CAPABILITIES: dict[str, dict[str, bool]] = {
    "full": {capability: True for capability in CAPABILITIES},
    "portable": {capability: False for capability in CAPABILITIES},
}


@dataclass(frozen=True)
class HardwareConfig:
    profile: str
    capabilities: dict[str, bool]

    @classmethod
    def from_env(cls):
        requested_profile = os.getenv("HARDWARE_PROFILE", "full").strip().lower() or "full"
        if requested_profile not in PROFILE_CAPABILITIES:
            valid_profiles = ", ".join(sorted(PROFILE_CAPABILITIES))
            raise ValueError(
                f"Invalid HARDWARE_PROFILE={requested_profile!r}. "
                f"Expected one of: {valid_profiles}"
            )
        return cls(
            profile=requested_profile,
            capabilities=dict(PROFILE_CAPABILITIES[requested_profile]),
        )

    def has(self, capability: str) -> bool:
        return bool(self.capabilities.get(capability, False))

    def require(self, capability: str):
        if not self.has(capability):
            raise HardwareCapabilityUnavailable(capability, self.profile)

    def to_frontend(self) -> dict:
        return {
            "profile": self.profile,
            "capabilities": dict(self.capabilities),
            "mock": os.getenv("MOCK", "1").strip() == "1",
        }


hardware = HardwareConfig.from_env()
