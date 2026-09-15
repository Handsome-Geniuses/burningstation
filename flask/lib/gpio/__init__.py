from pigpiod import HWGPIO, HWGPIO_MONITOR

from lib.hardware import hardware
from lib.gpio.gpio_setup import (
    UnavailableGPIO,
    ensure_gpio_monitor_started,
    get_emergency,
    get_robot_remote_on,
)


emergency = (
    get_emergency()
    if hardware.has("emergency_gpio")
    else UnavailableGPIO("emergency_gpio", "emergency")
)
robot_remote_on = (
    get_robot_remote_on()
    if hardware.has("robot_remote_power")
    else UnavailableGPIO("robot_remote_power", "robot_remote_on")
)

from lib.gpio.meter_detection_manager import METER_DETECTION_MANAGER as mdm
from lib.gpio.roller_manager import ROLLER_MANAGER as rm
import lib.gpio.tower_manager as tm
import lib.gpio.lamp_manager as lm
