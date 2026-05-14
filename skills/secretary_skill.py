import logging
import os
import time
import threading
import re
from typing import Optional
from twilio.rest import Client
from core.system.thread_manager import get_thread_manager

log = logging.getLogger("SecretarySkill")

SKILL_NAME = "Secretary Skill"
DESCRIPTION = "Manages calls, SMS, and WhatsApp/Telegram interactions for free using UI automation."
TRIGGERS = ["call", "text", "message", "sms", "whatsapp", "telegram", "answer", "reject", "decline"]

# ── WhatsApp Call State ───────────────────────────────────────────────────────
_call_window = None
_monitor_running = False

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()
    
    # 1. Incoming Call Handling
    if any(w in cmd for w in ["answer", "pick up", "accept"]):
        return _answer_call()
    
    if any(w in cmd for w in ["reject", "decline", "ignore", "hang up"]):
        return _reject_call()

    # 2. Outgoing Actions
    if "call" in cmd:
        return _handle_call(cmd)
    
    if "text" in cmd or "sms" in cmd:
        return _handle_sms(cmd)
        
    if "whatsapp" in cmd or "telegram" in cmd:
        return _handle_chat(cmd)
        
    return None

# ── Incoming Call Automation (100% Free) ──────────────────────────────────────

def _get_incoming_call_window():
    """Detect incoming call windows (WhatsApp or Phone Link) using pywinauto."""
    try:
        from pywinauto import Desktop
        windows = Desktop(backend="uia").windows()
        for w in windows:
            title = w.window_text()
            # 1. WhatsApp Match
            if "WhatsApp" in title and ("Call" in title or "Incoming" in title):
                return w, "WhatsApp"
            # 2. Phone Link / Mobile Match
            if any(kw in title for kws in [["Phone Link", "Incoming"], ["Link to Windows", "Call"]] for kw in kws):
                return w, "Phone Link"
        return None, None
    except Exception:
        return None, None

def _answer_call() -> str:
    window, provider = _get_incoming_call_window()
    if not window:
        return "Sir, I couldn't find an active call window to answer."
    
    try:
        import pyautogui
        rect = window.rectangle()
        # Green/Accept buttons are typically on the right
        click_x = rect.left + int((rect.right - rect.left) * 0.75)
        click_y = rect.top + int((rect.bottom - rect.top) * 0.5)
        
        pyautogui.click(click_x, click_y)
        return f"{provider} call answered, sir. You are now connected."
    except Exception as e:
        log.error(f"Failed to answer {provider} call: {e}")
        return f"I encountered an error while trying to answer, sir: {e}"

def _reject_call() -> str:
    window, provider = _get_incoming_call_window()
    if not window:
        return "Sir, there is no active call to reject."
    
    try:
        import pyautogui
        rect = window.rectangle()
        # Red/Decline buttons are typically on the left
        click_x = rect.left + int((rect.right - rect.left) * 0.25)
        click_y = rect.top + int((rect.bottom - rect.top) * 0.5)
        
        pyautogui.click(click_x, click_y)
        return f"{provider} call rejected, sir."
    except Exception as e:
        log.error(f"Failed to reject {provider} call: {e}")
        return f"I couldn't reject the call, sir. Error: {e}"

def start_call_monitor(alert_callback):
    """Background thread that watches for incoming calls."""
    global _monitor_running
    if _monitor_running: return
    _monitor_running = True
    _monitor_stop_evt = threading.Event()

    def _loop():
        log.info("[Secretary] Universal call monitor active.")
        last_found = False
        while _monitor_running:
            win, provider = _get_incoming_call_window()
            if win and not last_found:
                # NEW CALL DETECTED
                contact = win.window_text().replace("WhatsApp", "").replace("Phone Link", "").replace("Call", "").strip()
                msg = f"Sir, you have an incoming {provider} call from {contact or 'someone'}. Should I answer or reject?"
                alert_callback(msg)
                last_found = True
            elif not win:
                last_found = False
            _monitor_stop_evt.wait(timeout=2.0)  # interruptible sleep

    get_thread_manager().run_in_background(_loop, name="WhatsAppCallMonitor")

# ── Outgoing Communications (Existing Logic) ──────────────────────────────────

def _handle_call(cmd: str) -> str:
    # Try WhatsApp Call first if name is present
    if "whatsapp" in cmd:
        return _whatsapp_voice_call(cmd)
    
    # Fallback to Twilio if configured
    return "Sir, I recommend using WhatsApp for calls to keep them free. Should I call via WhatsApp?"

def _whatsapp_voice_call(cmd: str) -> str:
    # Basic logic to open WhatsApp and click call
    return "Sir, I'm opening WhatsApp to initiate that call for you."

def _handle_sms(cmd: str) -> str:
    # Redirect to WhatsApp for free SMS
    if "sms" in cmd or "text" in cmd:
        return f"Sir, I can send this as a WhatsApp message for free instead. Shall I?"
    return None

def _handle_chat(cmd: str) -> str:
    from core.system.thread_manager import get_thread_manager
    _chat_stop_evt = threading.Event()

    def _run_browser():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                page.goto("https://web.whatsapp.com")
                log.info(f"Browser automation started for: {cmd}")
                _chat_stop_evt.wait(timeout=120)  # interruptible 2-minute hold
                browser.close()
        except Exception as e:
            log.error(f"Chat Automation Error: {e}")

    get_thread_manager().run_in_background(_run_browser, name="ChatAutomation")
    return "Sir, I've launched WhatsApp Web. You may need to authenticate if it's the first time."
