from typing import Dict, Set, TypedDict
import ip_scanner
from lib.meter.fun import send_fun_meter
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
from prettyprint import STYLE, prettyprint as print
def __print(*args,**kwargs): pass
if not secrets.VERBOSE: print = __print
import time

class METERMANAGER:
    base = secrets.BASE
    __limit = 30
    __meters: Set[str] = set()
    __splash: Set[str] = set()
    __attempts:dict[str, int] = {}
    __booted:dict[str, int] = {}

    meters: Dict[str, SSHMeter] = {}

    class __FINALLY(Exception): pass

    @classmethod
    def __on_fresh(cls, ip: str):
        if ip in cls.__meters: return
        if cls.__attempts.get(ip,0) >= cls.__limit: return
        meter = SSHMeter(ip)
        try:
            meter.connect()
            try: send_fun_meter(meter)
            except: pass
            # check if booting
            if (splash:=meter.is_booting()):
                cls.__splash.add(ip)
                raise cls.__FINALLY
            # check if in splash
            elif (splash:=meter.in_splash()):
                cls.__splash.add(ip)
                raise cls.__FINALLY
            else:
                hn = meter.hostname
                # if just booted, give it some time
                if ip in cls.__splash or ip in cls.__attempts:
                    t0 = cls.__booted.get(ip,None)
                    if t0==None: 
                        print(f"[{hn}]🔧 Just booted? Giving it time to load up ...", fg="#008800")
                        t = time.time()
                        cls.__booted[ip] = t
                        meter.press('diagnostics')
                        raise cls.__FINALLY
                    elif time.time() - t0 > 20: pass
                    else: raise cls.__FINALLY

                # here, has booted+10s or was booted already
                meter.force_diagnostics()
                time.sleep(0.1)
                if not meter.in_diagnostics(): raise Exception
                cls.meters[ip] = meter
                cls.__meters.add(ip)
                print(f"✅ [{hn}] detected success", fg="#00ff00", style=STYLE.BOLD)


        except cls.__FINALLY: pass
        except: 
            if ip not in cls.__attempts:
                print(f"[{ip}]⚠️ couldn't connect. Meter booting or not a meter.", fg="#880000")
                print(f"[{ip}]ℹ️ will continue to try in background ...", fg="#888888", style=STYLE.DIM)
            cls.__attempts[ip] = cls.__attempts.get(ip, 0) + 1
            if cls.__attempts[ip] >= cls.__limit:
                print(f"[{ip}] failed to many times. gonna stop trying", fg="#ff0000")

        finally:
            meter.close()


    @classmethod
    def __on_stale(cls, ip: str):
        cls.meters[ip].close()
        cls.meters.pop(ip,None)
        cls.__meters.discard(ip)
        cls.__splash.discard(ip)
        cls.__booted.pop(ip,None)

    @classmethod
    def refresh(cls):
        current = set(ip_scanner.get_ips(base=cls.base, start=2, end=254))
        fresh = current - cls.__meters
        stale = cls.__meters - current

        for ip in fresh: cls.__on_fresh(ip)
        for ip in stale: cls.__on_stale(ip)

        return list(cls.__meters)
    
    @classmethod
    def list_meters(cls): return list(cls.__meters)
    @classmethod
    def get_meter(cls, ip: str): return cls.meters[ip]
        

if __name__ == "__main__":
    import time
    while True:
        time.sleep(2)
        print(METERMANAGER.refresh())         
 
