from typing import Dict, Set, TypedDict
import ip_scanner
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
from prettyprint import STYLE, prettyprint as print


ips = ip_scanner.get_ips(base=secrets.BASE, start=10, end=40, timeout=1, concurrency=500)

print(ips)