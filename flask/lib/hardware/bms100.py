import os
import struct
import threading
import time
from typing import Any

try:
    import serial
except ImportError:
    serial = None


SOC_REGISTER = 59
_RESPONSE_MARKER = b"\x51\x03"
_SERIAL_TIMEOUT_SECONDS = 0.1
_READ_DEADLINE_SECONDS = 1.0


def _modbus_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


_READ_REGISTERS = b"\x81\x03\x00\x00\x00\x7f"
_READ_COMMAND = _READ_REGISTERS + _modbus_crc(_READ_REGISTERS)


def _expected_response_length(response: bytes | bytearray) -> int | None:
    marker_index = response.find(_RESPONSE_MARKER)
    if marker_index < 0 or marker_index + 3 > len(response):
        return None

    byte_count = response[marker_index + 2]
    return marker_index + 3 + byte_count + 2


def parse_soc_response(response: bytes) -> float | None:
    marker_index = response.find(_RESPONSE_MARKER)
    if marker_index < 0 or marker_index + 3 > len(response):
        return None

    byte_count = response[marker_index + 2]
    data_start = marker_index + 3
    register_offset = (SOC_REGISTER - 1) * 2
    value_start = data_start + register_offset
    value_end = value_start + 2
    if value_end > len(response) or register_offset + 2 > byte_count:
        return None

    raw_value = struct.unpack(">H", response[value_start:value_end])[0]
    percentage = raw_value / 10.0
    return round(percentage, 1) if 0 <= percentage <= 100 else None


class BMS100Reader:
    def __init__(self, port: str | None = None):
        self.port = port or os.getenv("BMS_PORT", "/dev/ttyUSB0")
        self._lock = threading.Lock()
        self._connection: Any | None = None
        self._debug = os.getenv("BMS_DEBUG", "0") == "1"

    def _log_debug(self, msg: str):
        if self._debug:
            print(f"[BMS100] {msg}")

    def _close(self):
        if self._connection is None:
            return

        try:
            self._connection.close()
        except Exception:
            pass
        finally:
            self._connection = None

    def _connect(self):
        if serial is None:
            return None

        if self._connection is None:
            self._connection = serial.Serial(
                port=self.port,
                baudrate=9600,
                timeout=_SERIAL_TIMEOUT_SECONDS,
            )
            self._connection.reset_input_buffer()
            self._connection.reset_output_buffer()
            time.sleep(0.5)
        elif not self._connection.is_open:
            self._connection.open()
            self._connection.reset_input_buffer()
            self._connection.reset_output_buffer()
            time.sleep(0.5)
        else:
            self._connection.reset_input_buffer()
            self._connection.reset_output_buffer()

        return self._connection

    def _read_response(self, connection) -> bytes:
        response = bytearray()
        deadline = time.monotonic() + _READ_DEADLINE_SECONDS
        expected_length = None

        while time.monotonic() < deadline:
            if expected_length is not None and len(response) >= expected_length:
                break

            remaining = 512 if expected_length is None else expected_length - len(response)
            chunk = connection.read(max(1, min(remaining, 512)))
            if not chunk:
                continue

            response.extend(chunk)
            expected_length = _expected_response_length(response)

        return bytes(response)

    def read_percentage(self) -> float | None:
        if serial is None:
            self._log_debug("pyserial is not installed")
            return None

        with self._lock:
            try:
                connection = self._connect()
                if connection is None:
                    return None

                connection.write(_READ_COMMAND)
                time.sleep(0.05)
                response = self._read_response(connection)
                percentage = parse_soc_response(response)
                if percentage is None:
                    self._log_debug(f"unparsed response len={len(response)} hex={response.hex(' ')}")
                return percentage
            except Exception as exc:
                self._log_debug(f"read failed on {self.port}: {exc}")
                self._close()
                return None


_reader = BMS100Reader()


def read_battery_percentage() -> float | None:
    return _reader.read_percentage()
