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

bp = flask.Blueprint("hello", __name__)


@bp.get("/")
def __hello():
    # print("hello")
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


@bp.get("/sse")
def __stream():
    if flask.request.headers.get("accept") == "text/event-stream":
        return flask.Response(event_stream(), content_type="text/event-stream")

@bp.get("hardware")
def __hardware():
    return flask.jsonify(hardware_map)


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
        meter_ip="192.168.137.157",
        program_name=prog,
        kwargs={"count":1},
    )

    if not ok:
        return {"error": msg}, 409  # Conflict: already running, etc.
    return {"status": "started"}, 200

    return "testing", 200