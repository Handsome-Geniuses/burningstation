

from pigpiod import HWGPIO
pin5 = HWGPIO(5, "out")
pin5.state=1
input("")
pin5.state=0