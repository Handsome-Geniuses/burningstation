from pigpiod import HWGPIO


class HBridge:
    FORWARD = 0b01
    BACKWARD = 0b10
    COAST = 0b00
    BRAKE = 0b11
    def __init__(self, in1_pin, in2_pin, en_pin=None):
        self.in1 = HWGPIO(in1_pin, "out")
        self.in2 = HWGPIO(in2_pin, "out")
        self.en = HWGPIO(en_pin, "out") if en_pin is not None else None

    def get_value(self):
        return (self.in2.state << 1) | self.in1.state
    def set_value(self, value):
        assert 0 <= value <= 0b11
        self.in1.state = bool(value & 0b01)
        self.in2.state = bool((value >> 1) & 0b01)
    value = property(get_value,set_value)
    
    def enable(self):
        if self.en:
            self.en.on()

    def disable(self):
        if self.en:
            self.en.off()

    def forward(self): 
        self.set_value(self.FORWARD)
    def backward(self): 
        self.set_value(self.BACKWARD)
    def coast(self): 
        self.set_value(self.COAST)
    def brake(self): 
        self.set_value(self.BRAKE)

from pcf8574 import PCF8574
class HBridgeViaPCF8574:
    FORWARD = 0b01
    BACKWARD = 0b10
    COAST = 0b00
    BRAKE = 0b11
    def __init__(self, pcfio:PCF8574,bit0=0, bit1=1, biten=None, **kwargs):
        assert bit0 != bit1, "bit0 and bit1 must be different"
        assert 0 <= bit0 <= 7 and 0 <= bit1 <= 7, "bit0/bit1 must be between 0 and 7"

        if biten is not None:
            assert 0 <= biten <= 7, "biten must be between 0 and 7"
            assert biten not in (bit0, bit1), "biten cannot overlap bit0 or bit1"

        self.pcfio = pcfio
        self.bit0 = bit0
        self.bit1 = bit1
        self.biten = biten

    def get_value(self):
        bits = self.pcfio.read_byte()
        b0 = (bits >> self.bit0) & 1
        b1 = (bits >> self.bit1) & 1
        return (b1 << 1) | b0
    
    def set_value(self, value):
        assert 0 <= value <= 0b11
        bits = self.pcfio.read_byte()
        
        v0 = (value>>0) & 1
        v1 = (value>>1) & 1

        bits = (bits & ~(1 << self.bit0)) | ((v0 & 1) << self.bit0)
        bits = (bits & ~(1 << self.bit1)) | ((v1 & 1) << self.bit1)

        self.pcfio.write_byte(bits)
    value = property(get_value,set_value)

    def enable(self):
        if self.biten!=None:
            self.pcfio.set_state(self.biten,True)

    def disable(self):
        if self.biten!=None:
            self.pcfio.set_state(self.biten,False)

    def forward(self): 
        self.set_value(self.FORWARD)
    def backward(self): 
        self.set_value(self.BACKWARD)
    def coast(self): 
        self.set_value(self.COAST)
    def brake(self): 
        self.set_value(self.BRAKE)
    