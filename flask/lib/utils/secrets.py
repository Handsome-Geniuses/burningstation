import re
from dotenv import load_dotenv
import os

load_dotenv()
class secrets:
    VERBOSE = os.getenv("VERBOSE", "True") == "True"
    MOCK = os.getenv("MOCK", "True") == "True"
    