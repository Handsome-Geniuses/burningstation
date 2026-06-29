# class to hold ssh-meter. for states or what not
from typing import Optional, Literal, TypedDict, Dict, Tuple, List, Sequence
# from lib.ssh.client import SSHClient
from paramiko import SSHException
import sshkit
import requests
import re
import time
import os
import math
import json
import shlex
import threading
from html import unescape
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.utils import secrets
from lib.automation.shared_state import SharedState
from lib.meter.coin_utils import clear_coin_tallies as clear_coin_tallies_impl
from lib.meter.display_utils import (
    CHARUCO_PATHS, write_ui_page, write_ui_overlay,
    upload_image, is_custom_display_current,
    get_apriltag_path, write_results_json
)


DEVICE_TO_MODULE = {
    'printer': ('PRINTER',),
    'coin shutter': ('COIN_SHUTTER',),
    'nfc': ('KIOSK_NFC', 'KIOSK_NEO'),
    'modem': ('MK7_XE910',),
    'call in': ('MK7_XE910',),
    'screen test': ('yes',)
}

SPECIAL_CARD_TRACK2 = {
    "COINCOLLECTION": "1011977700005667=2612201201018400000",
    "METERDIAGNOSTICS": "1111977700003893=2612201201018400000",
}

LEGACY_CARD_READ_TEMPLATE_HEX = (
    "00018800004ab79ec30b42cba2dd0100"
    "01000132313039002400000000000000"
    "00000000000000000000000000000000"
    "00000000000000000000000000000000"
    "00000000000000000000000000000000"
    "00000000000000000000000000000000"
    "00000000000000000000000000003431"
    "30303339303435373834323937353d32"
    "31303932303132303130313834303030"
    "303000000000"
)

CARD_READ_HEADER_LEN = 14
CARD_READ_SRC_MODULE_OFFSET = 5
CARD_READ_READ_TYPE_OFFSET = 2
CARD_READ_ENCRYPTION_TYPE_OFFSET = 3
CARD_READ_CARD_TYPE_OFFSET = 4
CARD_READ_EXP_DATE_OFFSET = 5
CARD_READ_TRACK2_OFFSET = 16 + 80
CARD_READ_TRACK2_MAX_LEN = 40
CARD_READ_NFC_MODULE = 75
CARD_READ_TYPE_MSD_CONTACTLESS = 3

REMOTE_HTML_ROOT = "/var/volatile/html"
REMOTE_UI_HTML_PATH = f"{REMOTE_HTML_ROOT}/UI_0.html"
REMOTE_WEB_ROOT = f"{REMOTE_HTML_ROOT}/web"
REMOTE_BUSDEV_PATH = f"{REMOTE_WEB_ROOT}/busdev.php"
REMOTE_PRINT_DIR = "/var/volatile"

BUSDEV_KEY_HEX = {
    "nAsterisk": "2a00",
    "nPound": "2300",
    "aAsterisk": "2a00",
    "aPound": "2300",
    "aBack": "7900",
    "aEnter": "7a00",
    "globe": "6c00",
    "plus": "2b00",
    "minus": "2d00",
    "cancel": "7800",
    "okay": "6f00",
    "question": "6800",
    "max": "6d00",
    "softReset": "7f00",
    "diagnostics": "7200",
}
BUSDEV_KEY_PACKET_PREFIX = "00010200000000003e0800000000"
DIAG_SELECTED_PREFIX_RE = re.compile(r"^\s*(?:->|=>)\s*")

COIN_VALUE_TO_INDEX_BY_REGION: Dict[str, Dict[int, int]] = {
    "us": {
        5: 2,   # nickel
        10: 3,  # dime
        25: 4,  # quarter
        100: 5, # dollar coin
    },
    "uk": {
        5: 2,   # 5p
        10: 3,  # 10p
        20: 4,  # 20p
        50: 5,  # 50p
    },
}

class Firmwares(TypedDict):
    MK7_XE910: str
    KIOSK_NFC: str
    KIOSK_NEO: str
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
    'KIOSK_NEO': '',
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
MeterRegion = Literal["","us","uk"]

class InfoDict(TypedDict):
    ip: str
    status: str
    hostname: str
    firmwares: Firmwares
    meter_type: MeterType
    meter_region: MeterRegion
    module_info: Dict[str, ModuleInfo]
    system_versions: SystemVersions


class DiagMenuItem(TypedDict):
    text: str
    selected: bool


class DiagPageState(TypedDict):
    title: str
    title_segments: List[str]
    menu_items: List[DiagMenuItem]
    selected_index: Optional[int]
    is_menu: bool
    page_html: str

