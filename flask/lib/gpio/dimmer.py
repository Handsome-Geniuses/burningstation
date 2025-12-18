from pigpiod import HWGPIO, HWGPIO_MONITOR
from prettyprint import STYLE, prettyprint as print

psync = HWGPIO(20)
plamp = HWGPIO(21)

def on_sync(p: HWGPIO):
    print(f"sync -> {psync.state}")

HWGPIO_MONITOR.add_listener(psync, on_sync)
if __name__ == "__main__":
    HWGPIO_MONITOR.start()
    input("...")
    HWGPIO_MONITOR.stop()
