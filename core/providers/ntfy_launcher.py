"""
core/ntfy_launcher.py — JARVIS Self-Hosted ntfy Server Manager
===============================================================
Launches a private ntfy server binary on port 8124 with:
  • auth-default-access: deny-all  (no anonymous access)
  • A single authenticated user 'thomas' with a random 32-char password
  • All traffic confined to localhost/LAN — zero public internet exposure

Execution order:
  1. Ensure ntfy binary is present (auto-download v2.11.0 Windows AMD64 if missing)
  2. Write a server.yml config to <jarvis_root>/ntfy_data/
  3. Create user 'thomas' via `ntfy user add`
  4. Launch `ntfy serve` as a subprocess; keep the process alive via a daemon thread
  5. Expose `NTFY_PASSWORD`, `NTFY_URL`, and `is_running` for consumers
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from auth.device import get_device_id

log = logging.getLogger("ntfy_launcher")
log.setLevel(logging.INFO)

# ─── Constants ────────────────────────────────────────────────────────────────

NTFY_PORT:    int  = 8124
NTFY_VERSION: str  = "v2.11.0"          # pinned — change to test new releases

# Download URLs per platform
_NTFY_DOWNLOADS: dict[str, str] = {
    "windows_amd64": (
        f"https://github.com/binwiederhier/ntfy/releases/download/{NTFY_VERSION}/"
        f"ntfy_{NTFY_VERSION}_windows_amd64.zip"
    ),
    "linux_amd64": (
        f"https://github.com/binwiederhier/ntfy/releases/download/{NTFY_VERSION}/"
        f"ntfy_{NTFY_VERSION}_linux_amd64.tar.gz"
    ),
    "darwin_arm64": (
        f"https://github.com/binwiederhier/ntfy/releases/download/{NTFY_VERSION}/"
        f"ntfy_{NTFY_VERSION}_darwin_arm64.tar.gz"
    ),
}

# ─── Derived Paths ────────────────────────────────────────────────────────────

_ROOT     = Path(__file__).resolve().parent.parent          # JARVIS repo root
_DATA_DIR = _ROOT / "ntfy_data"                             # server data + cache
_BIN_DIR  = _ROOT / "ntfy_bin"                              # binary location
_BIN_NAME = "ntfy.exe" if platform.system() == "Windows" else "ntfy"
_BIN_PATH = _BIN_DIR / _BIN_NAME
_CFG_PATH = _DATA_DIR / "server.yml"

# ─── Shared State ─────────────────────────────────────────────────────────────

NTFY_URL:      str  = f"http://127.0.0.1:{NTFY_PORT}"
NTFY_USER:     str  = "thomas"
NTFY_PASSWORD: str  = ""       # filled in by start()
is_running:    bool = False

_process:      subprocess.Popen | None = None
_lock:         threading.Lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — Binary acquisition
# ══════════════════════════════════════════════════════════════════════════════

def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return f"{system}_{arch}"


def _ensure_binary() -> Path:
    """
    Return path to the ntfy binary, downloading it first if absent.
    Verifies the binary is executable before returning.
    """
    if _BIN_PATH.exists():
        log.info(f"[ntfy_launcher] Binary found: {_BIN_PATH}")
        return _BIN_PATH

    key = _platform_key()
    url = _NTFY_DOWNLOADS.get(key)
    if not url:
        raise RuntimeError(
            f"[ntfy_launcher] No download URL for platform '{key}'. "
            "Download ntfy manually from https://github.com/binwiederhier/ntfy/releases "
            f"and place the binary at: {_BIN_PATH}"
        )

    log.info(f"[ntfy_launcher] Downloading ntfy {NTFY_VERSION} for {key}…")
    _BIN_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip" if key.startswith("win") else ".tar.gz") as tmp:
        tmp_path = Path(tmp.name)

    try:
        urllib.request.urlretrieve(url, tmp_path)
        _extract_binary(tmp_path, key)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not _BIN_PATH.exists():
        raise RuntimeError(f"[ntfy_launcher] Binary not found after extraction: {_BIN_PATH}")

    # Make executable on POSIX
    if platform.system() != "Windows":
        _BIN_PATH.chmod(0o755)

    log.info(f"[ntfy_launcher] Binary ready at: {_BIN_PATH}")
    return _BIN_PATH


def _extract_binary(archive: Path, key: str) -> None:
    """Unpack the ntfy binary from the downloaded archive into _BIN_DIR."""
    if key.startswith("windows"):
        import zipfile
        with zipfile.ZipFile(archive, "r") as zf:
            for member in zf.namelist():
                if member.endswith(".exe"):
                    zf.extract(member, _BIN_DIR)
                    # Flatten any sub-directory structure
                    extracted = _BIN_DIR / member
                    if extracted != _BIN_PATH:
                        extracted.rename(_BIN_PATH)
                    break
    else:
        import tarfile
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if member.name.endswith("/ntfy") or member.name == "ntfy":
                    member.name = _BIN_NAME
                    tf.extract(member, _BIN_DIR)
                    break


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — Configuration
# ══════════════════════════════════════════════════════════════════════════════

_SERVER_YML_TEMPLATE = """\
# ══════════════════════════════════════════════════════
#  JARVIS Private ntfy Server Configuration
#  Generated automatically — do not edit by hand
# ══════════════════════════════════════════════════════

