import os
import struct
import threading
import time

try:
    import serial
except ImportError:
    serial = None


SOC_REGISTER = 59
_RESPONSE_MARKER = b"\x51\x03"


def _modbus_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


_READ_REGISTERS = b"\x81\x03\x00\x00\x00\x7f"
_READ_COMMAND = _READ_REGISTERS + _modbus_crc(_READ_REGISTERS)


def parse_soc_response(response: bytes) -> float | None:
    marker_index = response.find(_RESPONSE_MARKER)
    if marker_index < 0 or marker_index + 3 > len(response):
        return None

    byte_count = response[marker_index + 2]
    data_start = marker_index + 3
    data_end = data_start + byte_count
    register_offset = (SOC_REGISTER - 1) * 2
    if data_end > len(response) or register_offset + 2 > byte_count:
        return None

    raw_value = struct.unpack(
        ">H", response[data_start + register_offset:data_start + register_offset + 2]
    )[0]
    percentage = raw_value / 10.0
    return round(percentage, 1) if 0 <= percentage <= 100 else None


class BMS100Reader:
    def __init__(self, port: str | None = None):
        self.port = port or os.getenv("BMS_PORT", "/dev/ttyUSB0")
        self._lock = threading.Lock()

    def read_percentage(self) -> float | None:
        if serial is None:
            return None

        connection = None
        with self._lock:
            try:
                connection = serial.Serial(
                    port=self.port,
                    baudrate=9600,
                    timeout=0.2,
                )
                connection.reset_input_buffer()
                connection.write(_READ_COMMAND)
                time.sleep(0.05)
                return parse_soc_response(connection.read(512))
            except Exception:
                return None
            finally:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass


_reader = BMS100Reader()


def read_battery_percentage() -> float | None:
    return _reader.read_percentage()
