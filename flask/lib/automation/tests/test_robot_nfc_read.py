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

def test_robot_nfc_read(meter: SSHMeter, shared: SharedState = None, **kwargs):
    """ Navigate to the nfc diagnostics page, enable nfc, then wait for a card read """
    func_name = inspect.currentframe().f_code.co_name
    max_duration_s = int(kwargs.get("max_duration_s", 40))
    subtest = bool(kwargs.get("subtest", False))

    meter.set_ui_mode("charuco")
    robot = RobotClient()
    job_id = robot.run_program("run_nfc_card", {"meter_type": meter.meter_type, "meter_id": meter.hostname, "charuco_frame": kwargs.get("charuco_frame")})

    # print(f"{meter.host} {func_name} 1/1")
    # if shared and not subtest:
    #     shared.broadcast_progress(meter.host, func_name, 1, 1)

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
            if shared:
                check_stop_event(shared)
            
            found, data = robot.try_get_event("program_done", job_id=job_id, consume=True)
            if found:
                print(f"[NFC] Robot program finished but card still not detected... data: {data}")
                if shared:
                    shared.last_error = "robot finished without any card detection"
                    shared.stop_event.set()
                return # fail

            try:
                page = _fetch_ui_page(meter)
            except Exception as e:
                time.sleep(poll)
                if time.time() - start > max_duration_s:
                    if shared:
                        shared.last_error = 'max duration exceeded'
                        shared.stop_event.set()
                    return
                continue

            parsed = _parse_nfc_page(page)
            # print(f'[NFC] device={parsed.device} data="{parsed.data_raw}" card_masked="{parsed.card_masked}" card_last4="{parsed.card_last4}"')

            if parsed.card_masked is not None:
                print(f'[NFC] Card detected, last4={parsed.card_last4}')
                if shared:
                    shared.device_meta['last4'] = parsed.card_last4
                nfc_enabled = False
                # robot.wait_for_event("program_done", job_id=job_id, timeout=15)
                return  # success

            if time.time() - start > max_duration_s:
                if shared:
                    shared.last_error = 'max duration exceeded'
                    shared.stop_event.set()
                return

            if shared:
                check_stop_event(shared)
            time.sleep(poll)

    finally:
        if nfc_enabled:
            try:
                meter.press('minus')
            except Exception as _e:
                print(f'[NFC] Cleanup warning: failed to press [-]: {_e}')

