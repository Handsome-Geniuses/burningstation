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

emergency = HWGPIO(23, "in", "pull_up")

pcfio = [
    PCF8574(addr=0x20, invert=True, i2c=i2c),
    PCF8574(addr=0x21, invert=True, i2c=i2c),
    PCF8574(addr=0x22, invert=True, i2c=i2c),
]

mds = [HWGPIO_INVERTED(pin, "in", "pull_up") for pin in [17, 27, 22, 10, 9, 11, 5, 6, 13]]

motors = [
    HBridge(pcfio[1], 2, 3),
    HBridge(pcfio[1], 4, 5),
    HBridge(pcfio[1], 6, 7),
]

# pcfio interface and r g b b pins
tower_interface = (pcfio[0], 0,1,2,3)

lamp_interface = (pcfio[0], 4,5)

HWGPIO_MONITOR.start()