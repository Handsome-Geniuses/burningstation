# class to hold ssh-meter. for states or what not
from typing import  Optional, Literal, TypedDict, Dict, Tuple
# from lib.ssh.client import SSHClient
from paramiko import SSHException
import sshkit
import requests
import re
import time
import os
import math
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.utils import secrets
from lib.meter.display_utils import (
    CHARUCO_PATHS, write_ui_page, write_ui_overlay,
    upload_image, is_custom_display_current, get_apriltag_path
)


DEVICE_TO_MODULE = {
    'printer': 'PRINTER',
    'coin shutter': 'COIN_SHUTTER',
    'nfc': 'KIOSK_NFC',
    'modem': 'MK7_XE910',
    'screen test': 'yes'
}

class Firmwares(TypedDict):
    MK7_XE910: str
    KIOSK_NFC: str
    MSPM_PWR: str
    KBD_CONTROLLER: str
    COIN_SHUTTER: str
    EMV_CONTACT: str
    KIOSK_III: str
    MK7_RFID: str
    PRINTER: str
    BNA: str
    MK7_VALIDATOR: str
    KEY_PAD_2: str

defaultFirmwares:Firmwares = {
    'MK7_XE910': '',
    'KIOSK_NFC': '',
    'MSPM_PWR': '',
    'KBD_CONTROLLER': '',
    'COIN_SHUTTER': '',
    'EMV_CONTACT': '',
    'KIOSK_III': '',
    'MK7_RFID': '',
    'PRINTER': '',
    'BNA': '',
    'MK7_VALIDATOR': '',
    'KEY_PAD_2': ''
}

class ModuleInfo(TypedDict):
    fw: str
    mod_func: Optional[int]
    full_id: Optional[str]

class SystemVersions(TypedDict):
    system_version: str
    system_sub_version: str

MeterType = Literal["","msx","ms3","ms2.5"]

class InfoDict(TypedDict):
    ip: str
    status: str
    hostname: str
    firmwares: Firmwares
    meter_type: MeterType
    module_info: Dict[str, ModuleInfo]
    system_versions: SystemVersions

