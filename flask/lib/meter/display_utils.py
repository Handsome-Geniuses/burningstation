import os
import base64
import hashlib
from typing import Optional

BASE_DIR = os.path.join(os.path.dirname(__file__), "assets")
UI_PAGE_PATH = os.path.join(BASE_DIR, "UIPage.php")
UI_OVERLAY_PATH = os.path.join(BASE_DIR, "ui_overlay.json")

CHARUCO_PATHS = {
    "ms2.5": os.path.join(BASE_DIR, "ms25_charuco.png"),
    "ms3": os.path.join(BASE_DIR, "ms3_charuco.png"),
    "msx": os.path.join(BASE_DIR, "msx_charuco.png"),
}

# ------------------------------------------------------------------
# Upload helpers
# ------------------------------------------------------------------
def ensure_remote_dir(meter: "SSHMeter", remote_dir: str) -> None:  # type: ignore [name-defined]
    """Create remote directories if they don't exist using SSH."""
    cmd = f"mkdir -p {remote_dir}"
    meter.cli(cmd)

def write_ui_page(meter: "SSHMeter") -> None:  # type: ignore [name-defined]
    """Write the local UIPage.php to the remote meter via SSH command."""
    if not os.path.exists(UI_PAGE_PATH):
        raise FileNotFoundError(f"Local UIPage.php not found at {UI_PAGE_PATH}")
    
    with open(UI_PAGE_PATH, "r", encoding="utf-8", newline="") as f:
        php_content = f.read()
    
    remote_path = "/var/volatile/html/UIPage.php"
    ensure_remote_dir(meter, "/var/volatile/html")
    
    # Use heredoc for multi-line text upload
    cmd = f"cat <<'EOF' > {remote_path}\n{php_content}EOF"
    meter.cli(cmd)

def write_ui_overlay(meter: "SSHMeter") -> None:  # type: ignore [name-defined]
    """Write the local ui_overlay.json to the remote meter via SSH command (optional)."""
    if not os.path.exists(UI_OVERLAY_PATH):
        raise FileNotFoundError(f"Local ui_overlay.json not found at {UI_OVERLAY_PATH}")
    
    with open(UI_OVERLAY_PATH, "r", encoding="utf-8", newline="") as f:
        json_content = f.read()
    
    remote_path = "/var/volatile/html/ui_overlay.json"
    ensure_remote_dir(meter, "/var/volatile/html")
    
    # Use heredoc for multi-line text upload
    cmd = f"cat <<'EOF' > {remote_path}\n{json_content}EOF"
    meter.cli(cmd)

def upload_charuco(meter: "SSHMeter", local_path: str) -> None:  # type: ignore [name-defined]
    """Upload the local Charuco PNG to the remote meter via chunked binary SSH, renaming to charuco.png."""
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local Charuco file not found: {local_path}")
    
    with open(local_path, "rb") as f:
        binary_content = f.read()
    
    remote_dir = "/var/volatile/html/content/Images"
    remote_path = f"{remote_dir}/charuco.png"
    ensure_remote_dir(meter, remote_dir)
    
    meter.cli(f"> {remote_path}")  # Truncate or create empty file
    
    # Upload in chunks to avoid command length limits
    chunk_size = 500  # Smaller chunks for safety in minimal shells
    for i in range(0, len(binary_content), chunk_size):
        chunk = binary_content[i:i + chunk_size]
        # Convert to hex pairs and format as \\xHH\\xHH...
        hex_pairs = [chunk.hex()[j:j+2] for j in range(0, len(chunk.hex()), 2)]
        printf_arg = ''.join(f'\\x{x}' for x in hex_pairs)
        cmd = f"printf '{printf_arg}' >> {remote_path}"
        meter.cli(cmd)

# ------------------------------------------------------------------
# Detection helpers
# ------------------------------------------------------------------
def _local_text_file_hash(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return hashlib.sha256(f.read().encode("utf-8")).hexdigest()

def _remote_sha256(meter: "SSHMeter", remote_path: str) -> Optional[str]:  # type: ignore [name-defined]
    """
    Return SHA256 hexdigest of a remote file using the meter's built-in sha256sum.
    Returns None if file missing or command fails.
    """
    out = meter.cli(f"sha256sum '{remote_path}' 2>/dev/null || echo ''").strip()
    if not out:
        return None
    return out.split()[0]  # first column is the hash

def is_custom_display_current(meter: "SSHMeter") -> bool:  # type: ignore [name-defined]
    """
    Return True only if:
      • UIPage.php is present and byte-identical to local version
      • charuco.png is present and byte-identical to the correct version for this meter_type
    """
    # UIPage.php
    expected_ui_hash = _local_text_file_hash(UI_PAGE_PATH)
    remote_ui_hash = _remote_sha256(meter, "/var/volatile/html/UIPage.php")

    if remote_ui_hash != expected_ui_hash:
        # print(f"expected_ui_hash: {expected_ui_hash}")
        # print(f"remote_ui_hash: {remote_ui_hash}")
        return False

    # charuco.png
    local_charuco = CHARUCO_PATHS.get(meter.meter_type)
    if not local_charuco or not os.path.exists(local_charuco):
        raise FileNotFoundError(f"No local Charuco PNG for meter_type='{meter.meter_type}'")

    with open(local_charuco, "rb") as f:
        expected_charuco_hash = hashlib.sha256(f.read()).hexdigest()

    remote_charuco_hash = _remote_sha256(meter, "/var/volatile/html/content/Images/charuco.png")
    if remote_charuco_hash != expected_charuco_hash:
        # print(f"expected_charuco_hash: {expected_charuco_hash}")
        # print(f"remote_charuco_hash: {remote_charuco_hash}")
        return False

    return True

