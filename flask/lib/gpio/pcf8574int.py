from pcf8574 import PCF8574 as __PCF8574
from pigpiod import HWGPIO
import time

class PCF8574(__PCF8574):
    def __init__(self, addr=0x20, invert=False, intgpio: HWGPIO = None, **kwargs):
        super().__init__(addr, invert, **kwargs)
        self.intgpio = intgpio

    def __mock_trigger(self):
        if PCF8574.MOCK and self.intgpio:
            self.intgpio.state = 1
            time.sleep(0.01)
            self.intgpio.state = 0

    def write_byte(self, value):
        value = value & 0xFF
        if PCF8574.MOCK:
            if value == self.read_byte(): return
             
        res = super().write_byte(value)
        self.__mock_trigger()
        return res
    


    