#================================================================
# File: blueprint.py
# Desc: handle routes
#================================================================
import flask
from .manager import *

bp = flask.Blueprint('hello',__name__)

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