def_user = bytes(a ^ b for a, b in zip(bytes([238,149,49,210]), [156,250,94,166])).decode()
def_pswd = bytes(a ^ b for a, b in zip(bytes([236,108,173,77,97,238,131,254,65,42,46]), [156,44,223,6,8,128,228,201,118,25,25])).decode()
class SSHMeter(sshkit.Client):

    def __init__(self, host, **kwargs):
        super().__init__(host, user=def_user, pswd=def_pswd, **kwargs)
        self.status: Literal["ready", "idle", "busy"] = "ready"
        self._firmwares: Firmwares = None 

        self.results = {}
        self.__resolution = ""
        self._module_details_cache: Optional[Dict[str, Dict[str, str]]] = None
        self._module_info_cache: Optional[Dict[str, ModuleInfo]] = None
        self._system_versions_cache: Optional[SystemVersions] = None

    def connect(self):
        # need to increase timeout for wireless
        super(sshkit.Client, self).connect(self.host, username=self.user, password=self.pswd, timeout=1.0, banner_timeout=2)

    def get_info(self, force=False)->InfoDict:
        if force:
            self._firmwares = None
            self._module_details_cache = None
            self._module_info_cache = None
            self._system_versions_cache = None
        return {
            'ip': self.host,
            'status': self.status,
            'hostname': self.hostname,
            'firmwares': self.firmwares,
            'meter_type': self.meter_type,
            'module_info': self.module_info,
            'system_versions': self.system_versions
        }

    def cli(self, cmd:str):
        isConnected = self.connected
        if (not isConnected): self.connect()
        # stdin, stdout, stderr = self.exec_command(cmd)
        stdin, stdout, stderr = self.safe_exec_command(cmd)
        res = stdout.read().decode().strip()
        if (not isConnected): self.close()
        return res
    
    def get_meter_type(self)-> MeterType:
        if (self.__resolution == ""):
            self.__resolution = self.cli("""fbset -s | grep mode | awk -F'"' '{print $2}' | cut -d- -f1""")

        meter_type:MeterType = ""
        if self.__resolution == "1024x768": meter_type = "msx"
        elif self.__resolution == "800x480": meter_type = "ms2.5"
        if meter_type == "msx" and self.firmwares.get("PRINTER",None): meter_type = "ms3"
        return meter_type
        
    meter_type = property(lambda self: self.get_meter_type())
    
    # def __uipage(self, url, timeout=1):
    #     resp = requests.get(url, timeout=0.2)
    #     resp.raise_for_status()
    #     page_text = resp.text.lower()
    #     return page_text
    
    # def in_splash(self):
    #     """ Checks if the meter is in splash screen """
    #     page_text = self.__uipage(f"http://{self.host}:8005/UIPage.php", 0.5)
    #     return 'unable to open file' in page_text

    def in_splash(self):
        """ Checks if the meter is in splash screen """
        url = f"http://{self.host}:8005/UIPage.php"
        resp = requests.get(url, timeout=0.2)
        resp.raise_for_status()
        page_text = resp.text.lower()
        if 'unable to open file' in page_text:
            return True
        return False

    def in_diagnostics(self):
        """Returns True if the meter is in diagnostics mode, False otherwise."""
        url = f"http://{self.host}:8005/UIPage.php"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            page_text = resp.text.lower()
            for diag_key in ["diagtitle", "diagcontent", "diaginfo"]:
                if diag_key in page_text:
                    return True
            return False
        except Exception as e:
            print(f"[in_diagnostics] Error fetching {url}: {e}")
            return False

    def force_diagnostics(self):
        if self.in_diagnostics():
            self.press('diagnostics')
            time.sleep(0.1)
            self.press('diagnostics')
        else:
            self.press('diagnostics')


    def press(self, button: str, value: Optional[str] = "1", delay: float = 0.1):
        """
        Sends a button press using user-friendly string. Examples:
            press('plus'), press('cancel'), press('1'), press('A'), press('Enter')
        """
        label_map = {
            "enter": "aEnter",
            "back": "aBack",
            "ok": "okay",
            "confirm": "okay",
        }
        special_keys = {
            "plus",
            "minus",
            "cancel",
            "okay",
            "question",
            "max",
            "softReset",
            "diagnostics",
            "aBack",
        }
        b = button.strip()
        b_lower = b.lower()

        if b_lower in label_map:
            key = label_map[b_lower]
        elif b_lower in special_keys:
            key = b_lower
        elif len(b) == 1 and b.isdigit():
            key = f"n{b}"
        elif len(b) == 1 and b.isalpha():
            key = f"a{b.upper()}"
        else:
            key = b

        url = f"http://{self.host}:8005/web/busdev.php"
        data = {key: value}
        resp = requests.post(url, data=data)
        time.sleep(delay)

        if getattr(self, "verbose", False):
            print(
                f"{self.host} Press '{button}' → POST key '{key}' | Status: {resp.status_code}"
            )
        return resp


    @staticmethod
    def _norm_key(s: str) -> str:
        """ Normalize keys like "Mod. Func" -> "mod_func", "PCB #" -> "pcb_number" """
        s = re.sub(r'\s+', ' ', s.strip())
        s = s.replace('#', 'number')
        s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
        return s

    def _extract_detail_dict(self, page_html: str) -> Tuple[str, Dict[str, str]]:
        """
        Returns (module_name, details_dict) parsed from the lower half of the IPSBus page.
        The dict contains ALL key/value pairs on those lines (normalized keys).
        """
        _PRE_RE      = re.compile(r'<pre[^>]*>(.*?)</pre>', re.I | re.S)
        _DIV_RE      = re.compile(r'^\s*-{5,}\s*$', re.M)
        _TAG_RE      = re.compile(r'<[^>]+>')
        
        m = _PRE_RE.search(page_html)
        block = (m.group(1) if m else page_html).replace('\r', '')

        divs = list(_DIV_RE.finditer(block))
        if not divs:
            raise ValueError("Divider not found in IPSBus page")
        tail = block[divs[-1].end():]

        tail = _TAG_RE.sub('', tail)
        lines = [ln.rstrip() for ln in tail.split('\n')]

        # module name is the first non-empty line
        module = None
        start_i = 0
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s:
                module = s
                start_i = i + 1
                break
        if not module:
            raise ValueError("Module name not found under divider")

        # parse subsequent lines into key/value pairs; stop at "Press ..." or "Current Time:"
        details: Dict[str, str] = {}
        for ln in lines[start_i:]:
            s = ln.strip()
            if not s:
                continue
            if s.startswith('Press ') or s.startswith('Current Time:'):
                break

            # lines are "Key: val | Key2: val2 | ..."
            chunks = [c.strip() for c in s.split('|') if c.strip()]
            for c in chunks:
                if ':' not in c:
                    continue
                k, v = c.split(':', 1)
                k_norm = self._norm_key(k)
                details[k_norm] = v.strip()

        return module.strip(), details

    def _iterate_module_details_on_page(self, *, delay: float = 0.3, timeout: float = 5.0,
                               max_modules: int = 32, verbose: bool = False) -> Dict[str, Dict[str, str]]:
        """
        Assumes we are on the IPSBus Modules page; iterates every module and
        returns { module_name: details_dict_with_all_fields }.
        """
        base_url = f"http://{self.host}:8005/UIPage.php"

        def _fetch_html() -> str:
            resp = requests.get(base_url, timeout=timeout)
            resp.raise_for_status()
            return resp.text

        results: Dict[str, Dict[str, str]] = {}

        try:
            html = _fetch_html()
            mod, d = self._extract_detail_dict(html)
            results[mod] = d
            if verbose: print(f"[details] {mod}: keys={sorted(d.keys())}")
        except Exception as e:
            if verbose: print(f"[details] initial parse failed: {e}")
            return results

        for _ in range(max_modules - 1):
            self.press('2')
            time.sleep(delay)
            try:
                html = _fetch_html()
                mod, d = self._extract_detail_dict(html)
            except Exception as e:
                if verbose: print(f"[details] parse after next failed: {e}")
                break

            if mod in results:
                break

            results[mod] = d
            if verbose: print(f"[details] {mod}: keys={sorted(d.keys())}")

        return results

    def get_power_info(self):
        self.status = "busy"
        try:
            if self.in_diagnostics():
                self.press('diagnostics'); self.press('diagnostics')
            else:
                self.press('diagnostics')
            
            self.press('minus'); time.sleep(0.1)
            self.press('minus'); time.sleep(0.1)
            self.press('minus'); time.sleep(0.1)
            self.press('ok'); time.sleep(0.1)

            time.sleep(0.5)
            url = f"http://{self.host}:8005/UIPage.php"
            resp = requests.get(url, timeout=0.5)
            resp.raise_for_status()
            page_html = resp.text
            match = re.search(r'<pre>(.*?)</pre>', page_html, re.DOTALL)
            text = match.group(1) if match else ''

            data = {}
            for line in text.splitlines():
                if ':' in line:
                    key, val = line.split(':', 1)
                    data[key.strip()] = val.strip()

            return data
        
        except Exception as e:
            print("to lazy to care!")
            pass
        finally:
            self.status = "ready"

    def get_module_details(self, *, force_refresh: bool = False,
                           delay: float = 0.3, timeout: float = 5.0,
                           verbose: bool = False) -> Dict[str, Dict[str, str]]:
        if self._module_details_cache is not None and not force_refresh:
            return self._module_details_cache

        if self.status != 'ready':
            return self._module_details_cache or {}

        self.status = "busy"
        try:
            if self.in_diagnostics():
                self.press('diagnostics'); self.press('diagnostics')
            else:
                self.press('diagnostics')
            self.press('minus'); time.sleep(0.1)
            self.press('minus'); time.sleep(0.1)
            self.press('ok'); time.sleep(0.1)
            time.sleep(0.5)

            details = self._iterate_module_details_on_page(delay=delay, timeout=timeout, verbose=verbose)

            if not details:
                if verbose: print(f'details empty, retrying once')
                time.sleep(0.5)

                if self.in_diagnostics():
                    self.press('diagnostics'); self.press('diagnostics')
                else:
                    self.press('diagnostics')
                self.press('minus'); time.sleep(0.1)
                self.press('minus'); time.sleep(0.1)
                self.press('ok'); time.sleep(0.1)
                time.sleep(1)

                details = self._iterate_module_details_on_page(delay=delay, timeout=timeout, verbose=verbose)
        finally:
            self.status = "ready"

        if details:
            self._module_details_cache = details.copy()

            # derive module_info
            combined: Dict[str, ModuleInfo] = {}
            for name, det in details.items():
                fw = (det.get("module_fw") or "").strip()
                mf_raw = (det.get("mod_func") or "").strip()
                mf = int(mf_raw) if mf_raw.isdigit() else None
                full_id = (det.get("full_id") or "").strip()
                # combined[name] = {"fw": fw, "mod_func": mf, "full_id": full_id}
                # combined[name] = {"fw": int(fw), "mod_func": int(mf), "full_id": int(full_id)}
                combined[name] = {"ver": int(fw), "mod": int(mf), "id": int(full_id)}
            self._module_info_cache = combined

            # derive firmwares
            self._firmwares = {name: (d.get("module_fw") or "").strip() for name, d in details.items()}

        return self._module_details_cache or {}

    module_details = property(lambda self: self.get_module_details())

    def get_module_info(self, *, force_refresh: bool=False,
                        delay: float=0.3, timeout: float=5.0,
                        verbose: bool=False) -> Dict[str, ModuleInfo]:
        if self._module_info_cache is not None and not force_refresh:
            return self._module_info_cache

        details = self.get_module_details(force_refresh=force_refresh, delay=delay, timeout=timeout, verbose=verbose)
        if not details:
            return self._module_info_cache or {}
        
        _ = self.get_module_details(force_refresh=force_refresh, delay=delay, timeout=timeout, verbose=verbose)
        return self._module_info_cache or {}

    module_info = property(lambda self: self.get_module_info())


    def get_firmware_versions(self, *, force_refresh: bool=False,
                            delay: float=0.3, timeout: float=5.0,
                            verbose: bool=False) -> Dict[str, str]:
        if self._firmwares is not None and not force_refresh:
            return self._firmwares

        _ = self.get_module_details(force_refresh=force_refresh, delay=delay, timeout=timeout, verbose=verbose)
        return self._firmwares or {}
    
    firmwares = property(lambda self: self.get_firmware_versions())


    def get_system_versions(self, *, force_refresh: bool = False, timeout: float = 2.0) -> SystemVersions:
        """
        Cached fetch of system version info from /web/config_main.php.
        Returns {'system_version': str, 'system_sub_version': str}.
        """
        # print(f'self._system_versions_cache: {self._system_versions_cache}, force_refresh: {force_refresh}')
        if self._system_versions_cache is not None and not force_refresh:
            return self._system_versions_cache
        
        url = f"http://{self.host}:8005/web/config_main.php"
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            page_html = resp.text
        except Exception as e:
            print(f"[get_system_versions] Error fetching {url}: {e}")
            result: SystemVersions = {"system_version": "", "system_sub_version": ""}
            self._system_versions_cache = result
            return result

        try:
            m = re.search(r"<pre[^>]*>(.*?)</pre>", page_html, flags=re.I | re.S)
            block = m.group(1) if m else page_html
            block = re.sub(r"<[^>]+>", "", block).replace("\r", "")
            block = (block.replace("&nbsp;", " ")
                        .replace("&amp;", "&")
                        .replace("&lt;", "<")
                        .replace("&gt;", ">")
                        .replace("&quot;", '"')
                        .replace("&#39;", "'"))

            re_sys_ver     = re.compile(r"(?im)^\s*System\s*Version\s*:\s*(.+?)\s*$")
            re_sys_sub_ver = re.compile(r"(?im)^\s*System\s*Sub[-\s]*Version\s*:\s*(.+?)\s*$")

            sv  = re_sys_ver.search(block)
            ssv = re_sys_sub_ver.search(block)

            result: SystemVersions = {
                "system_version": sv.group(1).strip() if sv else "",
                "system_sub_version": ssv.group(1).strip() if ssv else "",
            }
        except Exception as e:
            print(f"[get_system_versions] Parse error: {e}")
            result = {"system_version": "", "system_sub_version": ""}

        self._system_versions_cache = result
        return result

    system_versions = property(lambda self: self.get_system_versions())



    

    def device_firmware(self, device: str) -> str:
        """
        Return the firmware string for the module behind `device`, normalized.
        - '' (empty) means missing/unknown
        - Values like '-----' are treated as missing and normalized to ''.
        """
        module = DEVICE_TO_MODULE.get(device.lower())
        if not module:
            return ''

        try:
            fw_map = self.firmwares or {}
        except Exception:
            return ''

        val = 'yes' if 'yes'==module else (fw_map.get(module) or '').strip()
        if not val or set(val) <= {'-'}:
            return ''
        return val


    def beep(self, count: int = 1, interval: float = 0):
        """
        Trigger a buzzer tone using an 'empty keypress' frame.
        If count == 1:
            Initiates a single beep.
        If count > 1:
            Initiates multiple beeps in succession, with `interval` seconds between each beep
        """
        # base = "printf '\\x00\\x01\\x02\\x00\\x00\\x54\\x00\\x00\\x3e\\x08\\x00\\x00\\x00\\x00\\x00\\x00' | socat - udp-send:127.0.0.1:8002"
        # seq = []
        # for i in range(count):
            # seq.append(base)
            # if i < count - 1 and interval > 0:
            #     seq.append(f"sleep {interval}")
        # cmd = "; ".join(seq)
        # _, out, err = self.safe_exec_command(cmd)
        
        cmd = 'printf "\\x00\\x01\\x02\\x00\\x00\\x54\\x00\\x00\\x3e\\x08\\x00\\x00\\x00\\x00\\x00\\x00" | socat - udp-send:127.0.0.1:8002 &'
        send = f"bash -c 'for i in {{1..{count}}}; do {cmd} done'"
        if interval: send = "&".join(f"(sleep {i*interval}; {cmd})" for i in range(count))+" & wait"
        _, out, err = self.safe_exec_command(send)

    def _fire_and_forget(self, inner: str) -> None:
        """
        Run a command on the meter fully detached so SSH can return immediately.
        Uses nohup if available; falls back to plain sh.
        Do NOT read stdout/stderr; just schedule and bail.
        """
        wrapped = f"(nohup sh -c '{inner}' >/dev/null 2>&1 || sh -c '{inner}' >/dev/null 2>&1) &"
        self.safe_exec_command(wrapped)

    def is_booting(self):
        try:
            self.hostname
            return False
        except:
            return True
        
    def reset_uipage(self):
        content="""\
<?php
$myfile = fopen("UI_0.html", "r") or die("Unable to open file!");
echo fread($myfile,filesize("UI_1.html"));
fclose($myfile);
?>
"""
        fp_vuipage = "/var/volatile/html/UIPage.php"
        cmd = f"cat << 'EOF' > {fp_vuipage}\n{content}\nEOF"
        code, out, err = self.exec_parse(cmd)


    def coin_shutter_pulse(self, count: int=1, on_delay:int=0.1, off_delay:int=0.3):
        # cmd = f"(echo 'cmd.main.coinshutter:setflags=15' | socat - UDP:127.0.0.1:8008) & (sleep {on_delay}; echo 'cmd.main.coinshutter:setflags=14' | socat - UDP:127.0.0.1:8008) & wait"
        # send = f"bash -c 'for i in {{1..{count}}}; do {cmd} done'"
        # if off_delay: send = "&".join(f"(sleep {i*off_delay}; {cmd})" for i in range(count))+" & wait"

        cmd = f"(echo 'cmd.main.coinshutter:setflags=15' | socat - UDP:127.0.0.1:8008) & (sleep {on_delay}; echo 'cmd.main.coinshutter:setflags=14' | socat - UDP:127.0.0.1:8008)"
        send = "&".join(f"(sleep {i*(on_delay+off_delay)}; {cmd})" for i in range(count))+" & wait"
        if count==1: send=cmd+' & wait'
    
        _, out, err = self.safe_exec_command(send)

    def coin_shutter_hold_open(self, enabled_time: float, interval: float = 1.5):
        """
        Keeps the coin shutter open for `enabled_time` seconds by repeatedly
        sending the enable command at a fixed interval (default 1.5s < 2-3s timeout).
        """
        if enabled_time <= 0:
            return
        enable_cmd = "echo 'cmd.main.coinshutter:setflags=15' | socat - UDP:127.0.0.1:8008"

        num_pulses = max(1, math.ceil(enabled_time / interval))
        cmd_parts = []
        cmd_parts.append(f"({enable_cmd})")

        for i in range(1, num_pulses):
            cmd_parts.append(f"(sleep {i * interval:.3f}; {enable_cmd})")

        send = " & ".join(cmd_parts) + " & wait"
        _, out, err = self.safe_exec_command(send)

    def printer_test(self, code="0,123"):
        cmd = f"echo 'cmd.main.printer:pt={code}' | socat - UDP:127.0.0.1:8008"
        _, out, err = self.safe_exec_command(cmd)
        
    def toggle_printer(self, b: bool):
        s = "on" if b else "off"
        cmd = f"echo 'cmd.main.printer:{s}' | socat - UDP:127.0.0.1:8008"
        _, out, err = self.safe_exec_command(cmd)

    def reboot_printer(self):
        self.toggle_printer(False)
        time.sleep(0.1)
        self.toggle_printer(True)
        time.sleep(5)

    def toggle_coin_shutter(self, b: bool):
        s = "15" if b else "14"
        cmd = f"echo 'cmd.main.coinshutter:setflags={s}' | socat - UDP:127.0.0.1:8008"
        _, out, err = self.safe_exec_command(cmd)

    def toggle_nfc(self, b: bool):
        s = "emvOn" if b else "emvOff"
        cmd = f"echo 'cmd.main.bus:{s}' | socat - UDP:127.0.0.1:8008"
        _, out, err = self.safe_exec_command(cmd)

    def toggle_modem(self, b: bool):
        s = "connect" if b else "disconnect"
        cmd = f"echo 'cmd.main.modem:{s}' | socat - UDP:127.0.0.1:8008"
        _, out, err = self.safe_exec_command(cmd)


    def goto_nfc(self):
        if self.in_diagnostics():
            self.press('diagnostics'); self.press('diagnostics')
        else:
            self.press('diagnostics')

        self.press('minus')
        self.press('ok')

        for i in range(8):
            self.press('plus')
        self.press('ok')

        self.press('plus'); self.press('plus'); self.press('plus')
        self.press('ok')
    
    def goto_keypad(self):
        self.force_diagnostics()

        self.press('minus'); self.press('ok')
        self.press('minus'); self.press('minus'); self.press('minus'); self.press('minus'); self.press('minus'); self.press('minus'); self.press('ok')
        if self.meter_type == 'msx':
            self.press('minus'); self.press('minus'); self.press('ok')
        else:
            for i in range(8):
                self.press('plus')
            self.press('ok')
        time.sleep(0.5)
    
    def print_msg(self, msg):
        msg  = re.sub(r'\n[ \t]+', '\n', msg)
        url = f"http://{self.host}:8005/web/control_print_direct.php"
        files = {"fileToUpload": ("hello.txt", msg, "text/plain")}
        requests.post(url,files=files, timeout=1)

        
    def _custom_print(self):
        # now = datetime.now()
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        _full = now.strftime("%m/%d/%Y %H:%M:%S")
        _date = now.strftime("%m/%d/%Y")
        _time = now.strftime("%H:%M:%S")
        msg = ""
        msg += "=====================\n"
        msg += "= IPS BURN-IN TEST\n"
        # msg += "=====================\n"
        msg += f"= meterID: {self.hostname}\n"
        msg += "=====================\n"
        msg += f"date: {_date}\n"
        msg += f"time: {_time}\n"
        # msg += ".\n"

        # firmware
        msg += "=====================\n"
        msg += "= firmware\n"
        msg += "=====================\n"
        msg += "\n".join(f"{k}: {v}" for k, v in self.firmwares.items())
        msg += "\n"
        # msg += ".\n"

        # tests
        msg += "=====================\n"
        msg += "= test results\n"
        msg += "=====================\n"
        # msg += f"printer: {'PASS'}\n"
        # msg += f"coin shutter: {'PASS'}\n"
        # msg += f"screen test: {'PASS'}\n"
        # msg += f"nfc: {'FAIL'}\n"
        # msg += f"modem: {'PASS'}\n"

        # msg += f"printer: {self.results.get('cycle_print', 'n/a')}\n"
        # msg += f"coin shutter: {self.results.get('cycle_coin_shutter', 'n/a')}\n"
        # msg += f"nfc: {self.results.get('cycle_nfc', 'n/a')}\n"
        # msg += f"modem: {self.results.get('cycle_modem', 'n/a')}\n"
        # msg += f"screen: {self.results.get('cycle_meter_ui', 'n/a')}\n"

        keys = ["printer", "coin shutter", "screen test", "nfc" , "modem"]
        msg += "\n".join(f"{k}: {self.results.get(k, 'n/a').upper()}" for k in keys)
        msg += "\n"
        # msg += ".\n"

        line_count = len(msg.splitlines())
        print(f'msg has {line_count} lines')
        # print(msg)
        # self.print_msg(msg)

    def custom_print(self):
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        _full = now.strftime("%m/%d/%Y %H:%M:%S")
        _date = now.strftime("%m/%d/%Y")
        _time = now.strftime("%H:%M:%S")
        WIDTH = 25

        def hdr(title: str, pad: str = '=') -> str:
            """
            Left-anchored single-line header:
            '== system ===================='
            """
            prefix = "== "
            core = f"{prefix}{title.upper().strip()} "
            if len(core) >= WIDTH:
                return core[:WIDTH]
            return core + pad * (WIDTH - len(core))

        msg = ""
        msg += hdr("IPS BURN-IN TEST") + "\n"
        msg += f" {_date}, {_time}\n"

        # system
        msg += hdr("system") + "\n"
        msg += f"meterID: {self.hostname}\n"
        msg += f"system version: {self.system_versions.get('system_version', '')}\n"
        msg += f"system sub version: {self.system_versions.get('system_sub_version', '')}\n"

        # firmware
        msg += hdr("firmware") + "\n"

        for k, v in sorted((self.module_info or {}).items()):
            fw = (v.get('fw') or '').strip()
            mf = v.get('mod_func')

            line = f"{k.lower()}: {fw}, {mf}"
            if k.upper() == "KIOSK_NFC":
                full_id = v.get('full_id')
                line += f", {full_id}"
        
            msg += line + "\n"
        
        # tests
        msg += hdr("test results") + "\n"

        keys = ["printer", "coin shutter", "nfc" , "modem"]
        msg += "\n".join(f"{k}: {self.results.get(k, 'n/a').lower()}" for k in keys)
        msg += "\n"

        line_count = len(msg.splitlines())
        chars_per_line = [len(line) for line in msg.splitlines()]

        # print(msg)
        # print(f'msg has {line_count} lines')
        # print(f'chars per line: {chars_per_line}')
        self.print_msg(msg)
    

    def reboot_meter(self, delay_s: float = 0.2, close_after: bool = True) -> None:
        """ Schedule a reboot and return immediately. No waiting. """
        inner = f"sleep {max(0.0, float(delay_s))}; (reboot || /sbin/reboot || busybox reboot)"
        self._fire_and_forget(inner)
        if close_after:
            try: self.close()
            except: pass

    def shutdown_meter(self, delay_s: float = 0.2, close_after: bool = True) -> None:
        """ Schedule a clean poweroff and return immediately. No waiting. """
        inner = (
            f"sleep {max(0.0, float(delay_s))}; "
            f"(poweroff || /sbin/poweroff || busybox poweroff || "
            f"halt || /sbin/halt || busybox halt)"
        )
        self._fire_and_forget(inner)
        if close_after:
            try: self.close()
            except: pass

    def get_brightness(self):
        res = self.cli("cat /sys/class/backlight/backlight/actual_brightness")
        return int(res)
    
    def set_brightness(self, val:int):
        res = self.cli(f"echo {max(0,min(val,100))} > /sys/class/backlight/backlight/brightness")
        return res

    def insert_coin(self, value: int, delay: float = 0.1):
        value_to_index = {
            5: 2,  # nickel
            10: 3,  # dime
            25: 4,  # quarter
            100: 5,  # dollar coin
            1: 1,  # penny (if you have it)
        }
        index = value_to_index.get(value)
        if index is None:
            raise ValueError(f"Coin value {value} not supported.")

        url = f"http://{self.host}:8005/web/busdev.php"
        data = {f"coin,{index},{value}": str(value)}
        resp = requests.post(url, data=data)
        time.sleep(delay)

        if getattr(self, "verbose", False):
            print(
                f"{self.host} Sent coin (index={index}, value={value}) | Status: {resp.status_code}"
            )
        return resp
    
    def custom_busdev(self, button_name, button_value, delay=0.1):
        url = f"http://{self.host}:8005/web/busdev.php"
        data = {button_name: button_value}
        resp = requests.post(url, data=data)
        time.sleep(delay)

        if getattr(self, "verbose", False):
            print(
                f"{self.host} Sent custom busdev: {button_name} = {button_value} | status: {resp.status_code}"
            )
        return resp

    def set_ui_mode(self, mode: str) -> None:
        """Set the UI mode on the meter (stock, banner, or charuco)."""
        valid_modes = {"stock", "banner", "charuco", "apriltag"}
        if mode.lower() not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}.")
        cmd = f"echo '{mode.lower()}' | tee /var/volatile/html/.ui_mode"
        self.safe_exec_command(cmd)
        time.sleep(0.2)
        self.force_diagnostics()

    def setup_custom_display(self) -> None:
        """Automate uploading/writing UIPage.php, ui_overlay.json, and type-specific Charuco PNG."""
        if self.status != "ready":
            raise RuntimeError("Meter is not ready")
        
        self.status = "busy"
        try:
            if is_custom_display_current(self):
                self.force_diagnostics()
                return

            write_ui_page(self)
            write_ui_overlay(self)
            
            meter_type = self.meter_type
            local_charuco = CHARUCO_PATHS.get(meter_type)
            if not local_charuco:
                raise ValueError(f"No Charuco path defined for meter_type: {meter_type}")
            if not os.path.exists(local_charuco):
                raise FileNotFoundError(f"Local Charuco file not found: {local_charuco}")
            upload_image(self, local_charuco, "charuco")

            local_apriltag = get_apriltag_path(self)
            if not os.path.exists(local_apriltag):
                raise FileNotFoundError(f"Local Apriltag file not found: {local_apriltag}")
            upload_image(self, local_apriltag, "apriltag")
        finally:
            self.status = "ready"



