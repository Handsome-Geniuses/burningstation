"""LAN discovery and registry; per-meter initialization never holds up scanning.

Keep ``lib/docs/meter/supervisor.md`` in sync with discovery/admission changes.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Dict, Set
import re
import time

import ip_scanner
from lib.meter.ssh_meter import SSHMeter
from lib.meter.lifecycle import MeterSession, session_for
from lib.meter.supervisor import MeterSupervisor
from lib.sse.sse_queue_manager import SSEQM, key_payload
from lib.utils import secrets
from lib.database import insert_sshmeter, update_meter_work_order
from lib.system.bay_guess import bootstrap_bay0_partial_guess, clear_meter, empty_bay_guess
from lib.system.states import states


class METERMANAGER:
    """Identify reachable IPs asynchronously, then admit only initialized meters.

    Registry presence lets the UI show booting/initializing progress; it is not
    permission to run a job. The supervisor establishes app readiness first,
    then admission owns navigation while inventory and DB metadata are loaded.
    Scan misses retain busy/explicitly sleeping sessions under their existing
    policy. A new physical identity gets a new session and lifecycle logfile.
    """
    MeterClass = SSHMeter
    base = secrets.BASE
    address_range = secrets.RANGE
    __discovery_lock = RLock()
    __meters: Set[str] = set()
    __attempts: dict[str, int] = {}
    __retry_at = {}
    __stale_counts: Dict[str, int] = {}
    __STALE_THRESHOLD = 2
    __reachable = set()
    __inflight = set()
    __newly_ready = set()
    __workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="meter-discovery")
    meters: Dict[str, MeterClass] = {}

    @classmethod
    def __on_stale(cls, ip: str, *, force: bool = False):
        with cls.__discovery_lock:
            cls.__stale_counts[ip] = cls.__stale_counts.get(ip, 0) + 1
            meter = cls.meters.get(ip)
            session = session_for(meter) if meter is not None else None
            if session is not None and session.supervisor:
                if cls.__stale_counts[ip] <= cls.__STALE_THRESHOLD or force:
                    session.supervisor._log("discovery_scan_miss", count=cls.__stale_counts[ip], force=force,
                                            owner=session.owner, sleep_pending=session.sleep_pending)
            if not force:
                if cls.__stale_counts[ip] < cls.__STALE_THRESHOLD:
                    return  # A missed probe is not a frontend removal.
                if session is not None and session.sleep_pending:
                    return  # Keep an explicitly sleeping meter available to wake.
                if meter is not None and getattr(meter, "status", None) == "busy":
                    # Preserve the original busy-meter policy. Ping misses alone
                    # must not interrupt a working test; the supervisor verifies
                    # SSH/application loss independently.
                    return
            if meter is not None:
                session = session_for(meter)
                if session is not None:
                    session.close()
                meter.close()
            cls.meters.pop(ip, None)
            cls.__meters.discard(ip)
            cls.__stale_counts.pop(ip, None)
            cls.__attempts.pop(ip, None)
            cls.__retry_at.pop(ip, None)
            cls.__newly_ready.discard(ip)
            states["bayGuess"] = clear_meter(states.get("bayGuess", empty_bay_guess()), ip)
            SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))
            SSEQM.broadcast("meter", {"ip": ip, "alive": False, "info": None})

    @classmethod
    def __identify(cls, ip):
        """Connect and validate identity before starting continuous capture/admission."""
        meter = None
        retained = False
        try:
            MeterSupervisor.discovery_log("ssh_identification_started", ip)
            meter = cls.MeterClass(ip)
            meter.connect()
            hostname = meter.hostname
            if not re.fullmatch(r"\d{8}", hostname):
                raise ValueError("SSH host is not an identified meter")
            session = MeterSession(meter)
            session.info = {"ip": ip, "hostname": hostname, "meter_type": "",
                            "firmwares": {}, "module_info": {}, "system_versions": {}}
            meter.session = session
            with cls.__discovery_lock:
                if ip not in cls.__reachable or ip in cls.meters:
                    return
                cls.meters[ip] = meter
                cls.__meters.add(ip)
                retained = True
            SSEQM.broadcast("meter", {"ip": ip, "alive": True, "info": meter.public_info()})
            supervisor = MeterSupervisor(session)
            supervisor.start()
            supervisor._log("discovery_identified", ip=ip, hostname=hostname,
                            previous_connection_attempts=cls.__attempts.get(ip, 0))
            # The normal refresh pass queues admission once MS3 is ready.
        except Exception as exc:
            with cls.__discovery_lock:
                cls.__attempts[ip] = cls.__attempts.get(ip, 0) + 1
                # Back off unidentified devices, never permanently blacklist an
                # address that may later be occupied by a real meter.
                # TODO: On a mixed LAN, reachable routers, robots, and laptops
                # are retried over SSH every 60 s indefinitely. Keep quick
                # retries for a booting meter, then consider a longer cooldown
                # for persistently unidentified IPs. Do not require a static
                # exclusion list or permanently suppress an IP: devices and
                # addresses can change. Reset the cooldown when an IP leaves
                # the scan, as refresh() already does for this retry state.
                cls.__retry_at[ip] = time.monotonic() + min(60, 2 ** min(cls.__attempts[ip], 6))
            MeterSupervisor.discovery_log("ssh_identification_failed", ip, error=str(exc),
                                          retry_in_s=min(60, 2 ** min(cls.__attempts[ip], 6)))
            if retained:
                # Startup failed after early registration. Forget that exact
                # object so a later refresh can identify it again.
                with cls.__discovery_lock:
                    removed = cls.meters.get(ip) is meter
                    if removed:
                        cls.meters.pop(ip)
                        cls.__meters.discard(ip)
                session.close()
                retained = False
                if removed:
                    SSEQM.broadcast("meter", {"ip": ip, "alive": False, "info": None})
        finally:
            if meter is not None and not retained:
                meter.close()
            with cls.__discovery_lock:
                cls.__inflight.discard(ip)

    @classmethod
    def __admit(cls, ip, meter, session):
        """Attempt normal inventory/DB initialization once on the discovery pool.

        refresh() schedules another attempt when recovery is ready. There is no
        separate admission thread or polling loop per meter. The epoch still
        protects a scan interrupted by restart; optional modules remain optional.
        """
        epoch = None
        try:
            with session.condition:
                if session.stopped.is_set() or not session.ready or session.admitted or session.owner is not None:
                    return
                session.owner = "admission"
                epoch = session.epoch
            with session.bind("admission"):
                session.initializing("Reading hardware modules, firmware, region, and system versions")
                info = meter.get_info(force=True)
                session.checkpoint(epoch)
                session.initializing("Saving identified meter and work order")
                row = insert_sshmeter(meter)
                meter.db_id = row[0]
                work_order = states.get("workOrder")
                if work_order is not None:
                    try:
                        update_meter_work_order(meter.db_id, int(work_order))
                    except Exception as exc:
                        # Original policy: work-order association is best effort;
                        # it must not restart initialization of a usable meter.
                        if session.supervisor:
                            session.supervisor._log("work_order_update_failed", work_order=work_order, error=str(exc))
                        SSEQM.broadcast("notify", {"ntype": "error", "msg": "Work order update failed",
                                                  "description": f"{meter.hostname} | {work_order}: {exc}"})
                session.info = info
                if states.get("mode") == "auto":
                    # Preserve the original auto-mode upload, but finish it
                    # under admission ownership before publishing readiness.
                    session.initializing("Preparing custom display for auto mode")
                    try:
                        meter.setup_custom_display()
                    except Exception as exc:
                        # Original setup failure did not reject a valid meter.
                        if session.supervisor:
                            session.supervisor._log("display_setup_failed", error=str(exc))
                        SSEQM.broadcast("notify", {"ntype": "error",
                                                  "msg": "Meter display setup failed",
                                                  "description": f"{meter.hostname}: {exc}"})
                    session.checkpoint(epoch)
                session.admitted = True
                session.info.pop("initialization_error", None)
                if session.supervisor:
                    session.supervisor._log("initialization_complete", info=info)
            with cls.__discovery_lock:
                if cls.meters.get(ip) is not meter:
                    return
                cls.__newly_ready.add(ip)
                cls.__attempts.pop(ip, None)
                states["bayGuess"] = bootstrap_bay0_partial_guess(
                    states.get("bayGuess", empty_bay_guess()), states.get("mds", []), cls.meters.keys())
            SSEQM.broadcast("meter", {"ip": ip, "alive": True, "info": meter.public_info()})
            SSEQM.broadcast("state", key_payload("bayGuess", states["bayGuess"]))
        except Exception as exc:
            session.info["initialization_error"] = str(exc)
            session.interrupt("Initialization incomplete: " + str(exc))
            if session.supervisor:
                session.supervisor._log("initialization_failed", error=str(exc), epoch=epoch)
        finally:
            if epoch is not None:
                session.release("admission")
            with cls.__discovery_lock:
                cls.__inflight.discard(ip)

    @classmethod
    def __on_fresh(cls, ip):
        if ip in cls.meters or ip in cls.__inflight or time.monotonic() < cls.__retry_at.get(ip, 0):
            return False
        cls.__inflight.add(ip)
        cls.__workers.submit(cls.__identify, ip)
        return False

    @classmethod
    def refresh(cls):
        """Scan once, schedule work, and return (newly admitted, missed, registered IPs)."""
        with cls.__discovery_lock:
            # Preserve the original serialized scan: concurrent callers must
            # not apply an older reachability result after a newer scan.
            current = set(ip_scanner.get_ips(base=cls.base, start=cls.address_range[0],
                                            end=cls.address_range[1], timeout=1, concurrency=500))
            cls.__reachable = current
            for ip in set(cls.__attempts) - current:
                cls.__attempts.pop(ip, None)
                cls.__retry_at.pop(ip, None)
            for ip in current & cls.__meters:
                cls.__stale_counts.pop(ip, None)
                session = session_for(cls.meters[ip])
                if session is None:
                    continue
                if session.identity_mismatch and session.owner is None:
                    cls.__on_stale(ip, force=True)
                elif not session.admitted and session.ready and session.owner is None and ip not in cls.__inflight:
                    cls.__inflight.add(ip)
                    cls.__workers.submit(cls.__admit, ip, cls.meters[ip], session)
            for ip in current - cls.__meters:
                cls.__on_fresh(ip)
            stale = cls.__meters - current
            for ip in list(stale):
                cls.__on_stale(ip)
            fresh = cls.__newly_ready & current
            cls.__newly_ready -= fresh
            result = fresh, stale, list(cls.__meters)
        cls.close_idle_connections()
        return result

    @classmethod
    def wipe(cls):
        """Forget unreachable or idle meters; preserve reachable busy meters."""
        # Last-resort operator action retained from the original station.
        # Reassess for lifecycle sessions: a missed scan can force-retire
        # a busy or explicitly sleeping meter.
        with cls.__discovery_lock:
            if not cls.meters:
                return {"removed": [], "preserved": []}
            reachable = set(ip_scanner.get_ips(
                base=cls.base, start=cls.address_range[0],
                end=cls.address_range[1], timeout=1, concurrency=500,
            ))
            removed, preserved = [], []
            for ip, meter in list(cls.meters.items()):
                if ip in reachable and getattr(meter, "status", None) == "busy":
                    cls.__stale_counts.pop(ip, None)
                    preserved.append(ip)
                else:
                    cls.__on_stale(ip, force=True)
                    removed.append(ip)
            return {"removed": removed, "preserved": preserved}

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
