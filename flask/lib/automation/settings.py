from lib.store.store import store


def build_passive_kwargs(modules: dict):
    store.load()

    has_nfc = "KIOSK_NFC" in modules
    has_modem = "MK7_XE910" in modules
    has_printer = "PRINTER" in modules
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_screen_test = True

    s = store.settings.passive
    j = s.job_counts

    kwargs = {
        "numBurnCycles": s.cycles,
        "numBurnDelay": s.test_delay,
        "nfc": {
            "job_count": (j.nfc if has_nfc else 0)
        },
        "modem": {
            "job_count": (j.modem if has_modem else 0)
        },
        "call in": {
            "job_count": (j.call_in if has_modem else 0)
        },
        "printer": {
            "job_count": (j.printer if has_printer else 0)
        },
        "coin shutter": {
            "job_count": (j.coin_shutter if has_coin_shutter else 0)
        },
        "screen test": {
            "job_count": (j.screen_test if has_screen_test else 0),
            "payment_type": "coins",
            "debug_ui": 0,
        },
    }

    return kwargs


def build_physical_kwargs(modules: dict, buttons=None):
    store.load()
    buttons = list(buttons or [])

    has_solar = True
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_nfc = "KIOSK_NFC" in modules
    has_robot_keypad = (("KEY_PAD_2" in modules) or ("KBD_CONTROLLER" in modules)) and bool(buttons)

    s = store.settings.physical
    j = s.job_counts

    kwargs = {
        "numBurnCycles": s.cycles,
        "numBurnDelay": s.test_delay,
        "solar": {
            "job_count": (j.solar if has_solar else 0)
        },
        "coin_shutter": {
            "job_count": (j.coin_shutter if has_coin_shutter else 0)
        },
        "nfc_gui": {
            "job_count": (j.nfc_gui if has_nfc else 0),
            "payment_type": "robot_contactless",
            "robot_ready_timeout": 20.0,
        },
        "robot_keypad": {
            "job_count": (j.robot_keypad if has_robot_keypad else 0),
            "buttons": buttons,
        },
        "monitors": [
            ("robot_keypad", {"buttons": buttons})
        ] if has_robot_keypad else [],
    }

    return kwargs
