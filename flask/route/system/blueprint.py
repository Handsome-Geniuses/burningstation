# ================================================================
# File: blueprint.py
# Desc: handle routes
# ================================================================
import flask
import os
import signal
import socket
import struct
from lib.automation.jobs import start_job
from lib.sse.question import setResponse
from lib.utils import secrets
from lib.hardware import HardwareCapabilityUnavailable, hardware
from .manager import *
from lib.gpio.gpio_setup import hardware_map

from lib.system import sim,override,station,program
from lib import database

from lib.store import store
from lib.sse.sse_queue_manager import SSEQM
bp = flask.Blueprint("hello", __name__)

try:
    import fcntl
except ImportError:
    fcntl = None


def _host_without_port(value):
    if not value:
        return None

    host = value.split(",", 1)[0].strip()
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def _dedupe_addresses(addresses):
    deduped = []
    seen = set()

    for entry in addresses:
        key = (entry.get("interface"), entry.get("family"), entry.get("address"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)

    return deduped


def _linux_interface_ipv4_addresses():
    if fcntl is None:
        return []

    addresses = []
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        return addresses

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, interface in interfaces:
            try:
                request = struct.pack("256s", interface[:15].encode("utf-8"))
                response = fcntl.ioctl(sock.fileno(), 0x8915, request)
                address = socket.inet_ntoa(response[20:24])
            except OSError:
                continue

            addresses.append({
                "interface": interface,
                "family": "IPv4",
                "address": address,
                "source": "interface",
            })

    return addresses


def _request_host():
    forwarded_host = flask.request.headers.get("X-Forwarded-Host")
    return _host_without_port(forwarded_host or flask.request.host)


def _device_ip_addresses():
    return {
        "hostname": socket.gethostname(),
        "request_host": _request_host(),
        "addresses": _dedupe_addresses(_linux_interface_ipv4_addresses()),
    }

# ================================================================
# small helpers
# ================================================================
@bp.get("/")
def __hello():
    return "hello", 200

@bp.get("/test")
def __test():
    # print("hello")
    test_message()
    return "hello", 200

@bp.get("/suicide")
def __suicide():
    print("SHINDERU")
    os.kill(os.getpid(),signal.SIGKILL)
    return "",200

@bp.get("hardware")
def __hardware():
    return flask.jsonify({
        **hardware_map,
        "hardware": hardware.to_frontend(),
    })

@bp.get("/device/ip-addresses")
def __device_ip_addresses():
    return flask.jsonify(_device_ip_addresses())


# ================================================================
# sets up server-sent events stream
# ================================================================
@bp.get("/sse")
def __stream():
    if flask.request.headers.get("accept") == "text/event-stream":
        return flask.Response(event_stream(), content_type="text/event-stream")





# ================================================================
# asks a question
# ================================================================
@bp.post("/question/response")
def __request_response():
    args = flask.request.get_json()
    value = args.get("value", None)
    if value is None:
        return "", 400
    
    valid = setResponse(value)
    if not valid:
        return "invalid/incorrect type", 400

    return "", 200


# ================================================================
# handles actions for sim, override, station, program
# ================================================================
handlers = {
    "sim": sim,
    "override": override,
    "station": station,
    "program": program,
}


def require_action_capability(type, action, data):
    if type == "override" and action == "motor":
        hardware.require("motor_control")
    elif type == "station":
        if action == "load":
            hardware.require("belt")
        elif action == "tower":
            hardware.require("tower")
        elif action == "lamp":
            hardware.require("lamp")
        elif action == "emergency":
            hardware.require("emergency_gpio")
        elif action == "mode" and data.get("value") == "auto":
            hardware.require("auto_mode")
    elif type == "sim":
        if action == "roller":
            hardware.require("motor_control")
        elif action == "meter":
            hardware.require("meter_detection")
        elif action == "emergency":
            hardware.require("emergency_gpio")

@bp.post("/<type>/<action>")
def handle_action(type, action):
    handler = handlers.get(type)
    if not handler:
        # 404 if unknown type
        return f"Unknown type '{type}'", 404

    data = flask.request.get_json() or {}
    try:
        require_action_capability(type, action, data)
        # if secrets.MOCK and handler!=sim: sim.on_action(action, **data)
        if secrets.MOCK and handler!=sim: return sim.on_mock(handler,action,**data)
        return handler.on_action(action, **data)
    except HardwareCapabilityUnavailable as exc:
        return flask.jsonify({
            "error": str(exc),
            "capability": exc.capability,
            "profile": exc.profile,
        }), 409



# ================================================================
# retrieve database
# ================================================================
@bp.get("/database/<table>")
def __database(table):
    args = flask.request.args.to_dict()
    limit = int(args.get("limit", 10))
    offset = int(args.get("offset", 0))
    
    if table == "meter_job":
        res = database.retrieve_jobs(limit=limit, offset=offset)
        # for row in res: row.pop("jctl", None)

    # elif table == "meters":
        # res = database.retrieve_meters(limit=limit, offset=offset)
    else:
        return f"unknown table '{table}'", 404

    # print(res)
    return flask.jsonify(res), 200


@bp.get("/database/meter_job")
def get_meter_jobs():
    args = flask.request.args.to_dict()

    limit = int(args.get("limit", 10))
    offset = int(args.get("offset", 0))

    date_start = args.get("date_start")
    date_end = args.get("date_end")
    meter_id_raw = args.get("meter_id")
    status_raw_values = flask.request.args.getlist("status")

    try:
        meter_id = int(meter_id_raw) if meter_id_raw not in (None, "") else None
    except ValueError:
        return flask.jsonify({"error": "invalid meter_id"}), 400

    statuses = [
        status
        for raw_value in status_raw_values
        for status in (value.strip() for value in raw_value.split(","))
        if status
    ] or None

    allowed_statuses = {"missing", "n/a", "pass", "fail"}
    invalid_statuses = [status for status in (statuses or []) if status not in allowed_statuses]
    if invalid_statuses:
        return flask.jsonify({
            "error": f"invalid status '{invalid_statuses[0]}'",
            "allowed": sorted(allowed_statuses),
        }), 400

    try:
        res = database.retrieve_jobs_filtered(
            limit=limit,
            offset=offset,
            date_start=date_start,
            date_end=date_end,
            meter_id=meter_id,
            status=statuses,
        )
    except Exception as e:
        return flask.jsonify({"error": str(e)}), 500

    return flask.jsonify(res), 200















@bp.get("/testing")
def __testing():
    # args = flask.request.get_json()
    args = flask.request.args.to_dict()
    ip = args.get("ip")  # ip address
    prog = args.get("prog")  # program number
    extra = args.get("args")  # additional arguments for configurations

    print(args)
    if ip is None:
        return "could not find device", 404

    if prog is None:
        return "no prog number specified", 404
    
    ok, msg = start_job(
        meter_ip=ip,
        program_name=prog,
        kwargs={"numBurnCycles":1, 'printer':1, 'count': 1},
    )

    if not ok:
        return {"error": msg}, 409  # Conflict: already running, etc.
    return {"status": "started"}, 200

    return "testing", 200




# ================================================================
# settings
# ================================================================
@bp.get("/settings")
def get_settings():
    return flask.jsonify(store.to_frontend())

@bp.get("/settings/values")
def get_values():
    return flask.jsonify(store.to_dict())

@bp.get("/settings/schema")
def get_schema():
    return flask.jsonify(store.get_schema())

@bp.post("/settings") # careful here, for lazy update full tree
def set_settings():
    data = flask.request.get_json()

    if not data:
        return {"error": "No JSON body provided"}, 400

    try:
        settings = store.set_from_dict(data)
        SSEQM.broadcast("settings", settings.model_dump())
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}, 400
    
@bp.patch("/settings")  # will probably use this mostly. partial updates
def update_settings():
    data = flask.request.get_json()

    if not data:
        return {"error": "No JSON body provided"}, 400

    try:
        updated = store.update_from_dict(data)
        SSEQM.broadcast("settings", updated.model_dump())
        return flask.jsonify(updated.model_dump())
    except Exception as e:
        return {"error": str(e)}, 400
    
@bp.post("/settings/save")
def save_settings():
    store.save()
    return {"status": "saved"}

@bp.post("/settings/reload")
def reload_settings():
    settings = store.reload()
    SSEQM.broadcast("settings", settings.model_dump())
    return flask.jsonify(settings.model_dump())




