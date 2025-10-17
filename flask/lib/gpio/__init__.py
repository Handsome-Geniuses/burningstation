# # from .pigpio import HWGPIO, HWGPIO_MONITOR, VALID_PINS
# from .pigpiod import HWGPIO, HWGPIO_MONITOR
from pigpiod import HWGPIO,HWGPIO_MONITOR
from pcf8574 import PCF8574
from i2c import NosI2C
from .roller import Roller
# from .mdet import MDet
from .meter_detection_states import MeterDetectionStates
__mock = True
i2c = None if __mock else NosI2C

HWGPIO.MOCK = __mock
PCF8574.MOCK = __mock


# control motors for rollers
rollers = [Roller(p) for p in (16,20,21)]

# emergency button
emergency =  HWGPIO(12, 'in')

# hold meter detection states. NEEDS CONSTANT UPDATING
mds = MeterDetectionStates()

# detection is handled by i2c io expander
pcfio1 = PCF8574(0x20, True, i2c=i2c)
pcfio1_int = HWGPIO(14, "in", "pull_up")
pcfio2 = PCF8574(0x21, True, i2c=i2c)
pcfio2_int = HWGPIO(15, "in", "pull_up")


HWGPIO_MONITOR.start()
