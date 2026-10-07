
class StopAutomation(Exception):
    pass

def check_stop_event(shared):
    if hasattr(shared, 'stop_event') and shared.stop_event.is_set():
        if not getattr(shared, 'abort_event', None) or not shared.abort_event.is_set():
            operator_failure = getattr(shared, 'extras', {}).get('operator_failure')
            if isinstance(operator_failure, dict) and operator_failure.get('reason'):
                raise StopAutomation(operator_failure['reason'])
            reason = getattr(shared, 'extras', {}).get('mock_failure')
            if reason:
                raise StopAutomation(reason)
        raise StopAutomation("Stop event triggered")
