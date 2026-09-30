"""Per-meter status channel for operator-guided tests."""
from typing import Any, Dict, Tuple

from lib.automation.shared_state import SharedState
from lib.sse.sse_queue_manager import SSEQM


STATE_KEY = "operator_feedback_state"
RESPONSES_KEY = "operator_feedback_responses"


def publish_operator_feedback(
    meter,
    shared: SharedState,
    *,
    test: str,
    title: str,
    instruction: str,
    status: str,
    current: int = 0,
    total: int = 0,
    details: Dict[str, Any] | None = None,
    active: bool = True,
    error: str = "",
) -> Dict[str, Any]:
    """Broadcast and retain a safe UI snapshot for one operator subtest."""
    payload: Dict[str, Any] = {
        "ip": meter.host,
        "test": test,
        "title": title,
        "instruction": instruction,
        "status": status,
        "current": max(0, int(current)),
        "total": max(0, int(total)),
        "details": details or {},
        "active": bool(active),
        "error": str(error or ""),
    }
    shared.extras[STATE_KEY] = payload
    SSEQM.broadcast("operator_feedback", payload)
    return payload


def submit_operator_feedback_response(shared: SharedState, test: str, value: bool) -> None:
    responses = shared.extras.setdefault(RESPONSES_KEY, {})
    if not isinstance(responses, dict):
        responses = {}
        shared.extras[RESPONSES_KEY] = responses
    responses[test] = bool(value)


def consume_operator_feedback_response(shared: SharedState, test: str) -> Tuple[bool, bool]:
    """Return ``(received, value)`` while preserving a false response."""
    responses = shared.extras.get(RESPONSES_KEY)
    if not isinstance(responses, dict) or test not in responses:
        return False, False
    return True, bool(responses.pop(test))
