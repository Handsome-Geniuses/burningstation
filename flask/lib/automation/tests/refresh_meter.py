from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.sse.sse_queue_manager import SSEQM as master

def refresh_meter(meter: SSHMeter, shared: SharedState = None, **kwargs):
    print(f">> REFRESHING METER INFORMATION!")

    isConnected = meter.connected
    if (not isConnected): meter.connect()
    meter.status='ready'
    info = meter.get_info(force=True)
    if (not isConnected): meter.close()
    master.broadcast("meter", {"ip": meter.host, "alive": True, "info": info})
    check_stop_event(shared)