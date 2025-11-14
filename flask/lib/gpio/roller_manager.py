from lib.gpio.gpio_setup import HBridge, pcfio_motors
from lib.utils import packer, unpacker
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.system.states import states

motors = [
    HBridge(*pcfio_motors[0]),
    HBridge(*pcfio_motors[1]),
    HBridge(*pcfio_motors[2]),
]

class ROLLER_MANAGER:
    FORWARD = HBridge.FORWARD
    REVERSE = HBridge.BACKWARD
    COAST = HBridge.COAST
    BRAKE = HBridge.BRAKE

    @staticmethod
    def unpack(value: int) -> list[int]:
        """Unpack a single byte into individual 2-bit values"""
        # return [(value >> (i * 2)) & 0b11 for i in range(3)]
        return unpacker(value,3)
    
    @staticmethod
    def pack(states: list[int]) -> int:
        """Pack list of 3 2-bit values to single byte"""
        assert len(states) == 3, "State list must have exactly 3 elements"
        # return sum((s & 0b11) << (i * 2) for i, s in enumerate(states))
        return packer(states)
    
    @staticmethod
    def get_value() -> int:
        """Get packed byte of all 3 motors (2 bits each)"""
        return (motors[0].value << 0) | (motors[1].value << 2) | (motors[2].value << 4)

    @staticmethod
    def set_value(value: int):
        """Set all 3 motors from a single packed byte"""
        assert isinstance(value, int), "value must be an integer"
        assert 0 <= value <= 0x3F, "value must fit within 6 bits (3 motors × 2 bits each)"
        ROLLER_MANAGER.set_value_list(unpacker(value, 3))

    @staticmethod
    def get_value_list() -> list[int]:
        """Get list of 3 motor 2-bit states"""
        return ROLLER_MANAGER.unpack(ROLLER_MANAGER.get_value())

    @staticmethod
    def set_value_list(values: list[int]):
        """Set all 3 motors from a list of 2-bit values"""
        assert isinstance(values, list), "states must be a list"
        assert len(values) == 3, "expected list of 3 motor states"
        assert all(isinstance(s, int) for s in values), "each motor state must be an int"
        assert all(0 <= s <= 0b11 for s in values), "each motor state must fit in 2 bits (0–3)"
        
        if states['motors'] == values: return
        for ch, value in enumerate(values):
            motors[ch].value = value
        states['motors'] = values
        SSEQM.broadcast("state", key_payload("motors", values))

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

