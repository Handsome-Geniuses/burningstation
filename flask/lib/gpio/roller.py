

from pigpiod import HWGPIO

class Roller(HWGPIO):
    def __init__(self, gpio):
        super().__init__(gpio, 'out')
    pass