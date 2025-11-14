import re
from dotenv import load_dotenv
import os

load_dotenv()
class secrets:
    VERBOSE = os.getenv("VERBOSE", "0") == "1"
    MOCK = os.getenv("MOCK", "1") == "1"
    