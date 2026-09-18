# this file is mostly for labeling
# all pin values should be placed here so we know what is used


from pigpiod import HWGPIO, HWGPIO_MONITOR
from lib.utils import secrets
from lib.hardware import HardwareCapabilityUnavailable, hardware


class HWGPIO_INVERTED(HWGPIO):
    @property
    def state(self) -> bool:
        return not super().state

    @state.setter
    def state(self, val: bool) -> None:
        super(HWGPIO_INVERTED, self.__class__).state.fset(self, not val)


class UnavailableGPIO:
    def __init__(self, capability: str, name: str, state: bool = False):
        self.capability = capability
        self.name = name
        self.gpio = name
        self._state = bool(state)

    @property
    def state(self) -> bool:
        return self._state

    @state.setter
    def state(self, value: bool) -> None:
        raise HardwareCapabilityUnavailable(self.capability, hardware.profile)

    def on(self):
        self.state = True

    def off(self):
        self.state = False


HWGPIO.MOCK = secrets.MOCK

_i2c = None
_pcfio = None
_emergency = None
_robot_remote_on = None
_gpio_monitor_started = False


# pin values here so we know whats used and unused
pin_emergency = 23
pin_robot_remote_on = 24
pins_mds = [17, 27, 22, 10, 9, 11, 5, 6, 13]
pin_buzzer = 12

pwm_lamps = [2, 3]

__pcfio_motor_index = 1
__pcfio_motor_pins = [2, 3, 4, 5, 6, 7]

__pcfio_tower_index = 0
__pcfio_tower_pins = [0, 1, 2]


def get_i2c():
    global _i2c
    hardware.require("i2c")
    if secrets.MOCK:
        return None
    if _i2c is None:
        from i2c import NosI2C

        _i2c = NosI2C()
    return _i2c


def get_pcfio():
    global _pcfio
    hardware.require("i2c")
    if _pcfio is None:
        # from lib.gpio.pcf8574int import PCF8574
        from pcf8574 import PCF8574

        PCF8574.MOCK = secrets.MOCK
        i2c = get_i2c()
        _pcfio = [
            PCF8574(addr=0x20, invert=True, i2c=i2c),
            PCF8574(addr=0x21, invert=False, i2c=i2c),
            PCF8574(addr=0x22, invert=True, i2c=i2c),
        ]
    return _pcfio


def get_pcfio_motors():
    hardware.require("motor_control")
    pcfio = get_pcfio()
    return [
        (pcfio[__pcfio_motor_index], __pcfio_motor_pins[i], __pcfio_motor_pins[i + 1])
        for i in range(0, len(__pcfio_motor_pins), 2)
    ]


def get_pcfio_tower():
    hardware.require("tower")
    pcfio = get_pcfio()
    return (pcfio[__pcfio_tower_index], *__pcfio_tower_pins)


def get_emergency():
    global _emergency
    hardware.require("emergency_gpio")
    if _emergency is None:
        _emergency = HWGPIO(pin_emergency, "in", "pull_up")
    return _emergency


def get_robot_remote_on():
    global _robot_remote_on
    hardware.require("robot_remote_power")
    if _robot_remote_on is None:
        _robot_remote_on = HWGPIO(pin_robot_remote_on, "out")
    return _robot_remote_on


def ensure_gpio_monitor_started():
    global _gpio_monitor_started
    hardware.require("station_io")
    if not _gpio_monitor_started:
        HWGPIO_MONITOR.start()
        _gpio_monitor_started = True


def __keyme(**kwargs):
    return kwargs


hardware_map = __keyme(
    hardware_profile=hardware.profile,
    capabilities=hardware.capabilities,
    pin_emergency=pin_emergency,
    pin_robot_remote_on=pin_robot_remote_on,
    pins_mds=pins_mds,
    pin_buzzer=pin_buzzer,
    pwm_lamps=pwm_lamps,
    pcfio_motors={"pcfio": __pcfio_motor_index, "pins": __pcfio_motor_pins},
    pcfio_tower={"pcfio": __pcfio_tower_index, "pins": __pcfio_tower_pins},
)


# print(hardware_map)
