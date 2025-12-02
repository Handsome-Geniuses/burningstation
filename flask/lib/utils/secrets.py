import re
from dotenv import load_dotenv
import os

load_dotenv()
class secrets:
    VERBOSE = os.getenv("VERBOSE", "0") == "1"
    MOCK = os.getenv("MOCK", "1") == "1"
    BASE = os.getenv("BASE", "192.168.169.")
    RANGE = list(map(int, os.getenv("RANGE", "2-254").split('-')))
    FUN = os.getenv("FUN", "0") == "1"