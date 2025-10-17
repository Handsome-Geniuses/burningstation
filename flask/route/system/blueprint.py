# ================================================================
# File: blueprint.py
# Desc: handle routes
# ================================================================
import flask
from .manager import *
from .sim import on_action

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


@bp.get("/sse")
def __stream():
    if flask.request.headers.get("accept") == "text/event-stream":
        return flask.Response(event_stream(), content_type="text/event-stream")


@bp.post("/sim/<action>")
def __roller(action):
    return on_action(action, **flask.request.get_json())


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
