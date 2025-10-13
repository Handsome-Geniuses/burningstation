# ===========================================================
# name: pigpio
# auth: nos
# desc: contrl gpio
# devices:
#   * rpi 5 - 6.12.34+rpt-rpi-2712
# ===========================================================
__all__ = ["HWGPIO"]
import os
import time
import asyncio
import threading
from typing import get_args, get_origin, Literal


def check_literal_type(value, literal_type):
    if get_origin(literal_type) is Literal:
        return value in get_args(literal_type)
    raise TypeError(f"{literal_type} is not a Literal type")


_channel_map = {
    2: 571,
    3: 572,
    4: 573,
    5: 574,
    6: 575,
    7: 576,
    8: 577,
    9: 578,
    10: 579,
    11: 580,
    12: 581,
    13: 582,
    14: 583,
    15: 584,
    16: 585,
    17: 586,
    18: 587,
    19: 588,
    20: 589,
    21: 590,
    22: 591,
    23: 592,
    24: 593,
    25: 594,
    26: 595,
    27: 596,
}
VALID_PINS = Literal[
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
]
_VALID_DIRS = Literal["out", "in"]


class HWGPIO:
    MOCK = False  # set True for testing without /sys

    _PATH_GPIO = "/sys/class/gpio"
    _PATH_EXPORT = "/sys/class/gpio/export"
    _PATH_UNEXPORT = "/sys/class/gpio/unexport"

    OUTPUT = "out"
    INPUT = "in"

    def __del__(self):
        self.enable = False
        print(f">>[CLEANUP] gpio{self.gpio}")

    def __init__(self, gpio: VALID_PINS, dir: _VALID_DIRS = INPUT, auto_enable=False):
        self.gpio = gpio
        if not check_literal_type(gpio, VALID_PINS):
            raise ValueError(f"bad pin {gpio}, valid pins are {VALID_PINS}")
        if not check_literal_type(dir, _VALID_DIRS):
            raise ValueError(f"bad dir {dir}, valid dirs are {_VALID_DIRS}")
        self.channel = _channel_map.get(gpio)
        self._PATH = os.path.join(HWGPIO._PATH_GPIO, f"gpio{self.channel}")

        if HWGPIO.MOCK:
            # skip all /sys access
            self.__enable = True
            self.__dir = dir
            self.__state = False
            return

        # check file write access
        if not os.access(HWGPIO._PATH_GPIO, os.W_OK):
            raise PermissionError(f"No write access to {HWGPIO._PATH_GPIO}")

        if auto_enable: self.enable = True

        # check if exported
        self.__enable = self.__check_exported()

        self.__dir = "out"
        if self.__enable:
            self.set_direction(dir, True)
            self.__state = self.__check_state()
        else:
            self.__state = -1

    def __echo(self, file: str, msg: any):
        if HWGPIO.MOCK:
            return  # skip writing in mock mode
        with open(file, "w") as f:
            f.write(str(msg))

    def __check_exported(self):
        if HWGPIO.MOCK:
            return True
        return os.path.isdir(self._PATH)

    def get_enable(self):
        return self.__enable

    def set_enable(self, state: bool):
        if self.__enable == state:
            return
        if HWGPIO.MOCK:
            self.__enable = state
            return

        if state:
            self.__echo(HWGPIO._PATH_EXPORT, self.channel)
        else:
            self.__echo(HWGPIO._PATH_GPIO, self.channel)
        if self.__check_exported() != state:
            raise Exception(f"GPIO{self.gpio} failed to export")
        self.__enable = state

    enable = property(get_enable, set_enable)

    def __check_direction(self):
        if HWGPIO.MOCK:
            return self.__dir
        with open(os.path.join(self._PATH, "direction")) as f:
            return f.read().strip()

    def get_direction(self):
        return self.__dir

    def set_direction(self, dir: _VALID_DIRS, firsttime=False):
        if not check_literal_type(dir, _VALID_DIRS):
            raise ValueError(
                f"GPIO{self.gpio}: bad dir {dir}, valid dirs are {_VALID_DIRS}"
            )
        if not self.enable:
            raise Exception(f"GPIO{self.gpio} is not enabled!")
        if not firsttime and self.__dir == dir:
            return
        if not HWGPIO.MOCK:
            self.__echo(os.path.join(self._PATH, "direction"), dir)
            if self.__check_direction() != dir:
                raise Exception(f"GPIO{self.gpio} failed to set direction")
        self.__dir = dir

    dir = property(get_direction, set_direction)

    def __check_state(self):
        if HWGPIO.MOCK:
            return self.__state
        with open(os.path.join(self._PATH, "value")) as f:
            return f.read().strip() == "1"

    def get_state(self):
        return self.__state

    def set_state(self, state: bool, force=False):
        if self.__dir == "in" and not force:
            raise Exception(f"GPIO{self.gpio} is an input!")
        if not self.enable:
            raise Exception(f"GPIO{self.gpio} is not enabled!")
        if self.__state == state:
            return
        if not HWGPIO.MOCK:
            self.__echo(os.path.join(self._PATH, "value"), 1 if state else 0)
            if self.__check_state() != state:
                raise Exception(f"GPIO{self.gpio} failed to set state")
            self.__state = state
        else:
            # in mock mode, trigger listeners
            if hasattr(self, "_mock_listeners") and self.__state != state:
                self.__state = state
                for callback in self._mock_listeners:
                    callback(self)
        self.__state = state

    state = property(get_state, set_state)

    def __mocker(self, state: bool):
        self.set_state(state, HWGPIO.MOCK)

    mock = property(get_state, __mocker)

    def on(self):
        self.state = True

    def off(self):
        self.state = False

    # ================= Async listener integration =================
    def add_listener(self, callback, edge="both", loop=None):
        """Add async listener for GPIO edges."""
        if not self.enable:
            raise Exception(f"GPIO{self.gpio} is not enabled!")
        if HWGPIO.MOCK:
            # In mock mode, store callback and call it on state change
            if not hasattr(self, "_mock_listeners"):
                self._mock_listeners = []
            self._mock_listeners.append(callback)
            return

        # real sysfs logic
        with open(os.path.join(self._PATH, "edge"), "w") as f:
            f.write(edge)

        fd = os.open(os.path.join(self._PATH, "value"), os.O_RDONLY | os.O_NONBLOCK)
        os.lseek(fd, 0, os.SEEK_SET)

        async def _watch():
            _loop = loop or asyncio.get_event_loop()
            last_val = None
            last_trigger = 0
            DEBOUNCE_MS = 100  # ignore edges within 50 ms

            while True:
                await _loop.run_in_executor(None, lambda: os.read(fd, 1))
                os.lseek(fd, 0, os.SEEK_SET)
                val = os.read(fd, 1).decode().strip() == "1"

                now = time.time() * 1000
                if val != last_val and (now - last_trigger) > DEBOUNCE_MS:
                    last_val = val
                    last_trigger = now
                    self.__state = val
                    callback(self)

        return (loop or asyncio.get_event_loop()).create_task(_watch())