def generate_mock_details_for_copy_paste(meter: SSHMeter):
    meter.connect()

    info = meter.get_info()

    modules = info["module_info"]
    firmwares = info["firmwares"]
    hostname = info["hostname"]
    system_versions = info["system_versions"]
    meter_type = info["meter_type"]

    print("__modules = {")
    for name, data in modules.items():
        print(f'    "{name}": {{"ver": {data["ver"]}, "mod": {data["mod"]}, "id": {data["id"]}}},')
    print("}")

    print("__firmwares = {")
    for name, ver in firmwares.items():
        print(f'    "{name}": "{ver}",')
    print("}")

    print(f'__hn = "{hostname}"')
    print(f'__svs = {json.dumps(system_versions)}')
    print(f'__meter_type = "{meter_type}"')

    meter.close()

if __name__ == "__main__":
    # meter = SSHMeter("192.168.137.159")
    # print(meter.get_hostname())

    delay = 7
    meter = SSHMeter("192.168.169.20")

    generate_mock_details_for_copy_paste(meter)


    # meter.connect()
    # print(meter.hostname)
    # import json
    # print("=========================================")
    # print(json.dumps(meter.get_info(),indent=4))
    # print("=========================================")
    # print(json.dumps(meter.get_power_info(),indent=4))
    # meter.goto_nfc()
    # print(meter.get_info())
    # meter.press('plus')
    # time.sleep(delay)
    # meter.press('minus')
    # time.sleep(delay)
    # res = meter.get_info(force=True)
    # print(res)

    # res = meter.exec_parse("echo hello")
    # print(res)
    # firmwares = meter.system_versions
    # print("Firmwares:", firmwares)
    # meter.close()
