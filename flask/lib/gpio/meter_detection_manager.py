from lib.gpio.gpio_setup import mds, HWGPIO
from lib.utils import packer, unpacker

class METER_DETECTION_MANAGER:
    @staticmethod
    def get_mds():
        return mds
    @staticmethod
    def get_value_list():
        return [md.state for md in mds]
    
    @staticmethod
    def set_value_list(states: list[bool]):
        """Set all 9 sensors from a list of booleans (only in MOCK mode)."""
        if not HWGPIO.MOCK: return
        assert len(states) == 9, "State list must have exactly 9 elements"
        for i, state in enumerate(states):
            mds[i].state = state

    @staticmethod
    def get_value():
        return packer(METER_DETECTION_MANAGER.get_value_list())

    @staticmethod
    def set_value(value: int):
        """Set all sensors from a 9-bit integer"""
        states = unpacker(value, 9)
        METER_DETECTION_MANAGER.set_state(states)
    

    @staticmethod
    def get_bit(index: int, value:int=None) -> bool:
        """Return the boolean state of sensor at given index (0..8)"""
        assert 0 <= index <= 8, "Index must be between 0 and 8"
        if value!=None:
            return bool(value & (1 << index))
        else:
            return mds[index].state

    @staticmethod
    def set_bit(index: int, value: bool):
        """Set the sensor at given index to True/False (only in MOCK mode)"""
        assert 0 <= index <= 8, "Index must be between 0 and 8"
        mds[index].state = value


    @staticmethod
    def get_ch_bit(ch:int, bit: int, value:int=None)->bool:
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= bit < 3, "bit must be 0-2"
        if value is None: value = METER_DETECTION_MANAGER.get_value()
        return bool(value & (1 << (ch * 3 + bit)))

    @staticmethod
    def set_ch_bit(ch: int, bit: int, state: bool):
        """Set a specific sensor bit in MOCK mode"""
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
