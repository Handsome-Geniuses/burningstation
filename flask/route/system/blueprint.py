# ================================================================
# File: blueprint.py
# Desc: handle routes
# ================================================================
import flask
import os
import signal
from lib.automation.jobs import start_job
from lib.sse.question import setResponse
from lib.utils import secrets
from .manager import *
from lib.gpio.gpio_setup import hardware_map

from lib.system import sim,override,station,program
from lib import database

from lib.store import store
bp = flask.Blueprint("hello", __name__)

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
    return flask.jsonify(hardware_map)


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

@bp.post("/<type>/<action>")
def handle_action(type, action):
    handler = handlers.get(type)
    if not handler:
        # 404 if unknown type
        return f"Unknown type '{type}'", 404

    data = flask.request.get_json() or {}
    # if secrets.MOCK and handler!=sim: sim.on_action(action, **data)
    if secrets.MOCK and handler!=sim: return sim.on_mock(handler,action,**data)
    return handler.on_action(action, **data)



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

    try:
        limit = int(args.get("limit", 10))
    except ValueError:
        return flask.jsonify({"error": "invalid limit"}), 400

    date_start = args.get("date_start")
    date_end = args.get("date_end")
    meter_id_raw = args.get("meter_id")
    status = args.get("status")

    try:
        meter_id = int(meter_id_raw) if meter_id_raw not in (None, "") else None
    except ValueError:
        return flask.jsonify({"error": "invalid meter_id"}), 400

    if status == "":
        status = None

    allowed_statuses = {"missing", "n/a", "pass", "fail"}
    if status is not None and status not in allowed_statuses:
        return flask.jsonify({
            "error": f"invalid status '{status}'",
            "allowed": sorted(allowed_statuses),
        }), 400

    try:
        res = database.retrieve_jobs_filtered(
            limit=limit,
            date_start=date_start,
            date_end=date_end,
            meter_id=meter_id,
            status=status,
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
        store.set_from_dict(data)
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
    return flask.jsonify(settings.model_dump())