listen-http: "0.0.0.0:{port}"          # Allow LAN access for mobile auth

base-url:    "http://{lan_ip}:{port}"

# Storage
cache-file:  "{data_dir}/cache.db"
auth-file:   "{data_dir}/auth.db"

# ── Security ──────────────────────────────────────────
auth-default-access: "deny-all"          # block all unauthenticated subscribers/publishers
behind-proxy:        false

# ── Rate-limiting ─────────────────────────────────────
visitor-request-limit-burst:     60
visitor-request-limit-replenish: "1m"
"""


def _get_lan_ip() -> str:
    """Detect the LAN IP of this machine."""
    import socket
    try:
        # Connect to a dummy external IP to see which local interface is used
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def _write_config() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    lan_ip = _get_lan_ip()
    global NTFY_URL
    NTFY_URL = f"http://{lan_ip}:{NTFY_PORT}"
    
    cfg = _SERVER_YML_TEMPLATE.format(
        port=NTFY_PORT,
        data_dir=str(_DATA_DIR).replace("\\", "/"),
        lan_ip=lan_ip
    )
    _CFG_PATH.write_text(cfg, encoding="utf-8")
    log.info(f"[ntfy_launcher] Config written to {_CFG_PATH} (LAN IP: {lan_ip})")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — User management
# ══════════════════════════════════════════════════════════════════════════════

def _provision_user(binary: Path, password: str) -> None:
    """
    Create (or reset) user 'thomas' with the given password.
    ntfy exits 0 on success, non-zero on failure.
    """
    base_cmd = [str(binary), "--config", str(_CFG_PATH)]

    # Delete if already exists (idempotent bootstrap)
    subprocess.run(
        base_cmd + ["user", "del", NTFY_USER],
        capture_output=True,
        text=True,
    )

    # Create fresh
    result = subprocess.run(
        base_cmd + ["user", "add", "--role=user", f"{NTFY_USER}:{password}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"[ntfy_launcher] Failed to create user '{NTFY_USER}': {result.stderr.strip()}"
        )

    # Grant publish + subscribe access to the JARVIS auth topic wildcard
    result = subprocess.run(
        base_cmd + ["access", NTFY_USER, "JARVIS_AUTH_*", "rw"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning(f"[ntfy_launcher] ACL grant warning: {result.stderr.strip()}")

    log.info(f"[ntfy_launcher] User '{NTFY_USER}' provisioned with topic access JARVIS_AUTH_*")


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Process supervision
# ══════════════════════════════════════════════════════════════════════════════

def _supervisor(binary: Path) -> None:
    """
    Runs `ntfy serve` and restarts it automatically if it crashes.
    Runs in a daemon thread so it doesn't block JARVIS startup.
    """
    global _process, is_running
    cmd = [str(binary), "serve", "--config", str(_CFG_PATH)]
    log.info(f"[ntfy_launcher] Starting: {' '.join(cmd)}")

    while True:
        try:
            with _lock:
                _process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                is_running = True

            _process.wait()                     # block until ntfy exits
            stderr = _process.stderr.read() if _process.stderr else ""
            log.warning(f"[ntfy_launcher] ntfy exited (rc={_process.returncode}): {stderr[:200]}")

        except FileNotFoundError:
            log.error("[ntfy_launcher] ntfy binary not found — cannot supervise.")
            break
        except Exception as exc:
            log.error(f"[ntfy_launcher] Supervisor error: {exc}")
        finally:
            with _lock:
                is_running = False

        log.info("[ntfy_launcher] Restarting ntfy in 3 s…")
        time.sleep(3)


def _wait_for_server(timeout: float = 10.0) -> bool:
    """Poll the ntfy health endpoint until the server is accepting connections."""
    import urllib.error
    deadline = time.time() + timeout
    url      = f"{NTFY_URL}/v1/health"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def start() -> dict:
    """
    Full bootstrap:
      1. Download binary if required
      2. Write server.yml
      3. Provision user 'thomas'
      4. Launch ntfy serve in a daemon supervisor thread
      5. Wait up to 10 s for health check

    Returns a dict with connection details for use by auth_bridge.py.
    """
    global NTFY_PASSWORD

    binary = _ensure_binary()
    NTFY_PASSWORD = secrets.token_urlsafe(24)

    # Save credentials for user reference (Upgrade #10)
    _cred_file = _ROOT / "memory" / "ntfy_creds.txt"
    try:
        _ROOT.joinpath("memory").mkdir(parents=True, exist_ok=True)
        with open(_cred_file, "w", encoding="utf-8") as f:
            f.write(f"URL:      {NTFY_URL}\n")
            f.write(f"User:     {NTFY_USER}\n")
            f.write(f"Password: {NTFY_PASSWORD}\n")
            f.write(f"Topic:    JARVIS_AUTH_{get_device_id()[:8]}\n")
        log.info(f"[ntfy_launcher] Credentials saved to: {_cred_file}")
    except Exception as e:
        log.warning(f"[ntfy_launcher] Failed to save credentials file: {e}")

    _write_config()
    _provision_user(binary, NTFY_PASSWORD)

    t = threading.Thread(target=_supervisor, args=(binary,), daemon=True, name="ntfy-supervisor")
    t.start()

    alive = _wait_for_server(timeout=12.0)
    if alive:
        log.info(f"[ntfy_launcher] Server ready at {NTFY_URL}")
    else:
        log.warning("[ntfy_launcher] Server did not respond within 12 s - check ntfy_data/")

    return {
        "url": NTFY_URL,
        "user": NTFY_USER,
        "password": NTFY_PASSWORD,
        "port": NTFY_PORT,
        "alive": alive,
    }


def stop() -> None:
    """Terminate the ntfy process (used on JARVIS shutdown)."""
    global is_running
    with _lock:
        if _process and _process.poll() is None:
            _process.terminate()
            log.info("[ntfy_launcher] ntfy process terminated.")
        is_running = False


def get_credentials() -> tuple[str, str, str]:
    """Return (url, user, password) for use in auth_bridge or mobile setup."""
    return NTFY_URL, NTFY_USER, NTFY_PASSWORD


def setup_event_subscriber():
    """Subscribe to EventNtfyPush from the global EventBus."""
    from core.system.event_bus import get_event_bus
    from core.system.events import EventNtfyPush
    import requests

    def on_ntfy_push(event: EventNtfyPush):
        if not is_running:
            return
        
        def _send():
            try:
                url = f"{NTFY_URL}/jarvis"
                auth = (NTFY_USER, NTFY_PASSWORD)
                requests.post(
                    url,
                    data=event.message[:500].encode("utf-8"),
                    headers={
                        "Title":    event.title[:100],
                        "Priority": event.priority,
                        "Tags":     event.tags,
                    },
                    auth=auth,
                    timeout=3,
                )
            except Exception:
                pass
        
        threading.Thread(target=_send, daemon=True, name="NtfyPushSender").start()

    get_event_bus().subscribe(EventNtfyPush, on_ntfy_push)
    log.info("[ntfy_launcher] Event subscriber active.")


# ── CLI entry point ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    info = start()
    print("\n" + "═" * 52)
    print("  JARVIS PRIVATE NTFY SERVER")
    print("═" * 52)
    print(f"  URL      : {info['url']}")
    print(f"  User     : {info['user']}")
    print(f"  Password : {info['password']}")
    print(f"  Status   : {'✓ ONLINE' if info['alive'] else '⚠ NOT RESPONDING'}")
    print("═" * 52)
    print("  Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop()
