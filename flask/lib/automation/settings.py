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
        "nfc": j.nfc if has_nfc else 0,
        "modem": j.modem if has_modem else 0,
        "printer": j.printer if has_printer else 0,
        "coin shutter": j.coin_shutter if has_coin_shutter else 0,
        "screen test": j.screen_test if has_screen_test else 0,
    }

    return kwargs


def build_physical_kwargs(modules: dict, buttons=None):
    store.load()

    has_solar = True
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_nfc = "KIOSK_NFC" in modules
    has_robot_keypad = ("KEY_PAD_2" in modules) or ("KBD_CONTROLLER" in modules)

    s = store.settings.physical
    j = s.job_counts

    kwargs = {
        "numBurnCycles": s.cycles,
        "numBurnDelay": s.test_delay,
        "solar": j.solar if has_solar else 0,
        "coin_shutter": j.coin_shutter if has_coin_shutter else 0,
        "nfc_gui": j.nfc_gui if has_nfc else 0,
        "robot_keypad": j.robot_keypad if has_robot_keypad else 0,
    }

    return kwargs
