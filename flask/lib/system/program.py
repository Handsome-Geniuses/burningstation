# ====================================================
# 
# ====================================================
import threading
import time

from lib.gpio import HWGPIO, HWGPIO_MONITOR, emergency

_program_lock = threading.Lock()
_program_running = False
_program_emergency_stop = False

def before_program(): pass
def after_program(): pass

def program_operation(timeout: float = None):
    """Decorator for program operations with before/after hooks"""

    def decorator(fn):
        def wrapper(**kwargs):
            global _program_running
            global _program_lock
            global _program_emergency_stop
            
            with _program_lock:
                if _program_emergency_stop:
                    print("program emergency stop active!")
                    return "Emergency stop active", 500
                if _program_running:
                    print("program busy!")
                    return "Already running", 409
                _program_running = True

            result = [("", 200)]
            
            on_done = kwargs.get('on_done', lambda: print(f"[{fn.__name__}] completed"))
            on_timeout = kwargs.get('on_timeout', lambda: print(f"[{fn.__name__}] timed out"))
            before_action = kwargs.get('before_action', before_program)
            after_action = kwargs.get('after_action', after_program)
            
            def run_operation():
                global _program_running
                global _program_lock
                try:
                    before_action()
                    res = fn(**kwargs)
                    if res:
                        result[0] = res
                finally:
                    after_action()
                    with _program_lock:
                        _program_running = False
                    
                    if on_done:
                        on_done()
            
            thread = threading.Thread(target=run_operation, daemon=True)
            thread.start()
            
            if timeout:
                def check_timeout():
                    thread.join(timeout=timeout)
                    if thread.is_alive():
                        print(f"Operation timed out after {timeout}s")
                        if on_timeout:
                            on_timeout()
                        with _program_lock:
                            _program_running = False
                
                threading.Thread(target=check_timeout, daemon=True).start()

            return result[0]

        return wrapper

    return decorator


def program_emergency_stop():
    """Activate emergency stop - prevents new programs from starting"""
    global _program_emergency_stop
    with _program_lock:
        _program_emergency_stop = True
    print("Program emergency stop activated!")


def program_emergency_reset():
    """Reset emergency stop flag - call this to allow programs again"""
    global _program_emergency_stop
    with _program_lock:
        _program_emergency_stop = False
    print("Program emergency stop cleared!")

def program_emergency_event(p:HWGPIO):
    if p.state: program_emergency_stop()
    else: program_emergency_reset()
HWGPIO_MONITOR.add_listener(emergency,program_emergency_event)

@program_operation
def some_action(**kwargs):
    pass

def on_action(action, **kwargs):
    res = None
    return res if res is not None else ("", 200)

__all__ = ['on_action']

