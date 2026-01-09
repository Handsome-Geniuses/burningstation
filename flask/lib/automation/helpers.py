
class StopAutomation(Exception):
    pass

def check_stop_event(shared):
    if hasattr(shared, 'stop_event') and shared.stop_event.is_set():
        raise StopAutomation("Stop event triggered")
