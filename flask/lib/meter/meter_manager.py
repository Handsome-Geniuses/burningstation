from typing import Dict, Set, TypedDict
import ip_scanner
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.meter.fun import send_fun_meter
from lib.meter.ssh_meter import SSHMeter
from lib.utils import secrets
from lib.database import insert_sshmeter, update_meter_work_order
from lib.system.bay_guess import bootstrap_bay0_partial_guess, clear_meter, empty_bay_guess
from lib.system.states import states
from prettyprint import STYLE, prettyprint as print


def __print(*args, **kwargs):
    pass


if not secrets.VERBOSE:
    print = __print
import datetime


class METERMANAGER:
    MeterClass = SSHMeter
    base = secrets.BASE
    address_range = secrets.RANGE
    __limit = 30
    __meters: Set[str] = set()
    __splash: Set[str] = set()
    __attempts: dict[str, int] = {}
    __stale_counts: Dict[str, int] = {}
    __STALE_THRESHOLD = 2
    __MIN_APP_RUNTIME_SECONDS = 70

    meters: Dict[str, MeterClass] = {}

    class __FINALLY(Exception):
        pass

    @staticmethod
    def _timestamp():
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    @classmethod
    def __on_stale(cls, ip: str):
        """Track stale detections and remove inactive meters once threshold is met. Defer romoval if meter is busy."""
        cls.__stale_counts[ip] = cls.__stale_counts.get(ip, 0) + 1

        if cls.__stale_counts[ip] >= cls.__STALE_THRESHOLD:
            if ip in cls.meters:
                meter = cls.meters[ip]
                hn = meter.hostname if hasattr(meter, 'hostname') else "unknown"
                if getattr(meter, "status", None) == "busy":
                    print(
                        f"[{cls._timestamp()}] STALE: {ip} ({hn}) removal deferred because meter is busy",
                        fg="#888800",
                    )
                    return
                print(f"[{cls._timestamp()}] STALE: {ip} ({hn}) removed from known meters", fg="#888800")
                SSEQM.broadcast(
                    "notify",
                    {
                        "ntype": "warn",
                        "msg": "Meter Disconnected",
                        "description": f"{ip} | {hn}",
                    },
                )

            cls.meters[ip].close()
            cls.meters.pop(ip, None)
            cls.__meters.discard(ip)
            cls.__splash.discard(ip)
            cls.__stale_counts.pop(ip, None)
            cls.__attempts.pop(ip, None)
            states["bayGuess"] = clear_meter(states.get("bayGuess", empty_bay_guess()), ip)
            SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))
        else:
            print(
                f"[{cls._timestamp()}] STALE (ignored): {ip} failed ping, count={cls.__stale_counts[ip]}/{cls.__STALE_THRESHOLD}",
                fg="#888800",
            )

        SSEQM.broadcast(
            "meter",
            {
                "ip": ip,
                "alive": False,
                "info": None,
            },
        )

    @classmethod
    def __on_fresh(cls, ip: str):
        if ip in cls.__meters:
            return False
        if cls.__attempts.get(ip, 0) >= cls.__limit:
            return False

        meter = METERMANAGER.MeterClass(ip)
        try:
            meter.connect()

            # check if booting
            if splash := meter.is_booting():
                cls.__splash.add(ip)
                print(
                    f"[{ip}] Meter is still booting; waiting before retrying ...",
                    fg="#888800",
                )
                raise cls.__FINALLY
            # check if in splash
            elif splash := meter.in_splash():
                cls.__splash.add(ip)
                print(
                    f"[{ip}] Meter UI is still in the splash screen; "
                    "waiting before retrying ...",
                    fg="#888800",
                )
                raise cls.__FINALLY
            else:
                hn = meter.hostname
                if not meter.in_diagnostics():
                    print(f"[{hn}-{ip}] Attempting to enter diagnostics ...", fg="#888800")
                    meter.force_diagnostics()
                try:
                    runtime_info = meter.get_app_runtime_info()
                except RuntimeError as e:
                    print(
                        f"[{hn}-{ip}] MS3 runtime is not available yet: {e}",
                        fg="#888800",
                    )
                    raise cls.__FINALLY

                runtime_seconds = runtime_info["runtime_seconds"]
                if runtime_seconds <= cls.__MIN_APP_RUNTIME_SECONDS:
                    print(
                        f"[{hn}-{ip}]🔧 Waiting for modules to initialize "
                        f"({runtime_seconds}/{cls.__MIN_APP_RUNTIME_SECONDS} seconds) ...",
                        fg="#008800",
                    )
                    raise cls.__FINALLY

                if not meter.in_diagnostics():
                    message = (
                        f"[{hn}-{ip}] Meter did not enter diagnostics; "
                        "will retry in the background ..."
                    )
                    print(message, fg="#880000")
                    raise RuntimeError(message)

                # add information to database
                try:
                    res = insert_sshmeter(meter)
                    meter_id = res[0]  # meter row id
                    print(
                        f"💾 [{hn}] database insert success (id={meter_id})",
                        fg="#00aa00",
                    )
                    meter.db_id = meter_id
                    work_order = states.get("workOrder")
                    if work_order is not None:
                        try:
                            update_meter_work_order(meter_id, int(work_order))
                            print(
                                f"💾 [{hn}] work_order set to {work_order}",
                                fg="#00aa00",
                            )
                        except Exception as e:
                            print(f"⚠️ [{hn}] work_order update failed: {e}", fg="#880000")
                            SSEQM.broadcast(
                                "notify",
                                {
                                    "ntype": "error",
                                    "msg": "Work order update failed",
                                    "description": f"{hn} | {work_order}",
                                },
                            )

                except Exception as e:
                    print(f"⚠️ [{hn}] database insert failed: {e}", fg="#880000")
                    raise e

                # add to known meters
                cls.meters[ip] = meter
                cls.__meters.add(ip)
                states["bayGuess"] = bootstrap_bay0_partial_guess(
                    states.get("bayGuess", empty_bay_guess()),
                    states.get("mds", []),
                    cls.meters.keys(),
                )

                # send FUN data
                # try: send_fun_meter(meter)
                # except: pass
                print(
                    f"✅ [{hn}-{ip}] added to active meters",
                    fg="#00ff00",
                    style=STYLE.BOLD,
                )
                SSEQM.broadcast(
                    "notify",
                    {
                        "ntype": "success",
                        "msg": "Meter Connected",
                        "description": f"{ip} | {hn}",
                    },
                )
                SSEQM.broadcast(
                    "meter",
                    {
                        "ip": ip,
                        "alive": True,
                        "info": meter.get_info(),
                    },
                )
                SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))
                return True

        except cls.__FINALLY:
            pass
        except Exception as e:
            if ip not in cls.__attempts:
                print(
                    f"[{ip}]⚠️ couldn't connect. Meter booting or not a meter.",
                    fg="#880000",
                )
                print(
                    f"[{ip}]ℹ️ will continue to try in background ...",
                    fg="#888888",
                    style=STYLE.DIM,
                )
            cls.__attempts[ip] = cls.__attempts.get(ip, 0) + 1
            if cls.__attempts[ip] >= cls.__limit:
                print(f"[{ip}] failed to many times. gonna stop trying", fg="#ff0000")

            # print("----------------------------", fg="#444444", style=STYLE.DIM)
            # print(e, fg="#444444", style=STYLE.DIM)
            # print("----------------------------", fg="#444444", style=STYLE.DIM)

        finally:
            meter.close()

    @classmethod
    def refresh(cls):
        current = set(
            ip_scanner.get_ips(
                base=cls.base,
                start=cls.address_range[0],
                end=cls.address_range[1],
                timeout=1,
                concurrency=500,
            )
        )
        fresh = current - cls.__meters
        stale = cls.__meters - current
        # if fresh: print(f"[{cls._timestamp()}] REFRESH: Found {len(fresh)} new live IPs: {sorted(fresh)}", fg="#000fff")
        # if stale: print(f"[{cls._timestamp()}] REFRESH: {len(stale)} stale IPs: {sorted(stale)}", fg="#000fff")

        alive_known = current & cls.__meters
        for ip in alive_known:
            cls.__stale_counts.pop(ip, None)

        valid_fresh = set()

        for ip in fresh:
            if cls.__on_fresh(ip):
                valid_fresh.add(ip)

        for ip in stale: cls.__on_stale(ip)

        cls.close_idle_connections()

        return valid_fresh, stale, list(cls.__meters)

    @classmethod
    def close_idle_connections(cls):
        """Ask each known meter to release idle pooled SSH connections."""
        for meter in list(cls.meters.values()):
            try:
                meter.close_if_idle()
            except Exception:
                pass
    
    @classmethod
    def list_meters(cls):
        return list(cls.__meters)

    @classmethod
    def get_meter(cls, ip: str):
        return cls.meters[ip]

    @classmethod
    def stale_meter(cls, ip: str):
        cls.__on_stale(ip)

    @classmethod
    def stale_all_meters(cls):
        for ip in list(cls.__meters):
            cls.__on_stale(ip)


if __name__ == "__main__":

    import time

    while True:
        time.sleep(1)
        fresh, stale, ips = METERMANAGER.refresh()
        print(f"ips: {ips}")
        print(f"fresh: {fresh}, stale: {stale}")