def_user = bytes(a ^ b for a, b in zip(bytes([238,149,49,210]), [156,250,94,166])).decode()
def_pswd = bytes(a ^ b for a, b in zip(bytes([236,108,173,77,97,238,131,254,65,42,46]), [156,44,223,6,8,128,228,201,118,25,25])).decode()
class SSHMeter(sshkit.Client):
    DEFAULT_SSH_IDLE_TIMEOUT = 180.0

    def __init__(self, host, **kwargs):
        super().__init__(host, user=def_user, pswd=def_pswd, **kwargs)
        self._lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._ssh_state_lock = threading.RLock()
        self._connected_hint = False
        self._ssh_active_ops = 0
        self.default_ssh_idle_timeout = float(kwargs.get("ssh_idle_timeout", self.DEFAULT_SSH_IDLE_TIMEOUT))
        self.ssh_idle_timeout = self.default_ssh_idle_timeout
        self._ssh_last_used_at = time.monotonic()
        self.status: Literal["ready", "idle", "busy"] = "ready"
        self._firmwares: Firmwares = None 

        self.results = {}
        self.__resolution = ""
        self._module_details_cache: Optional[Dict[str, Dict[str, str]]] = None
        self._module_info_cache: Optional[Dict[str, ModuleInfo]] = None
        self._system_versions_cache: Optional[SystemVersions] = None
        self._meter_region_cache: Optional[MeterRegion] = None
        self._http_available: Optional[bool] = None
        self._blink_until_stop: Optional[threading.Event] = None
        self._blink_until_thread: Optional[threading.Thread] = None
        self._blink_until_status: Optional[Literal["ready", "idle", "busy"]] = None

    def _transport_is_active(self) -> bool:
        """Return True only when Paramiko has a live active transport."""
        try:
            transport = self.get_transport()
            return bool(transport and transport.is_active())
        except Exception:
            return False

    @property
    def connected(self) -> bool:
        """Report current SSH health from Paramiko instead of a cached flag."""
        active = self._transport_is_active()
        self._connected_hint = active
        return active

    @connected.setter
    def connected(self, value: bool) -> None:
        self._connected_hint = bool(value)

    def _touch_ssh_use(self) -> None:
        """Record recent SSH activity for idle cleanup."""
        with self._ssh_state_lock:
            self._ssh_last_used_at = time.monotonic()

    def _begin_ssh_operation(self) -> None:
        """Mark an SSH command as active and ensure the transport is ready."""
        with self._ssh_state_lock:
            self._ssh_active_ops += 1
        try:
            self.connect()
        except Exception:
            self._end_ssh_operation(touch=False)
            raise

    def _end_ssh_operation(self, *, touch: bool = True) -> None:
        """Mark an SSH command as finished and optionally refresh idle time."""
        with self._ssh_state_lock:
            self._ssh_active_ops = max(0, self._ssh_active_ops - 1)
            if touch:
                self._ssh_last_used_at = time.monotonic()

    def connect(self):
        """Open or reuse a Paramiko SSH connection for this meter."""
        # need to increase timeout for wireless
        with self._lock:
            if self._transport_is_active():
                self.connected = True
                self._touch_ssh_use()
                return
            super(sshkit.Client, self).connect(
                self.host,
                username=self.user,
                password=self.pswd,
                timeout=1.0,
                banner_timeout=2,
                auth_timeout=2,
            )
            transport = self.get_transport()
            if transport:
                transport.set_keepalive(30)
            self.connected = True
            self._touch_ssh_use()

    def close(self):
        """Close the local Paramiko client and mark the cached hint disconnected."""
        with self._lock:
            try:
                super(sshkit.Client, self).close()
            except:
                pass
            self.connected = False

    def close_if_idle(self) -> bool:
        """Close the SSH transport if it is inactive and past the idle timeout."""
        with self._ssh_state_lock:
            if self._ssh_active_ops > 0:
                return False
            if not self.connected:
                should_close = True
            else:
                timeout = float(self.ssh_idle_timeout)
                if timeout <= 0:
                    return False
                should_close = time.monotonic() - self._ssh_last_used_at >= timeout

            if not should_close:
                return False

        with self._command_lock:
            with self._ssh_state_lock:
                if self._ssh_active_ops > 0:
                    return False
                if self.connected:
                    timeout = float(self.ssh_idle_timeout)
                    if timeout <= 0:
                        return False
                    if time.monotonic() - self._ssh_last_used_at < timeout:
                        return False
            self.close()
            return True

    def _exec_command_with_retry(self, command: str, *args, **kwargs):
        """Open an SSH command channel, reconnecting once if the transport is stale."""
        last_exc = None
        for attempt in range(2):
            try:
                self.connect()
                return super(sshkit.Client, self).exec_command(command, *args, **kwargs)
            except Exception as exc:
                last_exc = exc
                try:
                    self.close()
                except:
                    pass
                if attempt == 1:
                    raise last_exc
        raise last_exc

    def exec_command(self, command, *args, **kwargs):
        """Run a raw SSH command while protecting connection state."""
        with self._command_lock:
            self._begin_ssh_operation()
            try:
                return self._exec_command_with_retry(command, *args, **kwargs)
            finally:
                self._end_ssh_operation()

    def safe_exec_command(self, command: str):
        """Run a command and return raw Paramiko streams for legacy callers."""
        # Raw stream callers must consume/close returned stdout/stderr promptly.
        # Prefer cli() or exec_parse() when the caller needs command output.
        was_connected = self.connected
        with self._command_lock:
            self._begin_ssh_operation()
            try:
                res = self._exec_command_with_retry(command)
                if not was_connected:
                    res[1].channel.recv_exit_status()
                return res
            finally:
                self._end_ssh_operation()

    def exec_parse(self, command: str) -> tuple[int, str, str]:
        """Run a command and return exit code, stdout, and stderr as strings."""
        with self._command_lock:
            self._begin_ssh_operation()
            try:
                _, stdout, stderr = self._exec_command_with_retry(command)
                out = stdout.read().decode(errors="replace").strip()
                err = stderr.read().decode(errors="replace").strip()
                code = stdout.channel.recv_exit_status()
                return code, out, err
            finally:
                self._end_ssh_operation()

    def get_info(self, force=False)->InfoDict:
        if force:
            self._firmwares = None
            self._module_details_cache = None
            self._module_info_cache = None
            self._system_versions_cache = None
            self._meter_region_cache = None
        return {
            'ip': self.host,
            'status': self.status,
            'hostname': self.hostname,
            'firmwares': self.firmwares,
            'meter_type': self.meter_type,
            'meter_region': self.meter_region,
            'module_info': self.module_info,
            'system_versions': self.system_versions
        }

    def _cli_full(self, cmd: str) -> Tuple[str, str]:
        with self._command_lock:
            self._begin_ssh_operation()
            try:
                stdin, stdout, stderr = self._exec_command_with_retry(cmd)
                out = stdout.read().decode(errors="replace").strip()
                err = stderr.read().decode(errors="replace").strip()
                stdout.channel.recv_exit_status()
                return out, err
            finally:
                self._end_ssh_operation()

    def cli(self, cmd:str):
        out, _ = self._cli_full(cmd)
        return out

    @staticmethod
    def _synthetic_response(url: str, status_code: int = 200, text: str = "") -> requests.Response:
        response = requests.Response()
        response.status_code = status_code
        response.url = url
        response.encoding = "utf-8"
        response._content = text.encode("utf-8")
        return response

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        raise_for_status: bool = False,
        **kwargs,
    ) -> Optional[requests.Response]:
        if self._http_available is False:
            return None

        try:
            response = requests.request(method, url, **kwargs)
            if raise_for_status:
                response.raise_for_status()
            self._http_available = True
            return response
        except Exception:
            self._http_available = False
            return None

    def _run_remote_php_script(
        self,
        script_path: str,
        *,
        post_data: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
    ) -> str:
        script_dir = os.path.dirname(script_path)
        script_name = os.path.basename(script_path)

        php_parts: List[str] = []
        php_parts.append(
            '$_SERVER["REQUEST_METHOD"] = '
            + ('"POST";' if post_data else '"GET";')
        )
        if post_data:
            for key, value in post_data.items():
                php_parts.append(
                    f'$_POST[{json.dumps(str(key))}] = {json.dumps("" if value is None else str(value))};'
                )

        php_parts.append("ob_start();")
        php_parts.append(f"include {json.dumps(script_name)};")
        if capture_output:
            php_parts.append("$out = ob_get_clean();")
            php_parts.append("if ($out !== false) { echo $out; }")
        else:
            php_parts.append("ob_end_clean();")

        command = (
            f"cd {shlex.quote(script_dir)} && "
            f"php -r {shlex.quote(''.join(php_parts))}"
        )
        out, err = self._cli_full(command)
        if err:
            raise RuntimeError(err)
        return out

    @staticmethod
    def _hex_to_printf_payload(packet_hex: str) -> str:
        packet_hex = re.sub(r"\s+", "", packet_hex)
        if len(packet_hex) % 2 != 0:
            raise ValueError(f"Invalid hex payload length: {len(packet_hex)}")
        return "".join(
            f"\\x{packet_hex[i:i + 2]}"
            for i in range(0, len(packet_hex), 2)
        )

    def _udp_packet_hex_command(self, packet_hex: str, *, port: int) -> str:
        escaped_payload = self._hex_to_printf_payload(packet_hex)
        return (
            f"printf '%b' {shlex.quote(escaped_payload)} | "
            f"socat - UDP:127.0.0.1:{port}"
        )

    def _send_udp_packet_hex(self, packet_hex: str, *, port: int) -> None:
        command = self._udp_packet_hex_command(packet_hex, port=port)
        out, err = self._cli_full(command)
        if err and not out:
            raise RuntimeError(err)

    def _send_udp_packet_hex_detached(self, packet_hex: str, *, port: int) -> None:
        self._fire_and_forget(self._udp_packet_hex_command(packet_hex, port=port))

    def _send_rtsc_command(self, command: str, port: int = 8008) -> str:
        out, err = self._cli_full(
            f"printf %s {shlex.quote(command)} | socat - UDP:127.0.0.1:{port}"
        )
        if err and not out:
            raise RuntimeError(err)
        return out

    def _write_remote_text(self, remote_path: str, content: str) -> None:
        remote_dir = os.path.dirname(remote_path)
        delimiter = "__BURNINGSTATION_EOF__"
        while delimiter in content:
            delimiter += "_X"

        command = (
            f"mkdir -p {shlex.quote(remote_dir)} && "
            f"cat <<'{delimiter}' > {shlex.quote(remote_path)}\n"
            f"{content}\n"
            f"{delimiter}"
        )
        _, err = self._cli_full(command)
        if err:
            raise RuntimeError(err)

    def _read_uipage_html_via_cli(self) -> str:
        page_html, err = self._cli_full(f"cat {shlex.quote(REMOTE_UI_HTML_PATH)}")
        if err and not page_html:
            raise RuntimeError(err)
        return page_html

    @staticmethod
    def _busdev_key_hex(key: str) -> Optional[str]:
        if key in BUSDEV_KEY_HEX:
            return BUSDEV_KEY_HEX[key]
        if re.fullmatch(r"n\d", key):
            return f"{ord(key[1]):02x}00"
        if re.fullmatch(r"a[A-Z]", key):
            return f"{ord(key[1]):02x}00"
        return None

    def _post_busdev_form(
        self,
        data: Dict[str, str],
        *,
        delay: float = 0.1,
        prefer_cli: bool = False,
    ) -> requests.Response:
        url = f"http://{self.host}:8005/web/busdev.php"

        if not prefer_cli:
            resp = self._http_request("post", url, data=data, timeout=0.75)
            if resp is not None:
                time.sleep(delay)
                return resp

        self._run_remote_php_script(REMOTE_BUSDEV_PATH, post_data=data, capture_output=False)
        time.sleep(delay)
        return self._synthetic_response(url, text="cli-fallback")

    def _send_key_press_cli(self, key: str, delay: float = 0.1) -> requests.Response:
        key_hex = self._busdev_key_hex(key)
        if key_hex is None:
            return self._post_busdev_form({key: "1"}, delay=delay, prefer_cli=True)

        payload_hex = BUSDEV_KEY_PACKET_PREFIX + key_hex
        try:
            if self.connected:
                self._send_udp_packet_hex_detached(payload_hex, port=8002)
            else:
                self._send_udp_packet_hex(payload_hex, port=8002)
        except Exception:
            php_code = (
                f'$buf = hex2bin({json.dumps(payload_hex)});'
                '$sock = socket_create(AF_INET, SOCK_DGRAM, 0);'
                'if ($buf === false || $sock === false) { fwrite(STDERR, "Unable to create key packet\\n"); exit(1); }'
                'if (!socket_sendto($sock, $buf, strlen($buf), 0, "127.0.0.1", 8002)) {'
                '  fwrite(STDERR, "Unable to send key packet\\n");'
                '  exit(1);'
                '}'
                'socket_close($sock);'
            )
            _, err = self._cli_full(f"php -r {shlex.quote(php_code)}")
            if err:
                return self._post_busdev_form({key: "1"}, delay=delay, prefer_cli=True)

        time.sleep(delay)
        url = f"http://{self.host}:8005/web/busdev.php"
        return self._synthetic_response(url, text="cli-fallback")

    def _get_config_main_html(self, timeout: float = 2.0) -> str:
        url = f"http://{self.host}:8005/web/config_main.php"
        resp = self._http_request("get", url, timeout=timeout, raise_for_status=True)
        if resp is not None:
            return resp.text

        return self._send_rtsc_command("cmd.main.config")
       
    def get_meter_type(self)-> MeterType:
        if (self.__resolution == ""):
            self.__resolution = self.cli("""fbset -s | grep mode | awk -F'"' '{print $2}' | cut -d- -f1""")

        meter_type:MeterType = ""
        if self.__resolution == "1024x768":
            required_modules = ("PRINTER", "KEY_PAD_2", "COIN_SHUTTER")
            firmware_map = self.firmwares
            missing_modules = [
                module_name
                for module_name in required_modules
                if not firmware_map.get(module_name)
            ]
            # print(f"missing_modules: {missing_modules}")
            are_all_required_modules_missing = len(missing_modules) == len(required_modules)

            meter_type = "ms3"
            if are_all_required_modules_missing:
                meter_type = "msx"
        elif self.__resolution == "800x480": meter_type = "ms2.5"
        return meter_type

    meter_type = property(lambda self: self.get_meter_type())

    def _read_remote_file_if_exists(self, path: str) -> str:
        out, err = self._cli_full(f"cat {shlex.quote(path)}")
        if err and not out:
            err_lower = err.lower()
            if "no such file" in err_lower or "not found" in err_lower:
                return ""
            return ""
        return out.strip()

    def _get_meter_region_registry_values(self) -> Dict[str, str]:
        registry_files = {
            "app": "/cfg/registry/appCfg/app",
            "appCfgVersion": "/cfg/registry/appCfg/appCfgVersion",
            "appOverlayVersion": "/cfg/registry/appOverlay/appOverlayVersion",
        }
        marker = "__BURNINGSTATION_REG__:"
        command_parts = []
        for key, path in registry_files.items():
            command_parts.append(
                f"printf '%s\\n' {shlex.quote(marker + key)};"
                f"cat {shlex.quote(path)} 2>/dev/null || true;"
                "printf '\\n';"
            )

        out, _ = self._cli_full(" ".join(command_parts))
        values = {key: "" for key in registry_files}
        current_key: Optional[str] = None
        current_lines: List[str] = []

        for line in out.splitlines():
            if line.startswith(marker):
                if current_key is not None:
                    values[current_key] = "\n".join(current_lines).strip()
                current_key = line[len(marker):]
                current_lines = []
            else:
                current_lines.append(line)

        if current_key is not None:
            values[current_key] = "\n".join(current_lines).strip()

        return values

    def get_meter_region(self, *, force_refresh: bool = False) -> MeterRegion:
        if self._meter_region_cache is not None and not force_refresh:
            return self._meter_region_cache

        meter_region: MeterRegion = ""
        try:
            values = self._get_meter_region_registry_values()
        except Exception:
            self._meter_region_cache = meter_region
            return meter_region

        uk_hits = 0
        for value in values.values():
            normalized = (value or "").strip().lower()
            if re.search(r"(?<![a-z])uk(?![a-z])", normalized):
                uk_hits += 1

        if uk_hits >= 2:
            meter_region = "uk"
        else:
            meter_region = "us"

        self._meter_region_cache = meter_region
        return meter_region

    meter_region = property(lambda self: self.get_meter_region())

    def in_splash(self):
        """ Checks if the meter is in splash screen """
        page_text = self._get_uipage_html(timeout=0.2).lower()
        if 'unable to open file' in page_text:
            return True
        return False

    def in_diagnostics(self):
        """Returns True if the meter is in diagnostics mode, False otherwise."""
        try:
            page_text = self._get_uipage_html(timeout=5).lower()
            for diag_key in ["diagtitle", "diagcontent", "diaginfo"]:
                if diag_key in page_text:
                    return True
            return False
        except Exception as e:
            print(f"[in_diagnostics] Error fetching http://{self.host}:8005/UIPage.php: {e}")
            return False

    def force_diagnostics(self):
        if self.in_diagnostics():
            self.press('diagnostics')
            time.sleep(0.1)
            self.press('diagnostics')
        else:
            self.press('diagnostics')

    def _get_uipage_html(self, timeout: float = 5.0) -> str:
        url = f"http://{self.host}:8005/UIPage.php"
        resp = self._http_request("get", url, timeout=timeout, raise_for_status=True)
        if resp is not None:
            return resp.text

        return self._read_uipage_html_via_cli()

    def get_ui_page_html(self, timeout: float = 5.0) -> str:
        return self._get_uipage_html(timeout=timeout)

    @staticmethod
    def _parse_modem_state(value: str) -> Optional[str]:
        if not value:
            return None

        match = re.search(
            r"MODEM:\s*state=(S\d+_[A-Z_]+|\(unknown:-?\d+\))",
            value,
            re.IGNORECASE,
        )
        if not match:
            return None

        return match.group(1)

    def get_meter_status_text(self) -> str:
        return self.cli("echo 'cmd.main.meter:status' | socat - UDP:127.0.0.1:8008")

    def get_modem_state(self) -> Optional[str]:
        return self._parse_modem_state(self.get_meter_status_text())

    @staticmethod
    def _strip_html(value: str) -> str:
        text = unescape(value or "")
        text = text.replace("\xa0", " ")
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _diag_label_key(cls, value: str) -> str:
        text = cls._strip_html(value).lower()
        text = re.sub(r"\[[^\]]*\]", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _diag_label_variants(cls, value: str) -> set[str]:
        base = cls._diag_label_key(value)
        if not base:
            return set()

        tokens = base.split()
        variants = {base, "".join(tokens)}
        if tokens and tokens[-1] == "menu":
            core = tokens[:-1]
            if core:
                variants.add(" ".join(core))
                variants.add("".join(core))
        return {variant for variant in variants if variant}

    @classmethod
    def _diag_step_aliases(cls, step) -> set[str]:
        if isinstance(step, str):
            raw_aliases = [part.strip() for part in re.split(r"[|/]", step) if part.strip()]
            if not raw_aliases:
                raw_aliases = [step]
        else:
            raw_aliases = [str(part).strip() for part in step if str(part).strip()]

        aliases: set[str] = set()
        for alias in raw_aliases:
            aliases.update(cls._diag_label_variants(alias))
        return aliases

    @classmethod
    def _diag_matches(cls, aliases: set[str], candidate: str) -> bool:
        return bool(aliases & cls._diag_label_variants(candidate))

    @staticmethod
    def _menu_move(current_index: int, target_index: int, item_count: int) -> Tuple[str, int]:
        down_steps = (target_index - current_index) % item_count
        up_steps = (current_index - target_index) % item_count
        if down_steps <= up_steps:
            return "plus", down_steps
        return "minus", up_steps

    def get_diagnostics_state(self, timeout: float = 5.0) -> DiagPageState:
        page_html = self._get_uipage_html(timeout=timeout)

        title_match = re.search(
            r"<div[^>]*class\s*=\s*[\"']?diagtitle[\"']?[^>]*>\s*<div[^>]*>(.*?)</div>",
            page_html,
            flags=re.I | re.S,
        )
        title = self._strip_html(title_match.group(1)) if title_match else ""
        title = re.sub(r"\s*\[[^\]]*\]\s*", "", title).strip()
        title_segments = [segment.strip() for segment in title.split(":") if segment.strip()]

        pre_match = re.search(
            r"<div[^>]*class\s*=\s*[\"']?diaginfo[\"']?[^>]*>.*?<pre[^>]*>(.*?)</pre>",
            page_html,
            flags=re.I | re.S,
        )
        if pre_match is None:
            pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", page_html, flags=re.I | re.S)
        pre_text = unescape(pre_match.group(1)).replace("\r", "") if pre_match else ""

        menu_items: List[DiagMenuItem] = []
        selected_index: Optional[int] = None
        for line in pre_text.splitlines():
            if not line.strip():
                continue

            selected = bool(DIAG_SELECTED_PREFIX_RE.match(line))
            item_text = DIAG_SELECTED_PREFIX_RE.sub("", line).strip()
            if not item_text:
                continue

            menu_items.append({"text": item_text, "selected": selected})
            if selected:
                selected_index = len(menu_items) - 1

        if selected_index is None:
            menu_items = []

        return {
            "title": title,
            "title_segments": title_segments,
            "menu_items": menu_items,
            "selected_index": selected_index,
            "is_menu": selected_index is not None,
            "page_html": page_html,
        }

    def goto_diagnostics_path(
        self,
        path: Sequence,
        *,
        reset_to_service: bool = True,
        fetch_timeout: float = 4.5,
        press_delay: float = 0.15,
        settle_delay: float = 0.4,
        page_timeout: float = 5.0,
    ) -> DiagPageState:
        steps: List[set[str]] = []
        for step in path:
            aliases = self._diag_step_aliases(step)
            if aliases:
                steps.append(aliases)

        if reset_to_service:
            self.force_diagnostics()
            time.sleep(settle_delay)
        if not self.in_diagnostics():
            self.press('diagnostics')
            time.sleep(settle_delay)

        state = self.get_diagnostics_state(timeout=fetch_timeout)
        if not state["title_segments"]:
            raise RuntimeError("Unable to parse the current diagnostics page title")

        service_aliases = self._diag_step_aliases("service")
        if reset_to_service and not self._diag_matches(service_aliases, state["title_segments"][-1]):
            raise RuntimeError(
                f"Expected diagnostics home page after reset, found '{state['title']}'"
            )

        for target_aliases in steps:
            state = self.get_diagnostics_state(timeout=fetch_timeout)
            if state["title_segments"] and self._diag_matches(target_aliases, state["title_segments"][-1]):
                continue

            if not state["is_menu"]:
                raise RuntimeError(
                    f"Cannot navigate from non-menu diagnostics page '{state['title']}'"
                )

            matching_indexes = [
                index for index, item in enumerate(state["menu_items"])
                if self._diag_matches(target_aliases, item["text"])
            ]
            if not matching_indexes:
                available = ", ".join(item["text"] for item in state["menu_items"])
                raise RuntimeError(
                    f"Unable to find diagnostics item matching {sorted(target_aliases)} on "
                    f"'{state['title']}'. Available items: {available}"
                )

            if state["selected_index"] is None:
                raise RuntimeError(f"Unable to determine the selected diagnostics item on '{state['title']}'")

            target_index = min(
                matching_indexes,
                key=lambda index: min(
                    (index - state["selected_index"]) % len(state["menu_items"]),
                    (state["selected_index"] - index) % len(state["menu_items"]),
                ),
            )

            button, count = self._menu_move(
                state["selected_index"],
                target_index,
                len(state["menu_items"]),
            )
            for _ in range(count):
                self.press(button, delay=press_delay)

            previous_title = state["title"]
            previous_selected = state["selected_index"]
            self.press("ok", delay=press_delay)

            deadline = time.time() + page_timeout
            while True:
                if time.time() > deadline:
                    raise RuntimeError(
                        f"Timed out opening diagnostics item matching {sorted(target_aliases)} "
                        f"from '{previous_title}'"
                    )

                state = self.get_diagnostics_state(timeout=fetch_timeout)
                title_changed = state["title"] != previous_title
                selection_changed = state["selected_index"] != previous_selected

                if state["title_segments"] and self._diag_matches(target_aliases, state["title_segments"][-1]):
                    break
                if title_changed or selection_changed:
                    time.sleep(settle_delay)
                else:
                    time.sleep(settle_delay)

        return self.get_diagnostics_state(timeout=fetch_timeout)


    def press(self, button: str, value: Optional[str] = "1", delay: float = 0.1):
        """
        Sends a button press using user-friendly string. 
        ** UK meters need a persistent connection for comamnds to work quickly. Otherwise you will see very slow button presses, etc.
        Examples:
            press('plus'), press('cancel'), press('1'), press('A'), press('Enter')
        """
        label_map = {
            "+": "plus",
            "-": "minus",
            "up": "plus",
            "down": "minus",
            "enter": "aEnter",
            "aenter": "aEnter",
            "back": "aBack",
            "aback": "aBack",
            "ok": "okay",
            "confirm": "okay",
            "accept": "okay",
            "help": "question",
            "language": "globe",
            "softreset": "softReset",
            "asterisk": "nAsterisk",
            "star": "nAsterisk",
            "*": "nAsterisk",
            "pound": "nPound",
            "hash": "nPound",
            "#": "nPound",
        }
        special_keys = {
            "plus",
            "minus",
            "cancel",
            "okay",
            "question",
            "globe",
            "max",
            "diagnostics",
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

        data = {key: "" if value is None else str(value)}
        url = f"http://{self.host}:8005/web/busdev.php"

        resp = self._http_request("post", url, data=data, timeout=0.75)
        if resp is not None:
            time.sleep(delay)
        else:
            resp = self._send_key_press_cli(key, delay=delay)

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
        def _fetch_html() -> str:
            return self._get_uipage_html(timeout=timeout)

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
            page_html = self._get_uipage_html(timeout=0.5)
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
        
        try:
            page_html = self._get_config_main_html(timeout=timeout)
        except Exception as e:
            print(f"[get_system_versions] Error fetching config_main: {e}")
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
        modules = DEVICE_TO_MODULE.get(device.lower())
        if not modules:
            return ''

        try:
            fw_map = self.firmwares or {}
        except Exception:
            return ''

        for module in modules:
            val = 'yes' if module == 'yes' else (fw_map.get(module) or '').strip()
            if val and not set(val) <= {'-'}:
                return val
        return ''


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
        quoted_inner = shlex.quote(inner)
        wrapped = (
            f"(nohup sh -c {quoted_inner} >/dev/null 2>&1 || "
            f"sh -c {quoted_inner} >/dev/null 2>&1) &"
        )
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
        self.goto_diagnostics_path(
            ["Utilities", "Peripherals", ("Contact(less)", "NFC", "Contactless", "Contactless EMV")]
        )
    
    def goto_keypad(self):
        self.goto_diagnostics_path(
            ["Utilities", "Peripherals", ("Keyboard", "Keypad")]
        )
        time.sleep(0.5)
    
    def goto_power(self):
        self.goto_diagnostics_path(["Power Info"])

    def goto_callin(self):
        self.goto_diagnostics_path(["Call In"])

    def goto_modem_connection(self):
        self.goto_diagnostics_path(["Utilities", "Peripherals", "Modem Connection"])
    
    def goto_coins(self):
        self.goto_diagnostics_path(["Utilities", "Coins"])
    
    def print_msg(self, msg):
        msg  = re.sub(r'\n[ \t]+', '\n', msg)
        url = f"http://{self.host}:8005/web/control_print_direct.php"
        files = {"fileToUpload": ("hello.txt", msg, "text/plain")}
        resp = self._http_request("post", url, files=files, timeout=1)
        if resp is not None:
            return

        remote_path = f"{REMOTE_PRINT_DIR}/print_direct_{int(time.time() * 1000)}.txt"
        self._write_remote_text(remote_path, msg)
        try:
            self._send_rtsc_command(f"cmd.main.printer:pr={remote_path}")
            time.sleep(0.25)
        finally:
            self._cli_full(f"rm -f {shlex.quote(remote_path)}")


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

        firmware_map = self.firmwares or {}
        for k, v in sorted((self.module_info or {}).items()):
            fw = str(v.get("fw") or v.get("ver") or firmware_map.get(k) or "").strip()
            mf = v.get("mod_func", v.get("mod"))

            line = f"{k.lower()}: {fw}"
            if mf not in (None, ""):
                line += f", {mf}"
            if k.upper() == "KIOSK_NFC" or k.upper() == "KIOSK_NEO":
                full_id = v.get("full_id", v.get("id"))
                if full_id not in (None, ""):
                    line += f", {full_id}"
        
            msg += line + "\n"
        
        # tests
        # msg += hdr("test results") + "\n"

        # keys = ["printer", "coin shutter", "nfc" , "modem"]
        # msg += "\n".join(f"{k}: {self.results.get(k, 'n/a').lower()}" for k in keys)
        # msg += "\n"

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
        meter_region = str(self.meter_region or "").strip().lower() or "us"
        value_to_index = COIN_VALUE_TO_INDEX_BY_REGION.get(meter_region)
        index = None if value_to_index is None else value_to_index.get(value)
        if index is None:
            raise ValueError(
                f"Coin value {value} not supported for meter region {meter_region}."
            )

        data = {f"coin,{index},{value}": str(value)}
        resp = self._post_busdev_form(data, delay=delay)
        return resp

    def clear_coin_tallies(
        self,
        *,
        wallet_reset_delay: float = 0.3,
        collection_start_timeout: float = 4.0,
        collection_flow_timeout: float = 30.0,
        verify_timeout: float = 10.0,
        poll_interval: float = 1.0,
    ) -> bool:
        return clear_coin_tallies_impl(
            self,
            wallet_reset_delay=wallet_reset_delay,
            collection_start_timeout=collection_start_timeout,
            collection_flow_timeout=collection_flow_timeout,
            verify_timeout=verify_timeout,
            poll_interval=poll_interval,
        )

    def _send_raw_ipsbus_hex(self, hex_payload: str, delay: float = 0.1) -> None:
        compact = re.sub(r"\s+", "", hex_payload or "")
        if not compact:
            raise ValueError("Raw IPSBus payload must not be empty")
        if len(compact) % 2 != 0:
            raise ValueError(f"Raw IPSBus payload has odd hex length: {len(compact)}")

        escaped = "".join(
            f"\\x{compact[index:index + 2]}"
            for index in range(0, len(compact), 2)
        )
        cmd = f"printf '%b' '{escaped}' | socat -u - udp-send:127.0.0.1:8002"
        self.cli(cmd)
        time.sleep(delay)

    @staticmethod
    def _build_legacy_special_card_hex(
        track2: str,
        *,
        module: int = CARD_READ_NFC_MODULE,
        read_type: int = CARD_READ_TYPE_MSD_CONTACTLESS,
    ) -> str:
        if not track2:
            raise ValueError("track2 must not be empty")
        if len(track2) > CARD_READ_TRACK2_MAX_LEN:
            raise ValueError(
                f"track2 too long for legacy card frame: {len(track2)} > {CARD_READ_TRACK2_MAX_LEN}"
            )

        match = re.search(r"=(\d{4})", track2)
        if not match:
            raise ValueError(f"track2 is missing YYMM expiry: {track2!r}")

        payload = bytearray.fromhex(LEGACY_CARD_READ_TEMPLATE_HEX)
        payload[CARD_READ_SRC_MODULE_OFFSET] = module & 0xFF
        payload[CARD_READ_HEADER_LEN + CARD_READ_READ_TYPE_OFFSET] = read_type & 0xFF
        payload[CARD_READ_HEADER_LEN + CARD_READ_ENCRYPTION_TYPE_OFFSET] = 0
        payload[CARD_READ_HEADER_LEN + CARD_READ_CARD_TYPE_OFFSET] = 0

        exp_yymm = match.group(1).encode("ascii")
        payload[
            CARD_READ_HEADER_LEN + CARD_READ_EXP_DATE_OFFSET:
            CARD_READ_HEADER_LEN + CARD_READ_EXP_DATE_OFFSET + len(exp_yymm)
        ] = exp_yymm

        track2_bytes = track2.encode("ascii")
        track2_start = CARD_READ_HEADER_LEN + CARD_READ_TRACK2_OFFSET
        track2_end = track2_start + CARD_READ_TRACK2_MAX_LEN
        payload[track2_start:track2_end] = b"\x00" * CARD_READ_TRACK2_MAX_LEN
        payload[track2_start:track2_start + len(track2_bytes)] = track2_bytes
        return payload.hex()

    def present_special_card_raw(
        self,
        card_name: str,
        *,
        delay: float = 0.1,
        module: int = CARD_READ_NFC_MODULE,
    ) -> requests.Response:
        normalized = re.sub(r"[^A-Z]", "", str(card_name or "").upper())
        track2 = SPECIAL_CARD_TRACK2.get(normalized)
        if track2 is None:
            supported = ", ".join(sorted(SPECIAL_CARD_TRACK2))
            raise ValueError(f"Unsupported special card '{card_name}'. Supported: {supported}")

        hex_payload = self._build_legacy_special_card_hex(track2, module=module)
        self._send_raw_ipsbus_hex(hex_payload, delay=delay)

        if getattr(self, "verbose", False):
            print(
                f"{self.host} Sent raw special card: {normalized} | "
                f"module={module} | payload_len={len(hex_payload) // 2}"
            )

        resp = requests.Response()
        resp.status_code = 200
        resp._content = hex_payload.encode("ascii")
        resp.headers["X-Busdev-Bypass"] = "raw-ipsbus"
        return resp

    def present_coin_collection_card(self, delay: float = 0.1) -> requests.Response:
        return self.present_special_card_raw("COINCOLLECTION", delay=delay)

    def present_meter_diagnostics_card(self, delay: float = 0.1) -> requests.Response:
        return self.present_special_card_raw("METERDIAGNOSTICS", delay=delay)
    
    def custom_busdev(self, button_name, button_value, delay=0.1):
        data = {button_name: "" if button_value is None else str(button_value)}
        resp = self._post_busdev_form(data, delay=delay)
        return resp

    def set_ui_mode(self, mode: str) -> None:
        """Set the UI mode on the meter."""
        valid_modes = {"stock", "banner", "charuco", "apriltag", "results"}
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

        meter_type = self.meter_type
        print(f"[setup_custom_display] host={self.host} status={self.status} connected={self.connected} meter_type={meter_type}")

        if is_custom_display_current(self):
            # print(f"[setup_custom_display] display already current, forcing diagnostics refresh then returning")
            self.force_diagnostics()
            return

        self.status = "busy"
        try:
            # print(f"[setup_custom_display] uploading assets ({meter_type})")
            write_ui_page(self)
            write_ui_overlay(self)
            
            local_charuco = CHARUCO_PATHS.get(meter_type)
            if not local_charuco:
                raise ValueError(f"No Charuco path defined for meter_type: {meter_type}")
            if not os.path.exists(local_charuco):
                raise FileNotFoundError(f"Local Charuco file not found: {local_charuco}")
            upload_image(self, local_charuco, "charuco")

            ## Apriltag isn't currently used in the system so we can skip it for now, but leaving the code here in case we want to add it back in later
            # local_apriltag = get_apriltag_path(self)
            # if not os.path.exists(local_apriltag):
            #     raise FileNotFoundError(f"Local Apriltag file not found: {local_apriltag}")
            # upload_image(self, local_apriltag, "apriltag")

            print(f"[setup_custom_dsplay] done for {self.host}")
        finally:
            self.status = "ready"

    def update_display_results(self, shared: SharedState) -> None:
        """Update the meter's _display_results dict based on the completed job in SharedState."""
        program_name = shared.current_program
        if program_name not in ["cycle_all", "physical_cycle_all"]:
            shared.log(f"unable to update display results for program_name = '{program_name}'", console=True)
            return

        # Initialize _display_results if it doesn't exist yet
        if not hasattr(self, "_display_results") or self._display_results is None:
            self._display_results = {
                "overall_result": "N/A",
                "meter_info": {
                    "IP": self.host,
                    "Hostname": self.hostname,
                    "Meter Type": self.meter_type
                },
                "passive": {
                    "device_results": {},
                    "other_info": {}
                },
                "physical": {
                    "device_results": {},
                    "other_info": {}
                }
            }

        section = "passive" if program_name == "cycle_all" else "physical"

        # device_results
        dev_res = {k: str(v).lower() for k, v in shared.device_results.items()}
        self._display_results[section]["device_results"] = dev_res

        # other_info
        other_info = {k: str(v) for k, v in shared.device_meta.items()}
        other_info["Error"] = shared.last_error or "None"
        self._display_results[section]["other_info"] = other_info

        # compute overall_result: FAIL if any device result is "fail" (across both sections)
        all_dev_res = {
            **self._display_results["passive"]["device_results"],
            **self._display_results["physical"]["device_results"]
        }
        if any(v == "fail" for v in all_dev_res.values()):
            self._display_results["overall_result"] = "FAIL"
        else:
            self._display_results["overall_result"] = "PASS"

        write_results_json(self, self._display_results)
        self.set_ui_mode("results")
        
    def blink(self, amnt=2) -> None:
        v = self.get_brightness()
        for i in range(amnt):
            self.set_brightness(0)
            self.beep(1)
            time.sleep(0.1)
            self.set_brightness(50)
            self.beep(1)
            time.sleep(0.1)
        self.set_brightness(v)

    def blink_until_start(self, low: int = 0, high: int = 50, interval: float = 0.25, max_duration: float = 60.0, on_done=None) -> None:
        self.blink_until_stop()

        stop_event = threading.Event()
        previous_status = self.status

        with self._lock:
            self._blink_until_stop = stop_event
            self._blink_until_thread = None
            self._blink_until_status = previous_status
            self.status = "busy"

        def _blink_loop():
            brightness = high
            try:
                brightness = self.get_brightness()
                deadline = time.monotonic() + max(0.0, float(max_duration))
                while not stop_event.is_set() and time.monotonic() < deadline:
                    self.set_brightness(low)
                    self.beep(1)
                    if stop_event.wait(interval):
                        break
                    self.set_brightness(high)
                    self.beep(1)
                    stop_event.wait(interval)
            finally:
                try:
                    self.set_brightness(brightness)
                finally:
                    with self._lock:
                        if self._blink_until_stop is stop_event:
                            self.status = previous_status
                            self._blink_until_stop = None
                            self._blink_until_thread = None
                            self._blink_until_status = None
                            if on_done:
                                on_done()

        thread = threading.Thread(target=_blink_loop, name=f"meter-blink-{self.host}", daemon=True)
        with self._lock:
            self._blink_until_thread = thread
        thread.start()

    def blink_until_stop(self) -> None:
        with self._lock:
            stop_event = self._blink_until_stop
            thread = self._blink_until_thread

        if stop_event:
            stop_event.set()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)


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
