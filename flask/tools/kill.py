import requests
import sys
ok = False

try: ok = (requests.get('http://192.168.169.1:8011/api/system/suicide', timeout=0.5)).ok
except: pass
