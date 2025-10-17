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