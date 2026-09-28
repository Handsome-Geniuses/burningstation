from lib.store.store import store


COIN_REQUIREMENT_FIELDS_BY_REGION = {
    "us": (
        ("us_penny", "penny", "USD", 1),
        ("us_nickel", "nickel", "USD", 5),
        ("us_dime", "dime", "USD", 10),
        ("us_quarter", "quarter", "USD", 25),
        ("us_dollar_coin", "dollar_coin", "USD", 100),
    ),
    "uk": (
        ("uk_1p", "1p", "GBP", 1),
        ("uk_2p", "2p", "GBP", 2),
        ("uk_5p", "5p", "GBP", 5),
        ("uk_10p", "10p", "GBP", 10),
        ("uk_20p", "20p", "GBP", 20),
        ("uk_50p", "50p", "GBP", 50),
        ("uk_1_pound", "£1", "GBP", 100),
        ("uk_2_pounds", "£2", "GBP", 200),
    ),
}


def _build_operator_coin_requirements(coin_settings, meter_region):
    """Convert touchscreen quantity settings into the test program's schema."""
    region = str(meter_region or "").strip().lower()
    denominations = COIN_REQUIREMENT_FIELDS_BY_REGION.get(region)
    if denominations is None:
        return None

    requirements = {}
    for field_name, display_name, currency_code, value_minor in denominations:
        quantity = int(getattr(coin_settings.coin_requirements, field_name))
        if quantity > 0:
            requirements[display_name] = {
                "currency_code": currency_code,
                "value_minor": value_minor,
                "quantity": quantity,
            }
    return requirements


def build_passive_kwargs(modules: dict):
    store.load()

    has_nfc = "KIOSK_NFC" in modules or "KIOSK_NEO" in modules
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
    has_nfc = "KIOSK_NFC" in modules or "KIOSK_NEO" in modules
    has_robot_keypad = (("KEY_PAD_2" in modules) or ("KBD_CONTROLLER" in modules)) and bool(buttons)

    s = store.settings.physical
    j = s.job_counts

    kwargs = {
        "numBurnCycles": s.cycles,
        "numBurnDelay": s.test_delay,
        "solar": {
            "job_count": (j.solar if has_solar else 0)
        },
        "display_brightness": {
            "job_count": j.display_brightness,
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
            "verify_stuck": s.robot_keypad.verify_stuck,
            "back_enter_offsets_mm": s.robot_keypad.back_enter_offsets_mm,
            "max_retries_per_group": s.robot_keypad.max_retries_per_group,
        },
    }

    return kwargs


def build_operator_kwargs(modules: dict, buttons=None, meter_region=None):
    store.load()
    buttons = list(buttons or [])
    has_validator = "MK7_VALIDATOR" in modules
    has_nfc = "KIOSK_NFC" in modules or "KIOSK_NEO" in modules

    s = store.settings.operator
    j = s.job_counts
    coin_job_count = j.coins if has_validator else 0
    coin_requirements = _build_operator_coin_requirements(s.coins, meter_region)
    if coin_requirements == {}:
        # A coin run with no positive quantities cannot be valid. Mark it n/a
        # instead of sending an empty mapping to the test program.
        coin_job_count = 0

    coin_kwargs = {
        "job_count": coin_job_count,
        "allow_rejected": s.coins.allow_rejected,
        "max_duration_s": s.coins.max_duration_s,
        "poll_s": 0.75,
    }
    if coin_requirements:
        coin_kwargs["coin_requirements"] = coin_requirements

    return {
        "numBurnCycles": s.cycles,
        "numBurnDelay": s.test_delay,
        "screen_test": {"job_count": j.screen_test},
        "coins": coin_kwargs,
        "touchscreen": {
            "job_count": j.touchscreen,
            "expected_touch_count": s.touchscreen.expected_touch_count,
            "max_duration_s": s.touchscreen.max_duration_s,
        },
        "display_brightness": {"job_count": j.display_brightness, "max_duration_s": 60.0},
        "keypad": {
            "job_count": j.keypad,
            "buttons": buttons,
            "max_duration_s": s.keypad.max_duration_s,
        },
        "contactless": {
            "job_count": (j.contactless if has_nfc else 0),
            "max_duration_s": s.contactless.max_duration_s,
            "poll_s": 0.75,
        },
        "card_reader": {
            "job_count": j.card_reader,
            "max_duration_s": s.card_reader.max_duration_s,
            "poll_s": 0.5,
            "require_card_accepted": s.card_reader.require_card_accepted,
        },
    }
