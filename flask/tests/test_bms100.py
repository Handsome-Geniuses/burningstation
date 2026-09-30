import unittest
from unittest.mock import patch

from lib.hardware.bms100 import BMS100Reader, parse_soc_response


class BMS100Tests(unittest.TestCase):
    def test_parses_soc_register(self):
        data = bytearray(254)
        data[116:118] = (690).to_bytes(2, "big")

        self.assertEqual(
            parse_soc_response(b"prefix\x51\x03" + bytes([254]) + data),
            69.0,
        )

    def test_rejects_missing_truncated_and_out_of_range_values(self):
        self.assertIsNone(parse_soc_response(b""))
        self.assertIsNone(parse_soc_response(b"\x51\x03\xfe\x00"))

        data = bytearray(254)
        data[116:118] = (1001).to_bytes(2, "big")
        self.assertIsNone(parse_soc_response(b"\x51\x03" + bytes([254]) + data))

    def test_serial_open_failure_returns_unavailable(self):
        with patch("lib.hardware.bms100.serial") as serial_module:
            serial_module.Serial.side_effect = OSError("port unavailable")
            self.assertIsNone(BMS100Reader("/missing").read_percentage())


if __name__ == "__main__":
    unittest.main()
