# Hardware Profiles

The backend reads `HARDWARE_PROFILE` at startup and exposes the active profile
through `/api/system/hardware` and SSE state key `hardware`.

`MOCK` is separate:

- `MOCK=1` means simulated/testing hardware behavior.
- `HARDWARE_PROFILE=portable` means this machine does not have the station IO
  hardware, even if `MOCK=1`.

## Profiles

```env
HARDWARE_PROFILE=full
```

`full` is the default and keeps the existing station hardware capabilities
enabled: belt, motor control, I2C expanders, meter-detection GPIO, tower,
lamps, emergency GPIO, robot remote power pulse, and auto mode.

```env
HARDWARE_PROFILE=portable
```

`portable` disables station IO by default. The application can start without
`/dev/i2c-1`, GPIO pins, PWM, belt motors, meter-detection sensors, tower,
lamps, emergency GPIO, or robot remote power GPIO. Auto mode is disabled because
the current auto flow depends on belt movement.

## Capability Checks

Use the central hardware layer:

```python
from lib.hardware import hardware

if hardware.has("belt"):
    ...

hardware.require("motor_control")
```

`hardware.require(...)` raises `HardwareCapabilityUnavailable`. The system route
converts that exception into a `409` JSON response with the unavailable
capability and active profile.

## Adding A Capability

1. Add the capability name to `CAPABILITIES` in
   `lib/hardware/capabilities.py`.
2. Set the capability value for every profile in `PROFILE_CAPABILITIES`.
3. Guard the hardware-owning module with `hardware.require("capability_name")`.
4. Expose safe read defaults when disabled if the state is part of SSE.
5. Use the existing frontend `hardware.capabilities` state to hide or disable
   controls; do not hard-code the profile in the frontend.
