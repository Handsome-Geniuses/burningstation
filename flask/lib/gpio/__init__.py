# # from .pigpio import HWGPIO, HWGPIO_MONITOR, VALID_PINS
# from .pigpiod import HWGPIO, HWGPIO_MONITOR
from pigpiod import HWGPIO, HWGPIO_MONITOR
from pcf8574 import PCF8574
from i2c import NosI2C
from lib.gpio.hbridge import HBridgeViaPCF8574 as HBridge
from lib.utils import secrets
import time

i2c = None if secrets.MOCK else NosI2C()
HWGPIO.MOCK = secrets.MOCK
PCF8574.MOCK = secrets.MOCK

emergency = HWGPIO(23, "in")



# ==========================================
# set up pcf8574 io expander
# ==========================================
class __PCF8574_with_interrupt(PCF8574):
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


pcfio1 = __PCF8574_with_interrupt(
    addr=0x20, invert=True, intgpio=HWGPIO(14, "in", "pull_up"), i2c=i2c
)
pcfio2 = __PCF8574_with_interrupt(
    addr=0x21, invert=True, intgpio=HWGPIO(15, "in", "pull_up"), i2c=i2c
)
pcfio3 = __PCF8574_with_interrupt(
    addr=0x22, invert=True, intgpio=HWGPIO(18, "in", "pull_up"), i2c=i2c
)

# ==========================================
# set up meter detection shiet pcf8574
# ==========================================
class METER_DETECTION_MANAGER:
    @staticmethod
    def get_value():
        return ((pcfio2.get_state(0) & 1) << 8) | (pcfio1.read_byte() & 0xFF)

    @staticmethod
    def get_state():
        # return [pcfio2.get_state(0)] + pcfio1.get_state()
        # return list(reversed(pcfio1.get_state())) + [pcfio2.get_state(0)]
        return pcfio1.get_state() + [pcfio2.get_state(0)]

    @staticmethod
    def set_value(value: int):
        """Set all sensors from a 9-bit integer"""

        # Lower 8 bits -> pcfio1
        pcfio1.write_byte(value & 0xFF)
        # Bit8 -> pcfio2 pin0
        pcfio2.set_state(0, bool((value >> 8) & 1))

    @staticmethod
    def set_state(states: list[bool]):
        """Set all 9 sensors from a list of booleans (only in MOCK mode)."""
        if not PCF8574.MOCK:
            return
        assert len(states) == 9, "State list must have exactly 9 elements"
        packed = (int(states[0]) << 8) | sum(
            int(s) << i for i, s in enumerate(states[1:])
        )
        METER_DETECTION_MANAGER.set_value(packed)

    @staticmethod
    def get_bit(index: int, value:int=None) -> bool:
        """Return the boolean state of sensor at given index (0..8)"""
        assert 0 <= index <= 8, "Index must be between 0 and 8"
        if value!=None:
            return bool(value & (1 << index))
        else:
            if index == 8:
                return bool(pcfio2.get_state(0))
            else:
                return bool(pcfio1.get_state(index))

    @staticmethod
    def set_bit(index: int, value: bool):
        """Set the sensor at given index to True/False (only in MOCK mode)"""
        if not PCF8574.MOCK:
            return
        assert 0 <= index <= 8, "Index must be between 0 and 8"
        if index == 8:
            pcfio2.set_state(0, value)
        else:
            pcfio1.set_state(index, value)

    @staticmethod
    def get_ch_bit(ch:int, bit: int, value:int=None)->bool:
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= bit < 3, "bit must be 0-2"
        if value is None: value = METER_DETECTION_MANAGER.get_value()
        return bool(value & (1 << (ch * 3 + bit)))

    @staticmethod
    def set_ch_bit(ch: int, bit: int, state: bool):
        """Set a specific sensor bit in MOCK mode"""
        if not PCF8574.MOCK:
            return
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= bit < 3, "bit must be 0-2"
        index = ch * 3 + bit
        METER_DETECTION_MANAGER.set_bit(index, state)
    
    @staticmethod
    def get_ch_value(ch: int, value: int = None) -> int:
        """Get the 3-bit value for a channel (0-7)"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = METER_DETECTION_MANAGER.get_value()
        return (value >> (ch * 3)) & 0b111
    
    @staticmethod
    def set_ch_value(ch: int, ch_value: int):
        """Set the 3-bit value for a channel"""
        if not PCF8574.MOCK:
            return
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= ch_value < 8, "ch_value must be 0-7"
        current = METER_DETECTION_MANAGER.get_value()
        # Clear the 3 bits for this channel, then set the new value
        current &= ~(0b111 << (ch * 3))
        current |= (ch_value & 0b111) << (ch * 3)
        METER_DETECTION_MANAGER.set_value(current)

    @staticmethod
    def get_ch_states(ch: int, value: int = None) -> list[bool]:
        """Get the 3 sensor states for a channel as a list of booleans"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = METER_DETECTION_MANAGER.get_value()
        ch_value = METER_DETECTION_MANAGER.get_ch_value(ch, value)
        return [(ch_value >> i) & 1 for i in range(3)]

    @staticmethod
    def set_ch_states(ch: int, states: list[bool]):
        """Set the 3 sensor states for a channel from a list of booleans"""
        if not PCF8574.MOCK:
            return
        assert 0 <= ch < 3, "ch must be 0-2"
        assert len(states) == 3, "states list must have exactly 3 elements"
        ch_value = sum(int(s) << i for i, s in enumerate(states))
        METER_DETECTION_MANAGER.set_ch_value(ch, ch_value)

    @staticmethod
    def is_ch_full(ch: int, value: int = None) -> bool:
        """Check if all 3 sensors in a channel are active (value == 0b111)"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = METER_DETECTION_MANAGER.get_value()
        return METER_DETECTION_MANAGER.get_ch_value(ch, value) == 0b111

    @staticmethod
    def is_ch_empty(ch: int, value: int = None) -> bool:
        """Check if all 3 sensors in a channel are inactive (value == 0b000)"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = METER_DETECTION_MANAGER.get_value()
        return METER_DETECTION_MANAGER.get_ch_value(ch, value) == 0b000

