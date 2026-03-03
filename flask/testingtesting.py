
if __name__ == "__main__": 
    from lib.automation.jobs import start_job
    import time

    import tools.mock # for testing with mock meters
    from lib.meter.meter_manager import METERMANAGER
    _,_,ips = METERMANAGER.refresh()
    meterip = ips[0]


    kwargs = {
        "numBurnCycles": 1,
        "numBurnDelay": 5,
        "solar": {"enabled": True},
        "coin_shutter": {"enabled": False},
        "nfc": {"enabled": False},
        "robot_keypad": {"enabled": False, "buttons": ['X']},

        "monitors": [
            ("nfc", {"timeout_on_s": 6.0, "timeout_off_s": 5.0}),
            ("robot_keypad", {"buttons": ['X']})
        ]
    }
    start_job(meterip, "physical_cycle_all", kwargs, verbose=True)

    time.sleep(60)



    






