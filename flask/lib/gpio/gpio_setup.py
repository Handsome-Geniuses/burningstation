# this file is mostly for labeling
# all pin values should be placed here so we know what is used


# from lib.gpio.pcf8574int import PCF8574
from pcf8574 import PCF8574
from pigpiod import HWGPIO, HWGPIO_MONITOR
from lib.utils import secrets
from i2c import NosI2C
from lib.gpio.hbridge import HBridgeViaPCF8574 as HBridge


class HWGPIO_INVERTED(HWGPIO):
    @property
    def state(self) -> bool:
        return not super().state

    @state.setter
    def state(self, val: bool) -> None:
        super(HWGPIO_INVERTED, self.__class__).state.fset(self, not val)


i2c = None if secrets.MOCK else NosI2C()
HWGPIO.MOCK = secrets.MOCK
PCF8574.MOCK = secrets.MOCK


pcfio = [
    PCF8574(addr=0x20, invert=True, i2c=i2c),
    PCF8574(addr=0x21, invert=False, i2c=i2c),
    PCF8574(addr=0x22, invert=True, i2c=i2c),
]


# pin values here so we know whats used and unused
pin_emergency = 23
pins_mds = [17, 27, 22, 10, 9, 11, 5, 6, 13]
pin_buzzer = 12

pwm_lamps = [2, 3] 

__pcfio_motor_index = 1
__pcfio_motor_pins = [2, 3, 4, 5, 6, 7]
pcfio_motors = [
    (pcfio[__pcfio_motor_index], __pcfio_motor_pins[i], __pcfio_motor_pins[i + 1])
    for i in range(0, len(__pcfio_motor_pins), 2)
]

# pcfio_motors = [
#     (pcfio[1], 2, 3),
#     (pcfio[1], 4, 5),
#     (pcfio[1], 6, 7)
# ]

__pcfio_tower_index = 0
__pcfio_tower_pins = [0, 1, 2]
pcfio_tower = (pcfio[__pcfio_tower_index], *__pcfio_tower_pins)



emergency = HWGPIO(pin_emergency, "in", "pull_up")

HWGPIO_MONITOR.start()


def __keyme(**kwargs):
    return kwargs


hardware_map = __keyme(
    pin_emergency=pin_emergency,
    pins_mds=pins_mds,
    pin_buzzer=pin_buzzer,
    pwm_lamps=pwm_lamps,
    pcfio_motors={"pcfio": __pcfio_motor_index, "pins": __pcfio_motor_pins},
    pcfio_tower={"pcfio": __pcfio_tower_index, "pins": __pcfio_tower_pins},
)


# print(hardware_map)