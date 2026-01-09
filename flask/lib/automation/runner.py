import threading
import traceback
from lib.meter.ssh_meter import SSHMeter
from lib.automation.listener import start_listener_thread
from lib.automation.tests import PROGRAM_REGISTRY, get_monitors
from lib.automation.shared_state import SharedState
from datetime import datetime

_SENTINEL = object()

def _resolve_devices(program_name: str, automation_kwargs: dict, shared: SharedState):
    """
    Resolve which devices (monitors) to register for this run
    monitors override precedence:
      1) automation_kwargs['monitors'] if present (even if [])
      2) get_monitors(program_name) from tests package
    """
    override = automation_kwargs.pop("monitors", _SENTINEL)
    if override is not _SENTINEL:
        devices = override or []
        shared.log(f"using override monitors for {program_name!r}: {devices}")
        return devices
    devices = get_monitors(program_name)
    return devices

def run_test_job(
    meter: SSHMeter,
    program_name: str,
    automation_kwargs: dict,
    shared: SharedState,
    log: bool = True,
    verbose: bool = False,
):
    """
    Runs a test job: optionally spins up modular listener with selected devices,
    runs the selected test, and manages shared state.
    """
    devices = _resolve_devices(program_name, automation_kwargs, shared)

    devices_enriched = []
    for dev_id, cfg in devices:
        cfg = dict(cfg or {})
        cfg.setdefault("meter_type", getattr(meter, "meter_type", ""))
        try:
            cfg.setdefault("firmwares", dict(meter.firmwares or {}))
        except Exception:
            cfg.setdefault("firmwares", {})
        devices_enriched.append((dev_id, cfg))

    # Start the modular listener only if needed (devices or logging/verbose)
    listener_thread = None
    logfile_name = None
    if log:
        logfile_name=f'[{meter.hostname}]{datetime.now().strftime("d%y%m%dt%H%M%S")}'
        if shared.current_program: logfile_name+=f"-{shared.current_program}"

    if devices or log or verbose:
        listener_thread = start_listener_thread(
            shared=shared,
            host=meter.host,
            pswd=meter.pswd,
            devices=devices_enriched,
            user=meter.user,
            save_logs=log,
            verbose=verbose,
            trace_lines=False,
            # kwargs
            logfile_name=logfile_name
        )

    try:
        if program_name not in PROGRAM_REGISTRY:
            raise ValueError(f"Unknown test: {program_name!r}")
        test_func = PROGRAM_REGISTRY[program_name]
        test_func(meter, shared=shared, **automation_kwargs)

    except Exception as exc:
        shared.log(f"Error running test {program_name!r} on {meter.host}: {type(exc).__name__}: {exc}", console=True)
        for line in traceback.format_exc().splitlines():
            shared.log(line, console=True)
        
        shared.last_error = str(exc)
        shared.stop_event.set()

    finally:
        # Ensure listener thread (if any) stops
        if listener_thread is not None:
            shared.end_listener.set()
            listener_thread.join(timeout=5)
