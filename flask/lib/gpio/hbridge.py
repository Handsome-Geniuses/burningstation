from pigpiod import HWGPIO

class HBridge:
    def __init__(self, in1_pin, in2_pin, en_pin=None):
        self.in1 = HWGPIO(in1_pin, "out")
        self.in2 = HWGPIO(in2_pin, "out")
        self.en = HWGPIO(en_pin, "out") if en_pin is not None else None

    def forward(self):
        if self.en: self.en.on()
        self.in1.on()
        self.in2.off()

    def backward(self):
        if self.en: self.en.on()
        self.in1.off()
        self.in2.on()

    def stop(self):
        if self.en: self.en.off()
        self.in1.off()
        self.in2.off()

if __name__ == "__main__":
    a = HBridge(17,18,27)
    a.forward()