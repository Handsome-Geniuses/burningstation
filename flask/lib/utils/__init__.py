from lib.utils.prettyprint import *
from lib.utils.secrets import *

from typing import Literal


def literalValidGenerator(literals):
    validLiterals = set(literals.__args__)
    isValidLiteral = lambda s: s in validLiterals
    return isValidLiteral


# QTypes, validQtypes = generator(
QTypes = Literal["boolean", "string", "number"]
isValidQType = literalValidGenerator(QTypes)


s:QTypes = "boolean"

def packer(states:list[bool]) -> int:
    """Pack list of booleans into a single integer bitfield"""
    return sum((1 << i) if state else 0 for i, state in enumerate(states))

def unpacker(value:int, length:int) -> list[bool]:
    """Unpack integer bitfield into a list of booleans of given length"""
    return [(value & (1 << i)) != 0 for i in range(length)]

if __name__ == "__main__":
    states = [True, False, True, True, False, False, True, False, False]
    packed = packer(states)
    print(f"Packed: {packed:09b} ({packed})")
    unpacked = unpacker(packed, 9)
    print(f"Unpacked: {unpacked}")