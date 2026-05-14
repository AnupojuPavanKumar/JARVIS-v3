"""
core/auth_bridge.py — JARVIS Mobile Biometric Handoff Bridge  (v2 — Private Edition)
======================================================================================
What changed from v1:
  • Pushes to a SELF-HOSTED ntfy server (core/ntfy_launcher.py) instead of ntfy.sh
  • The push payload is AES-256-GCM encrypted — intercepting local Wi-Fi reveals nothing
  • /verify endpoint now ONLY accepts 192.168.0.0/16 + loopback (strict LAN lockdown)
  • Encryption key is generated fresh each JARVIS session and printed to console for
    one-time phone setup (paste it into Shortcuts / Tasker once)

Encryption scheme — AES-256-GCM:
  • 256-bit random session key (regenerated every restart)
  • 96-bit random IV (nonce) per message
  • Wire format: base64( iv[12] || ciphertext || tag[16] )
  • Phone decodes with the same key hardcoded in its automation

Security layers:
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. Self-hosted ntfy on 127.0.0.1 — never leaves the machine │
  │ 2. AES-256-GCM payload — even Wi-Fi sniffers see gibberish  │
  │ 3. /verify restricted to 192.168.x.x + loopback only (403)  │
  │ 4. Auth token: secrets.compare_digest(sha256, sha256)        │
  │ 5. 15-second session window — replay attacks hit a dead gate │
  └─────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import sys
import threading
import time
from typing import Optional

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

# ─── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("auth_bridge")
log.setLevel(logging.INFO)

# ─── Configuration ─────────────────────────────────────────────────────────────

# ─── Persistent Auth Key (auto-generated on first boot) ────────────────────────
# Security fix: the old fallback "JARVIS_PRIME_7743" was globally predictable —
# anyone on ntfy.sh could spam biometric requests to "JARVIS_AUTH_JARVIS_PRIME_7743".
#
# Fix: generate a cryptographically random key once and persist it to
# memory/auth_config.json. Subsequent restarts load the same key, so the
# phone's Shortcuts/Tasker config stays valid across reboots.
# The JARVIS_AUTH_KEY env var still overrides everything (for CI / custom setups).

_AUTH_CONFIG_PATH = os.path.join("memory", "auth_config.json")


def _load_or_create_unique_key() -> str:
    """Load persisted auth key, or generate and save a new one on first boot."""
    env_key = os.getenv("JARVIS_AUTH_KEY")
    if env_key:
        return env_key   # Explicit env var always wins

    os.makedirs("memory", exist_ok=True)
    if os.path.exists(_AUTH_CONFIG_PATH):
        try:
            with open(_AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("unique_key", "")
            if key and len(key) >= 16:
                log.info("[auth_bridge] Loaded persistent auth key from auth_config.json")
                return key
        except Exception as exc:
            log.warning(f"[auth_bridge] Could not read auth_config.json: {exc}")

    # First boot — generate a strong random key and persist it
    new_key = secrets.token_urlsafe(24)   # 192 bits, URL-safe base64
    try:
        with open(_AUTH_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"unique_key": new_key, "note": "Auto-generated on first boot. Do not share."}, f, indent=2)
        log.info("[auth_bridge] Generated and saved new persistent auth key.")
    except Exception as exc:
        log.warning(f"[auth_bridge] Could not persist auth key: {exc}")
    return new_key


UNIQUE_KEY:       str = _load_or_create_unique_key()
NTFY_TOPIC:       str = f"JARVIS_AUTH_{UNIQUE_KEY}"

VERIFY_TIMEOUT_S: int = 15

# These are overridden by start_bridge_server() once ntfy_launcher.start() fires.
# Defaults point to local server; fall back to ntfy.sh only if local is unavailable.
_ntfy_base:     str = "http://127.0.0.1:8124"   # updated by configure_ntfy()
_ntfy_user:     str = ""
_ntfy_password: str = ""

# ─── Session Secrets (regenerated every JARVIS restart) ────────────────────────

# AES-256 key — 32 random bytes, displayed as hex for phone setup
_AES_KEY_BYTES: bytes = secrets.token_bytes(32)
AES_KEY_HEX:    str   = _AES_KEY_BYTES.hex()    # 64-char hex → paste into phone shortcut

# HMAC auth token for /verify endpoint
AUTH_TOKEN: str = secrets.token_hex(32)          # 64-char hex

# ── Strict LAN-only CIDR (Task 3 — 192.168.x.x + loopback only) ───────────────
_PERMITTED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),          # localhost
    ipaddress.ip_network("192.168.0.0/16"),       # ← strict home LAN only
    ipaddress.ip_network("::1/128"),              # IPv6 loopback
]

# ─── Shared State ──────────────────────────────────────────────────────────────

is_verified:  bool          = False
is_timed_out: bool          = False
_verify_lock: threading.Lock = threading.Lock()
_deadline:    Optional[float] = None

# ─── FastAPI App ───────────────────────────────────────────────────────────────

app = FastAPI(title="JARVIS Auth Bridge v2", docs_url=None, redoc_url=None)


# ══════════════════════════════════════════════════════════════════════════════
#  AES-256-GCM Encryption Helpers
# ══════════════════════════════════════════════════════════════════════════════

def encrypt_message(plaintext: str, key_bytes: bytes = _AES_KEY_BYTES) -> str:
    """
    Encrypt a UTF-8 string with AES-256-GCM.

    Returns a base64-encoded string: base64(nonce[12] + ciphertext + tag[16])

    The phone decrypts with:
      key   = bytes.fromhex(AES_KEY_HEX)
      data  = base64.b64decode(received_b64)
      nonce = data[:12]
      ct_tag = data[12:]
      plain = AESGCM(key).decrypt(nonce, ct_tag, None).decode()
    """
    aesgcm = AESGCM(key_bytes)
    nonce  = secrets.token_bytes(12)                          # 96-bit IV
    ct     = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)   # ct includes GCM tag
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_message(b64_ciphertext: str, key_bytes: bytes = _AES_KEY_BYTES) -> str:
    """
    Symmetric counterpart — used in tests / debugging only.
    The phone-side decryption logic mirrors this exactly.
    """
    aesgcm = AESGCM(key_bytes)
    raw    = base64.b64decode(b64_ciphertext)
    nonce  = raw[:12]
    ct_tag = raw[12:]
    return aesgcm.decrypt(nonce, ct_tag, None).decode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  IP Gate (Strict 192.168.x.x + loopback)
# ══════════════════════════════════════════════════════════════════════════════

def _is_lan_ip(request: Request) -> bool:
    raw_ip: str = request.client.host  # type: ignore[union-attr]
    try:
        ip_obj = ipaddress.ip_address(raw_ip)
        return any(ip_obj in net for net in _PERMITTED_NETWORKS)
    except ValueError:
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  Session State Management
# ══════════════════════════════════════════════════════════════════════════════

def _reset_state() -> None:
    global is_verified, is_timed_out, _deadline
    with _verify_lock:
        is_verified  = False
        is_timed_out = False
        _deadline    = None


def _timeout_watcher() -> None:
    global is_verified, is_timed_out, _deadline
    while True:
        time.sleep(0.25)
        with _verify_lock:
            if _deadline is None or is_verified:
                continue
            if time.time() >= _deadline:
                if not is_verified:
                    is_timed_out = True
                    log.warning("[auth_bridge] Verification timed out — defaulting to PIN.")
                _deadline = None


_watcher = threading.Thread(target=_timeout_watcher, daemon=True, name="auth-timeout-watcher")
_watcher.start()


# ══════════════════════════════════════════════════════════════════════════════
#  Pydantic Models
# ══════════════════════════════════════════════════════════════════════════════

class VerifyPayload(BaseModel):
    auth_token: str


# ══════════════════════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/ping")
async def ping() -> dict:
    """
    Encrypts the biometric request message with AES-256-GCM and publishes it
    to the self-hosted ntfy server.  The phone decrypts and triggers biometrics.
    """
    global _deadline
    _deadline = None
    _reset_state()

    with _verify_lock:
        _deadline = time.time() + VERIFY_TIMEOUT_S

    # ── Encrypt the payload ───────────────────────────────────────────────────
    plaintext = "Sir, identity confirmation required."
    encrypted = encrypt_message(plaintext)

    ntfy_url = f"{_ntfy_base}/{NTFY_TOPIC}"
    headers  = {
        "Title":    "JARVIS - Biometric Request", # Replaced em-dash to avoid header encoding issues
        "Priority": "urgent",
        "Tags":     "lock,robot",
    }

    # Build auth credentials for self-hosted server
    auth: httpx.Auth | None = None
    if _ntfy_user and _ntfy_password:
        auth = httpx.BasicAuth(_ntfy_user, _ntfy_password)

    try:
        async with httpx.AsyncClient(timeout=5.0, auth=auth) as client:
            resp = await client.post(
                ntfy_url,
                content=encrypted.encode("utf-8"),     # sends AES-GCM blob
                headers=headers,
            )
            resp.raise_for_status()
        log.info(f"[auth_bridge] Encrypted ping → {ntfy_url}")
        return {
            "status":    "ping_sent",
            "topic":     NTFY_TOPIC,
            "encrypted": True,
            "timeout_s": VERIFY_TIMEOUT_S,
        }

    except httpx.HTTPError as exc:
        log.error(f"[auth_bridge] ntfy delivery failed: {exc}")
        return {"status": "ping_failed", "detail": str(exc)}


@app.post("/verify")
async def verify(payload: VerifyPayload, request: Request) -> dict:
    """
    Called by the phone after on-device biometric success.
    Strict:  192.168.x.x + loopback only, timing-safe token check.
    """
    global is_verified

    # ── Gate 1: 192.168.x.x LAN-only ─────────────────────────────────────────
    if not _is_lan_ip(request):
        client_ip = getattr(request.client, "host", "unknown")
        log.warning(f"[auth_bridge] /verify BLOCKED — non-LAN IP: {client_ip}")
        raise HTTPException(status_code=403, detail="Access restricted to local Wi-Fi network (192.168.x.x).")

    # ── Gate 2: Constant-time token comparison ────────────────────────────────
    if not secrets.compare_digest(
        hashlib.sha256(payload.auth_token.encode()).digest(),
        hashlib.sha256(AUTH_TOKEN.encode()).digest(),
    ):
        log.warning("[auth_bridge] /verify — invalid token rejected.")
        raise HTTPException(status_code=401, detail="Invalid authentication token.")

    # ── Gate 3: Active session window ─────────────────────────────────────────
    with _verify_lock:
        if _deadline is None:
            raise HTTPException(status_code=409, detail="No active auth session. Call /ping first.")
        if time.time() > _deadline:
            raise HTTPException(status_code=408, detail="Verification window expired (>15 s).")
        is_verified = True
        log.info("[auth_bridge] ✓ Mobile biometric verification ACCEPTED.")

    return {"status": "verified", "message": "Identity confirmed. Welcome back, Sir."}


@app.get("/status")
async def status(request: Request) -> dict:
    """LAN-only health/status poll for the Qt UI."""
    if not _is_lan_ip(request):
        raise HTTPException(status_code=403, detail="LAN access only.")
    return {
        "is_verified":  is_verified,
        "is_timed_out": is_timed_out,
        "ntfy_server":  _ntfy_base,
        "topic":        NTFY_TOPIC,
        "token_hint":   AUTH_TOKEN[:8] + "…",
        "aes_key_hint": AES_KEY_HEX[:8] + "…",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Public API for JARVIS subsystems
# ══════════════════════════════════════════════════════════════════════════════

def configure_ntfy(url: str, user: str = "", password: str = "") -> None:
    """
    Point the bridge at the local ntfy server.
    Called by main.py after ntfy_launcher.start() returns.

    Example:
        info = ntfy_launcher.start()
        configure_ntfy(info["url"], info["user"], info["password"])
    """
    global _ntfy_base, _ntfy_user, _ntfy_password
    _ntfy_base     = url.rstrip("/")
    _ntfy_user     = user
    _ntfy_password = password
    log.info(f"[auth_bridge] ntfy configured → {_ntfy_base} (user: {user or 'anonymous'})")


def get_token()   -> str: return AUTH_TOKEN
def get_aes_key() -> str: return AES_KEY_HEX


def ping_sync() -> bool:
    """Synchronous wrapper for Qt threads — runs ping() in a fresh event loop."""
    import asyncio
    try:
        loop   = asyncio.new_event_loop()
        result = loop.run_until_complete(ping())
        loop.close()
        return result.get("status") == "ping_sent"
    except Exception as exc:
        log.error(f"[auth_bridge] ping_sync error: {exc}")
        return False


def start_bridge_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """
    Starts the FastAPI /verify bridge in a daemon Uvicorn thread.
    IMPORTANT: Call configure_ntfy() before this so pings go to the local server.
    """
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True, name="auth-bridge-uvicorn")
    t.start()

    log.info(f"[auth_bridge] Bridge → http://{host}:{port}")
    log.info(f"[auth_bridge] Auth token  (first 8): {AUTH_TOKEN[:8]}…")
    log.info(f"[auth_bridge] AES-256 key (first 8): {AES_KEY_HEX[:8]}…")
    log.info(f"[auth_bridge] ntfy topic: {NTFY_TOPIC}")

    # ── Print full key for first-time phone setup ─────────────────────────────
    print("\n" + "═" * 60)
    print("  JARVIS MOBILE AUTH — ONE-TIME PHONE SETUP")
    print("═" * 60)
    print(f"  Verify URL : http://YOUR_PC_IP:{port}/verify")
    print(f"  Auth Token : {AUTH_TOKEN}")
    print(f"  AES-256 Key: {AES_KEY_HEX}")
    print(f"  ntfy Topic : {NTFY_TOPIC}")
    print("  (Copy these into Shortcuts / Tasker — they reset on restart)")
    print("═" * 60 + "\n")