mdm = METER_DETECTION_MANAGER
# ==========================================
# set up motors for rollers, uses pcf8574
# ==========================================
motors = [
    HBridge(pcfio2, 1, 2),
    HBridge(pcfio2, 3, 4),
    HBridge(pcfio2, 5, 6),
]

class ROLLER_MANAGER:
    FORWARD = HBridge.FORWARD
    BACKWARD = HBridge.BACKWARD
    COAST = HBridge.COAST
    BRAKE = HBridge.BRAKE
    @staticmethod
    def get_motor(ch) -> HBridge:
        assert 0 <= ch < 3, "ch must be 0-2"
        return motors[ch]

    @staticmethod
    def unpack(value: int) -> list[int]:
        """Unpack a single byte into individual 2-bit values"""
        return [(value >> (i * 2)) & 0b11 for i in range(3)]
    
    @staticmethod
    def pack(states: list[int]) -> int:
        """Pack list of 3 2-bit values to single byte"""
        assert len(states) == 3, "State list must have exactly 3 elements"
        return sum((s & 0b11) << (i * 2) for i, s in enumerate(states))
    
    @staticmethod
    def get_value() -> int:
        """Get packed byte of all 3 motors (2 bits each)"""
        return (motors[0].value << 0) | (motors[1].value << 2) | (motors[2].value << 4)

    @staticmethod
    def set_value(value: int):
        """Set all 3 motors from a single packed byte"""
        motors[0].value = (value >> 0) & 0b11
        motors[1].value = (value >> 2) & 0b11
        motors[2].value = (value >> 4) & 0b11

    @staticmethod
    def get_value_list() -> list[int]:
        """Get list of 3 motor 2-bit states"""
        return ROLLER_MANAGER.unpack(ROLLER_MANAGER.get_value())

    @staticmethod
    def set_value_list(states: list[int]):
        """Set all 3 motors from a list of 2-bit values"""
        ROLLER_MANAGER.set_value(ROLLER_MANAGER.pack(states))

    @staticmethod
    def get_ch_value(ch: int, value: int = None) -> int:
        """Get the 2-bit value for a motor channel (0-2)"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = ROLLER_MANAGER.get_value()
        return (value >> (ch * 2)) & 0b11

    @staticmethod
    def set_ch_value(ch: int, ch_value: int):
        """Set the 2-bit value for a motor channel"""
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= ch_value < 4, "ch_value must be 0-3"
        current = ROLLER_MANAGER.get_value()
        # Clear the 2 bits for this channel, then set the new value
        current &= ~(0b11 << (ch * 2))
        current |= (ch_value & 0b11) << (ch * 2)
        ROLLER_MANAGER.set_value(current)

    @staticmethod
    def get_ch_value_list(ch: int, value: int = None) -> list[int]:
        """Get individual bits of a motor as a list [bit0, bit1]"""
        assert 0 <= ch < 3, "ch must be 0-2"
        if value is None:
            value = ROLLER_MANAGER.get_value()
        ch_value = ROLLER_MANAGER.get_ch_value(ch, value)
        return [(ch_value >> i) & 1 for i in range(2)]

    @staticmethod
    def set_ch_value_list(ch: int, bits: list[int]):
        """Set individual bits of a motor from a list [bit0, bit1]"""
        assert 0 <= ch < 3, "ch must be 0-2"
        assert len(bits) == 2, "bits list must have exactly 2 elements"
        ch_value = sum((b & 1) << i for i, b in enumerate(bits))
        ROLLER_MANAGER.set_ch_value(ch, ch_value)

    
        


rm = ROLLER_MANAGER

HWGPIO_MONITOR.start()


