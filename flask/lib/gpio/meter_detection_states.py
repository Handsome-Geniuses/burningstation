from typing import Tuple


class MeterDetectionStates:
    def __init__(self):
        self.__value = 0b000000000  # 9 bits

    @property
    def states(self) -> list[bool]:
        # Convert to 9-bit binary string, pad with zeros on the left
        return [bool(int(b)) for b in f"{self.__value:09b}"]

    @states.setter
    def states(self, bits: list[bool]):
        if len(bits) != 9:
            raise ValueError("States must be a list of 9 booleans.")
        self.__value = int("".join("1" if b else "0" for b in bits), 2)

    @property
    def value(self) -> int:
        return self.__value

    @value.setter
    def value(self, value: int):
        assert 0 <= value <= 0b111111111, "Value must be a 9-bit integer (0–511)"
        self.__value = value

    def set_bit(self, index: int, state: bool):
        assert 0 <= index < 9, "Bit index must be between 0 and 8"
        if state:
            self.__value |= 1 << index
        else:
            self.__value &= ~(1 << index)

    def get_bit(self, index: int):
        assert 0 <= index < 9, "Bit index must be between 0 and 8"
        return bool(self.__value & 1 << index)

    def set_ch_bit(self, ch: int, bit: int, state: bool):
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= bit < 3, "bit must be 0-2"
        self.set_bit(ch * 3 + bit, state)

    def get_ch_bit(self, ch: int, bit: int):
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= bit < 3, "bit must be 0-2"
        return bool(self.__value & 1 << (ch * 3 + bit))

    def set_ch_value(self, ch: int, value: int):
        assert 0 <= ch < 3, "ch must be 0-2"
        assert 0 <= value <= 0b111, "value must be 0b0-0b111"
        mask = 0b111 << (ch * 3)
        self.__value &= ~mask
        self.__value |= value << (ch * 3)

    def get_ch_value(self, ch: int) -> int:
        assert 0 <= ch < 3
        mask = 0b111 << (ch * 3)
        return (self.__value & mask) >> (ch * 3)

    def get_ch_states(self, ch: int) -> list[bool]:
        assert 0 <= ch < 3, "ch must be 0-2"
        mask = 0b111 << (ch * 3)
        value = (self.__value & mask) >> (ch * 3)
        return [(value >> i) & 1 == 1 for i in range(3)]

    def is_ch_full(self, ch: int):
        assert 0 <= ch < 3, "ch must be 0-2"
        mask = 0b111 << (ch * 3)
        return (self.__value & mask) == mask

    def is_ch_empty(self, ch: int):
        assert 0 <= ch < 3, "ch must be 0-2"
        mask = 0b111 << (ch * 3)
        return (self.__value & mask) == 0

    def is_ch_left(self, ch: int):
        return self.get_ch_bit(ch, 0)

    def is_ch_right(self, ch: int):
        return self.get_ch_bit(ch, 2)

    def is_ch_mid(self, ch: int):
        return self.get_ch_bit(ch, 1)

    def is_full_states(self) -> list[bool]:
        return [self.is_ch_full(ch) for ch in range(3)]

    def is_empty_states(self) -> list[bool]:
        return [self.is_ch_empty(ch) for ch in range(3)]


if __name__ == "__main__":
    mds = MeterDetectionStates()
    print(mds.is_ch_empty(0))
