import threading
import time
from lib.gpio import robot_remote_on
from lib.hardware import hardware

_robot_pulse_lock = threading.Lock()

def pulse_robot_remote_on(duration: float = 3.0):
    if not hardware.has("robot_remote_power"):
        return
    if not _robot_pulse_lock.acquire(blocking=False):
        return  # already pulsing

    def _pulse():
        try:
            robot_remote_on.on()
            time.sleep(duration)
            robot_remote_on.off()
        finally:
            _robot_pulse_lock.release()

    threading.Thread(target=_pulse, daemon=True).start()
