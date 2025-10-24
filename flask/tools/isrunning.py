import requests
import sys
ok = False

try: ok = (requests.get('http://localhost:8011/api/system', timeout=0.5)).ok
except: pass

if ok: sys.exit(0)
else: sys.exit(1)
   