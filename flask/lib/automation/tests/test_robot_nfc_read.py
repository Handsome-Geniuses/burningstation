import time
import requests
import re, html
import inspect
from dataclasses import dataclass
from typing import Optional

from lib.meter.ssh_meter import SSHMeter
from lib.automation.shared_state import SharedState
from lib.automation.helpers import check_stop_event, StopAutomation
from lib.robot.robot_client import RobotClient


_PRE_RE = re.compile(r"<pre>(.*?)</pre>", re.I | re.S)
_DEV_RE = re.compile(r"device=(\w+)\s+timeout=(\d+)", re.I)
_PSV_RE = re.compile(r"params=(\d+)\s+structVer=(\d+)", re.I)
_DATA_RE = re.compile(r'data="([^"]*)"', re.I)
_CARD_RE = re.compile(r"Card read:\s*([Xx\d ]+)", re.I)

@dataclass
class NFCParse:
    has_contactless_block: bool
    device: Optional[str]
    timeout: Optional[int]
    params: Optional[int]
    struct_ver: Optional[int]
    data_raw: Optional[str]
    card_masked: Optional[str]
    card_last4: Optional[str]

def _parse_nfc_page(html_text: str) -> NFCParse:
    txt = html.unescape(html_text or "")
    m = _PRE_RE.search(txt)
    pre = m.group(1) if m else txt

    has_block = "Contactless Message:" in pre
    device = timeout = params = struct_ver = None
    data_raw = card_masked = card_last4 = None

    if has_block:
        m1 = _DEV_RE.search(pre)
        if m1:
            device = m1.group(1)
            timeout = int(m1.group(2))
        m2 = _PSV_RE.search(pre)
        if m2:
            params = int(m2.group(1))
            struct_ver = int(m2.group(2))
        m3 = _DATA_RE.search(pre)
        if m3:
            data_raw = m3.group(1)

        m4 = _CARD_RE.search(pre)
        if m4:
            card_masked = m4.group(1).strip()
            digits = re.sub(r"\D", "", card_masked)
            if len(digits) >= 4:
                card_last4 = digits[-4:]

    return NFCParse(
        has_contactless_block=has_block,
        device=device,
        timeout=timeout,
        params=params,
        struct_ver=struct_ver,
        data_raw=data_raw,
        card_masked=card_masked,
        card_last4=card_last4,
    )

def _fetch_ui_page(meter: SSHMeter, timeout: float = 2.0) -> str:
    url = f"http://{meter.host}:8005/UIPage.php"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text

def test_robot_nfc_read(meter: SSHMeter, shared: SharedState, **kwargs):
    """ Navigate to the nfc diagnostics page, enable nfc, then wait for a card read """
    func_name = inspect.currentframe().f_code.co_name
    max_duration_s = int(kwargs.get("max_duration_s", 40))
    subtest = bool(kwargs.get("subtest", False))

    shared.log(f"{meter.host} {func_name} 1/1")
    if not subtest:
        shared.broadcast_progress(meter.host, func_name, 1, 1)

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_nfc_card", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "charuco_frame": kwargs.get("charuco_frame")})

    if meter.in_diagnostics():
        meter.press('diagnostics'); meter.press('diagnostics')
    else:
        meter.press('diagnostics')

    meter.press('minus')
    meter.press('ok')
    for i in range(8):
        meter.press('plus')
    meter.press('ok')
    meter.press('plus'); meter.press('plus'); meter.press('plus')
    meter.press('ok')
    time.sleep(1)

    #! double check that we made it to the right page

    meter.press('plus')
    nfc_enabled = True

    start = time.time()
    poll = 0.5
    try:
        while True:
            check_stop_event(shared)
            
            found, data = robot.try_get_event("program_done", job_id=job_id, consume=True)
            if found:
                shared.log(f"Robot program finished but card still not detected... data: {data}")
                shared.last_error = "robot program finished without any card detected"
                shared.stop_event.set()
                return # fail

            try:
                page = _fetch_ui_page(meter)
            except Exception as e:
                time.sleep(poll)
                if time.time() - start > max_duration_s:
                    shared.last_error = 'max duration exceeded'
                    shared.stop_event.set()
                    return
                continue

            parsed = _parse_nfc_page(page)

            if parsed.card_masked is not None:
                shared.log(f'Card detected, last4={parsed.card_last4} | parsed={parsed}')
                shared.device_meta['last4'] = parsed.card_last4
                nfc_enabled = False
                time.sleep(8) # Gives grace period for NFC reader to send shutdown confirmation (or else NFCMonitor gets suppressed and cant cancel it once received)
                return  # success

            if time.time() - start > max_duration_s:
                shared.last_error = f'max duration exceeded ({max_duration_s} sec)'
                shared.stop_event.set()
                return

            check_stop_event(shared)
            time.sleep(poll)

    finally:
        if nfc_enabled:
            try:
                meter.press('minus')
            except Exception as _e:
                shared.log(f'Cleanup warning: failed to press [-] | {_e}', console=True)

