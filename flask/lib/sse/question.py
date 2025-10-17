from typing import Literal
from lib.sse.sse_queue_manager import SSEQM
import threading
from lib.utils import literalValidGenerator


QTypes = Literal["boolean", "string", "number"]
validQType = literalValidGenerator(QTypes)

confirmation_event = threading.Event()
confirmation_event.clear()
confirmation_value = None
confirmation_type: QTypes = "boolean"


def isValidResponse(response, qtype: QTypes = None):
    if qtype == None:
        qtype = confirmation_type
    if not validQType(qtype):
        raise ValueError(qtype)

    if qtype == "boolean":
        return isinstance(response, bool)
    elif qtype == "string":
        return isinstance(response, str)
    elif qtype == "number":
        return isinstance(response, (int, float))
    return False


def setResponse(response):
    if not isValidResponse(response):
        print("not valid")
        return False
    global confirmation_value
    if not confirmation_event.is_set():
        confirmation_value = response
        confirmation_event.set()
    return True


def ask_clients(
    msg: str = "yes or no?",
    title: str = "Question",
    id: str = "question",
    qtype: QTypes = "boolean",
    src=None,
    confirm="yes",
    cancel="no",
):
    global confirmation_event
    global confirmation_value
    global confirmation_type

    if not validQType(qtype):
        raise ValueError(qtype)

    # setup to wipe repeat calls without answers just in case
    if not confirmation_event.is_set():
        confirmation_event.set()  # unblocks all old .wait()
        confirmation_event = threading.Event()
        print("WARNING! Previous question unanswered. Clearing it.")

    # reset values
    confirmation_event.clear()
    confirmation_value = None
    confirmation_type = qtype

    # build the payload
    payload = {
        "msg": msg,
        "title": title,
        "qtype": qtype,
        "id": id,
        "src": src,
        "dataurl": None,
        "confirm": confirm,
        "cancel": cancel,
    }

    # broadcast the question
    SSEQM.broadcast("question", payload)
    print(f"[QUESTION] asking --> {title} | {msg}")

    # wait until any client responds
    confirmation_event.wait()
    # no confirmation_value cause wipe? return
    if confirmation_value == None: return None

    # tell clients response
    payload["response"] = confirmation_value
    SSEQM.broadcast("question", payload)
    print(f"[QUESTION] response --> {confirmation_value}")

    return confirmation_value

