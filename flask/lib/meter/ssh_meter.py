# class to hold ssh-meter. for states or what not
from typing import  Optional, Literal, TypedDict, Dict, Tuple
# from lib.ssh.client import SSHClient
from paramiko import SSHException
import sshkit
import requests
import re
import time
from lib.utils import secrets

import json


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
        self._module_details_cache: Optional[Dict[str, Dict[str, str]]] = None
        self._module_info_cache: Optional[Dict[str, ModuleInfo]] = None
        self._system_versions_cache: Optional[SystemVersions] = None

    def connect(self):
        with self._lock:
            try:
                if self.id_rsa: super(sshkit.Client, self).connect(self.host, username=self.user, key_filename=self.id_rsa, timeout=0.5, )
                else: super(sshkit.Client, self).connect(self.host, username=self.user, password=self.pswd, timeout=0.5)
                self.connected = True
            except OSError as e:
                if e.errno == 9 or "Bad file descriptor" in str(e): 
                    print(f"[{self.host}] BAD FILE DESCRIPTOR?")
                    raise Exception(f"[{self.host}] BAD FILE DESCRIPTOR?")
            except SSHException as e:
                print(f"[{self.host}] ssh not ready?")
                raise Exception(f"[{self.host}] ssh not ready?")
            except:
                print("yoyoyo")
                raise Exception(f"connect to {self.host} failed due to timeout")

    def get_info(self):
        return {
            'ip': self.host,
            'status': self.status,
            'hostname': self.hostname,
            'firmwares': self.firmwares
        }
    
    def __uipage(self, url, timeout=1):
        resp = requests.get(url, timeout=0.2)
        resp.raise_for_status()
        page_text = resp.text.lower()
        return page_text
    
    def in_splash(self):
        """ Checks if the meter is in splash screen """
        page_text = self.__uipage(f"http://{self.host}:8005/UIPage.php", 0.5)
        return 'unable to open file' in page_text

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
                combined[name] = {"fw": int(fw), "mod_func": int(mf), "full_id": int(full_id)}
            self._module_info_cache = combined

            # derive firmwares
            self._firmwares = {name: (d.get("module_fw") or "").strip() for name, d in details.items()}

        return self._module_details_cache or {}

    module_details = property(get_module_details)

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

    module_info = property(get_module_info)

    def get_firmware_versions(self, *, force_refresh: bool=False,
                            delay: float=0.3, timeout: float=5.0,
                            verbose: bool=False) -> Dict[str, str]:
        if self._firmwares is not None and not force_refresh:
            return self._firmwares

        _ = self.get_module_details(force_refresh=force_refresh, delay=delay, timeout=timeout, verbose=verbose)
        return self._firmwares or {}
    
    firmwares = property(get_firmware_versions)

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

    system_versions = property(get_system_versions)



    

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


if __name__ == "__main__":
    # meter = SSHMeter("192.168.137.159")
    # print(meter.get_hostname())

    client = SSHMeter("192.168.137.158")
    client.connect()
    res = client.exec_parse("echo hello")
    print(res)
    client.close()
