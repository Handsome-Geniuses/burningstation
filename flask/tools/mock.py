from unittest.mock import patch
from lib.meter.ssh_meter import SSHMeter

__modules = {
    "MK7_XE910": {"ver": 2209, "mod": 3, "id": 76011859},
    "KIOSK_NFC": {"ver": 2227, "mod": 0, "id": 75006081},
    "MSPM_PWR": {"ver": 2219, "mod": 2, "id": 84000022},
    "KBD_CONTROLLER": {"ver": 2217, "mod": 4, "id": 93001636},
    "MK7_RFID": {"ver": 2101, "mod": 0, "id": 0},
    "COIN_SHUTTER": {"ver": 2215, "mod": 1, "id": 61000071},
    "KIOSK_III": {"ver": 146, "mod": 0, "id": 39078272},
    "MK7_VALIDATOR": {"ver": 2217, "mod": 2, "id": 71000694},
    "BNA": {"ver": 2207, "mod": 2, "id": 97000490},
    "PRINTER": {"ver": 2205, "mod": 1, "id": 50002729},
    "KEY_PAD_2": {"ver": 1, "mod": 0, "id": 89002160},
}
__hn = "30000269"
__svs = {"system_version": "48792", "system_sub_version": "29"}
__meter_type = "ms2.5"


patch.object(SSHMeter, "get_module_info", return_value=__modules).start()
patch.object(SSHMeter, "get_hostname", return_value=__hn).start()
patch.object(SSHMeter, "get_meter_type", return_value=__meter_type).start()
patch.object(SSHMeter, "get_system_versions", return_value=__svs).start()



