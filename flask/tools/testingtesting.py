
def testing_physical():
    from lib.automation.jobs import start_job
    import time

    import tools.mock # for testing with mock meters
    from lib.meter.meter_manager import METERMANAGER
    _,_,ips = METERMANAGER.refresh()
    # meterip = ips[0]
    meterip = "192.168.169.34"


    kwargs = {
        "numBurnCycles": 1,
        "numBurnDelay": 5,
        "solar": {"enabled": True},
        "coin_shutter": {"enabled": False},
        "nfc": {"enabled": False},
        "robot_keypad": {"enabled": False, "buttons": ['X']},

        # "monitors": [
        #     ("nfc", {"timeout_on_s": 6.0, "timeout_off_s": 5.0}),
        #     ("robot_keypad", {"buttons": ['X']})
        # ]
    }


    start_job(meterip, "physical_cycle_all", kwargs, verbose=True)
    print("yooo")
    time.sleep(122)


def testing_passive():

    from lib.automation.jobs import start_job
    import time

    # import tools.mock # for testing with mock meters
    from lib.meter.meter_manager import METERMANAGER
    _,_,ips = METERMANAGER.refresh()
    meterip = ips[0]
    meter = METERMANAGER.get_meter(meterip)

    modules = meter.module_info
    has_nfc = "KIOSK_NFC" in modules
    has_modem = "MK7_XE910" in modules
    has_printer = "PRINTER" in modules
    has_coin_shutter = "COIN_SHUTTER" in modules
    has_screen_test = True  # all meters have screen test

    kwargs = {
        "nfc": 1 if has_nfc else 0,
        "modem": 1 if has_modem else 0 ,
        "printer": 1 if has_printer else 0,
        "coin shutter": 1 if has_coin_shutter else 0,
        "screen test": 1 if has_screen_test else 0,
        "numBurnCycles": 30,
        "numBurnDelay": 10   
    }
    kwargs = {
        "nfc": 0,
        "modem": 0 ,
        "printer": 0,
        "coin shutter": 1 ,
        "screen test": 0,
        "numBurnCycles": 1,
        "numBurnDelay": 10   
    }


    # if states["mode"] == "auto":
    #     response = requests.post("http://127.0.0.1:8011/api/system/station/load", json={"type":"L"})
    
    start_job(meterip, "cycle_all", kwargs, verbose=True)


def testing_robot_abort_and_idle():
    pass


def uh():
    from lib.automation.jobs import start_job
    import time

    import tools.mock # for testing with mock meters
    from lib.meter.meter_manager import METERMANAGER

    _,_,ips = METERMANAGER.refresh()
    meterip = ips[0]
    start_job(meterip, "test_solar", {}, verbose=True)
    time.sleep(122)



if __name__ == "__main__": 
    uh()
    # testing_physical()
    # testing_robot_abort_and_idle()
    # pass
    # testing_passive()

    # import time
    # import threading
    # t = threading.Thread(target=testing_passive, daemon=True)
    # t.start()


    # print("hello")

    # time.sleep(10)
    # print("goodbye")