# loop = asyncio.new_event_loop()
# asyncio.set_event_loop(loop)
# def loop_thread(): loop.run_forever()



class HWGPIO_MONITOR:
    loop = asyncio.new_event_loop()
    running = False
    _listeners = {}  # pin -> list of tasks
    
    @classmethod
    def start(cls):
        if cls.running: return
        cls.running = True
        asyncio.set_event_loop(cls.loop)
        def loop_thread(): cls.loop.run_forever()
        threading.Thread(target=loop_thread, daemon=True).start()

    @classmethod
    def stop(cls):
        if not cls.running: return
        cls.running = False
        cls.loop.call_soon_threadsafe(cls.loop.stop)

    @classmethod
    def basic_callback(cls,p:HWGPIO):
        print(f"GPIO{p.gpio} changed to {p.state}")

    @classmethod
    def add_listener(cls, pin: HWGPIO, callback=None, edge="both"):
        # cls.start() # ensure loop is running if wanted
        if callback is None: callback = cls.basic_callback
        # schedule listener safely in loop thread
        def schedule():
            task = pin.add_listener(callback, edge=edge, loop=cls.loop)
            if task is not None: cls._listeners.setdefault(pin, []).append(task)

        cls.loop.call_soon_threadsafe(schedule)

    @classmethod
    def remove_listeners(cls, pin: HWGPIO):
        if pin not in cls._listeners:
            return
        for task in cls._listeners[pin]:
            task.cancel()
        del cls._listeners[pin]


if __name__ == "__main__":
    import threading
    HWGPIO.MOCK = True
    
    def on_change(p:HWGPIO):  print(f"GPIO{p.gpio} changed to {p.state}")


    p21 = HWGPIO(21, "out")
    p21.enable = True

    p20 = HWGPIO(20, "in")
    p20.enable = True

    
    def method1():
        async def main():
            p21.add_listener(on_change)
            p20.add_listener(on_change)
            await asyncio.Event().wait()
                
        def start_main():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(main())
        
        def run1():
            asyncio.run(main())
        def run2():
            threading.Thread(target=start_main, daemon=True).start()
            input("")

        run1()

    def method2():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        def loop_thread(): loop.run_forever()
        threading.Thread(target=loop_thread, daemon=True).start()
        # schedule listener safely in loop thread
        loop.call_soon_threadsafe(lambda: p21.add_listener(on_change, loop=loop))
        loop.call_soon_threadsafe(lambda: p20.add_listener(on_change, loop=loop))
        input("")


    def method3():
        HWGPIO_MONITOR.start()
        HWGPIO_MONITOR.add_listener(p21, on_change)
        HWGPIO_MONITOR.add_listener(p20, on_change)

    method3()
    input("")
    p21.state = True
    input("")
    HWGPIO_MONITOR.remove_listeners(p21)
    input("")
    HWGPIO_MONITOR.stop()
    






"""
sudo nano /boot/firmware/config.txt
dont think its needed anymore but just in cast
[pi5]
arm_freq=2800       # CPU frequency in MHz
gpu_freq=1000       # GPU frequency in MHz
over_voltage=6      # Increases voltage (0-8 safe range)
dtoverlay=pwm,pin=18,func=2
gpio=5,6,7,8,16,17,20,21,22,26,27=pu
gpio=9,10,11,12,18,19,23,24,25=op
"""