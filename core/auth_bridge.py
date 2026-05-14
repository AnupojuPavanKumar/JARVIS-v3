"""
core/auth_bridge.py — Mobile biometric auth bridge via NTFY.

Acts as the interface between JARVIS and your mobile device.
Sends a secure notification to your phone with Approve/Deny buttons.
"""

import threading
import time
import requests
import json
import logging
from typing import Optional

log = logging.getLogger("auth_bridge")

# ── State flags ───────────────────────────────────────────────────────────────
is_verified: bool = False
is_timed_out: bool = False
_topic: Optional[str] = None
_lock = threading.Lock()
_listener_thread: Optional[threading.Thread] = None

# ── Connection check ──────────────────────────────────────────────────────────

def ping_sync() -> bool:
    """
    Checks if the local ntfy server is running.
    """
    from core.providers.ntfy_launcher import is_running
    return is_running

# ── Auth lifecycle ─────────────────────────────────────────────────────────────

def reset():
    """Reset auth state for a new auth session."""
    global is_verified, is_timed_out
    with _lock:
        is_verified = False
        is_timed_out = False

def approve():
    global is_verified
    with _lock:
        is_verified = True
        log.info("[AuthBridge] Remote access APPROVED.")

def timeout():
    global is_timed_out
    with _lock:
        is_timed_out = True

def _listen_for_response(topic: str, server_url: str, auth: tuple):
    """Long-polling listener for the ntfy response."""
    global is_verified
    url = f"{server_url}/{topic}/json"
    
    try:
        # We listen for a message containing "APPROVED"
        with requests.get(url, stream=True, auth=auth, timeout=30) as r:
            for line in r.iter_lines():
                if is_verified or is_timed_out: break
                if line:
                    msg = json.loads(line)
                    text = msg.get("message", "").upper()
                    if "APPROVE" in text or "GRANT" in text:
                        approve()
                        break
    except Exception as e:
        log.error(f"[AuthBridge] Listener error: {e}")

def start_session(timeout_sec: float = 30.0):
    """
    Sends an ntfy request to mobile and starts the listener.
    """
    from core.providers.ntfy_launcher import get_credentials, is_running
    if not is_running:
        log.warning("[AuthBridge] ntfy server not running. Skipping mobile auth.")
        timeout()
        return

    reset()
    url, user, pwd = get_credentials()
    auth = (user, pwd)
    
    # Unique topic for this device's auth
    from auth.device import get_device_id
    topic = f"JARVIS_AUTH_{get_device_id()[:8]}"
    
    # 1. Send Notification with Biometric/FaceID Emphasis
    try:
        requests.post(
            f"{url}/{topic}",
            data="Awaiting mobile biometric verification. Unlock your device and tap APPROVE to link neural pathways.",
            headers={
                "Title": "⚡ JARVIS: Biometric Challenge",
                "Priority": "urgent",
                "Tags": "faceid,lock,zap",
                "Click": f"{url}/{topic}", # Opening the topic in app often triggers biometric unlock
                "Actions": f"view, Approve (FaceID/TouchID), {url}/{topic}?message=APPROVE, clear=true; view, Deny, {url}/{topic}?message=DENY, clear=true"
            },
            auth=auth,
            timeout=5
        )
        log.info(f"[AuthBridge] Biometric challenge sent to topic: {topic}")
    except Exception as e:
        log.error(f"[AuthBridge] Failed to send auth request: {e}")
        timeout()
        return

    # 2. Start Listener
    threading.Thread(target=_listen_for_response, args=(topic, url, auth), daemon=True).start()

    # 3. Start Timeout Timer
    _expire_evt = threading.Event()

    def _expire():
        _expire_evt.wait(timeout=timeout_sec)
        if not is_verified:
            log.warning("[AuthBridge] Mobile auth timed out.")
            timeout()

    threading.Thread(target=_expire, daemon=True, name="AuthBridgeExpire").start()
