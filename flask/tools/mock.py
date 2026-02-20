from unittest.mock import patch
from lib.meter.ssh_meter import SSHMeter

# __modules = {
#     "MK7_XE910": {"ver": 2209, "mod": 3, "id": 76011859},
#     "KIOSK_NFC": {"ver": 2227, "mod": 0, "id": 75006081},
#     "MSPM_PWR": {"ver": 2219, "mod": 2, "id": 84000022},
#     "KBD_CONTROLLER": {"ver": 2217, "mod": 4, "id": 93001636},
#     "MK7_RFID": {"ver": 2101, "mod": 0, "id": 0},
#     "COIN_SHUTTER": {"ver": 2215, "mod": 1, "id": 61000071},
#     "KIOSK_III": {"ver": 146, "mod": 0, "id": 39078272},
#     "MK7_VALIDATOR": {"ver": 2217, "mod": 2, "id": 71000694},
#     "BNA": {"ver": 2207, "mod": 2, "id": 97000490},
#     "PRINTER": {"ver": 2205, "mod": 1, "id": 50002729},
#     "KEY_PAD_2": {"ver": 1, "mod": 0, "id": 89002160},
# }
# __firmwares = {
#     "MK7_XE910": "2209",
#     "KIOSK_NFC": "2227",
#     "MSPM_PWR": "2219",
#     "KBD_CONTROLLER": "2217",
#     "MK7_RFID": "2101",
#     "COIN_SHUTTER": "2215",
#     "KIOSK_III": "146",
#     "MK7_VALIDATOR": "2217",
#     "BNA": "2207",
#     "PRINTER": "2205",
#     "KEY_PAD_2": "1"
# }
# __hn = "30000269"
# __svs = {"system_version": "48792", "system_sub_version": "29"}
# __meter_type = "ms2.5"

__modules = {
    "MK7_XE910": {"ver": 2209, "mod": 3, "id": 76000166},
    "KIOSK_NFC": {"ver": 2227, "mod": 0, "id": 75008793},
    "MSPM_PWR": {"ver": 2219, "mod": 2, "id": 84003495},
    "KBD_CONTROLLER": {"ver": 2217, "mod": 4, "id": 93003771},
    "EMV_CONTACT": {"ver": 26, "mod": 0, "id": 601015619},
    "COIN_SHUTTER": {"ver": 2215, "mod": 1, "id": 61003019},
    "MK7_RFID": {"ver": 2101, "mod": 0, "id": 80000066},
    "KIOSK_III": {"ver": 146, "mod": 0, "id": 57639321},
    "ESCROW_28": {"ver": 2210, "mod": 1, "id": 95000772},
    "MK7_VALIDATOR": {"ver": 2217, "mod": 2, "id": 71001241},
    "PRINTER": {"ver": 2208, "mod": 1, "id": 50003276},
    "KEY_PAD_2": {"ver": 1, "mod": 0, "id": 89003579},
}
__firmwares = {
    "MK7_XE910": "2209",
    "KIOSK_NFC": "2227",
    "MSPM_PWR": "2219",
    "KBD_CONTROLLER": "2217",
    "EMV_CONTACT": "26",
    "COIN_SHUTTER": "2215",
    "MK7_RFID": "2101",
    "KIOSK_III": "146",
    "ESCROW_28": "2210",
    "MK7_VALIDATOR": "2217",
    "PRINTER": "2208",
    "KEY_PAD_2": "1",
}
__hn = "30001189"
__svs = {"system_version": "48792", "system_sub_version": "31"}
__meter_type = "ms3"

original_init = SSHMeter.__init__
def mock_init(self, host, **kwargs):
    original_init(self, host, **kwargs)
    # override all internal caches/state
    self._Client__hostname = __hn

    self._module_info_cache = __modules
    self._firmwares = __firmwares
    self._system_versions_cache = __svs
    self.status = "ready"
    self.results = {}
    self._module_details_cache = __modules
    # self.__resolution = "800x480"  # so meter_type works
    self._SSHMeter__resolution = "800x480"
    self._host = host  # if any code uses self.host

# patch.object(SSHMeter, "__init__", mock_init).start()
patch("lib.meter.ssh_meter.SSHMeter.__init__", mock_init).start()

# # mocking get_power_info to return dummy data
# def mock_get_power_info(self):
#     return {"Voltage": "5000mV", "Current": "0.7A"}
# # patch.object(SSHMeter, "get_power_info", mock_get_power_info).start()
# patch("lib.meter.SSHMeter.get_power_info", mock_get_power_info).start()


if __name__ == "__main__":
    meter = SSHMeter("192.168.169.20")
    print(meter.get_info())