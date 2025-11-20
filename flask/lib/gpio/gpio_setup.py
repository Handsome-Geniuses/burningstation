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
pcfio_motors = [
    (pcfio[1], 2, 3),
    (pcfio[1], 4, 5),
    (pcfio[1], 6, 7)
]
pcfio_tower = (pcfio[0], 0, 1, 2)

lamp_pwm_channels=[2,3] #0:12, 1:13, 2:18, 3:19
lamp_interface = (pcfio[0], 4, 5)


emergency = HWGPIO(pin_emergency, "in", "pull_up")

HWGPIO_MONITOR.start()