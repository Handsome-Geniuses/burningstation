# ================================================================
# File: blueprint.py
# Desc: handle routes
# ================================================================
import flask
import os
import signal
from lib.sse.question import setResponse
from lib.utils import secrets
from .manager import *
# import lib.system.sim as sim
# import lib.system.override as override
# import lib.system.station as station
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

# @bp.post("/sim/<action>")
# def __sim(action):
#     return sim.on_action(action, **flask.request.get_json())
# @bp.post('/override/<action>')
# def __override(action):
#     return override.on_action(action, **flask.request.get_json())
# @bp.post('/station/<action>')
# def __station(action):
#     return station.on_action(action, **flask.request.get_json())
# @bp.post("/program/<action>")
# def __program(action):
#     return program.on_action(action, **flask.request.get_json())



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