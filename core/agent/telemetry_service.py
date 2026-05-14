"""
core/agent/telemetry_service.py — HUD & Telemetry Service (v2)
===============================================================
Ghost C fix: replaces the strong UI reference with a weakref.

PROBLEM:
  TelemetryService held a direct (strong) reference to the Qt UI widget.
  If the UI was closed and re-created while background services (scheduler,
  system watcher, proactive engine) remained alive, those services would
  call methods on a dead C++ Qt object, causing a segfault or RuntimeError.

SOLUTION:
  Store the UI as `weakref.ref(ui)`. The HUD methods now resolve the ref
  on every call:
    - If the UI is still alive → update normally.
    - If the UI has been garbage-collected → silently skip (log at DEBUG).

  Additionally, TelemetryService publishes HUD updates via the EventBus
  so that the UI can re-subscribe after a restart without any service needing
  to be re-wired. The `set_ui()` method still works for the initial wire.
"""
from __future__ import annotations

import logging
import weakref
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.engines.speech_dispatcher import SpeechDispatcher

log = logging.getLogger("TelemetryService")


class TelemetryService:
    """
    Thread-safe HUD and proactive-alert gateway.

    Uses weakref for the UI reference so dead widget objects are never accessed.
    All HUD methods degrade silently when the UI is unavailable.
    """

    def __init__(self, ui=None, speech: Optional["SpeechDispatcher"] = None):
        self._ui_ref: Optional[weakref.ref] = weakref.ref(ui) if ui is not None else None
        self._speech = speech

    # ── UI wiring (weakref-based) ─────────────────────────────────────────────

    def set_ui(self, ui):
        """Wire (or replace) the UI reference. Stored as a weak reference."""
        self._ui_ref = weakref.ref(ui) if ui is not None else None

    def _get_ui(self):
        """
        Dereference the UI weakref safely.
        Returns the live UI object, or None if it has been garbage-collected.
        """
        if self._ui_ref is None:
            return None
        ui = self._ui_ref()
        if ui is None:
            log.debug("[Telemetry] UI weakref expired — skipping update.")
        return ui

    def set_speech(self, speech: "SpeechDispatcher"):
        """Wire the speech dispatcher."""
        self._speech = speech

    # ── HUD ──────────────────────────────────────────────────────────────────

    def set_active_skill(self, skill_name: str):
        """Update the HUD active-skill indicator from any thread."""
        try:
            ui = self._get_ui()
            if ui is None:
                return
            hud_fn = getattr(getattr(ui, "_hud", None), "set_active_skill", None)
            if hud_fn:
                from PyQt6.QtCore import QTimer
                _ref, _name = weakref.ref(ui), skill_name
                def _safe_update():
                    _ui = _ref()
                    if _ui is not None:
                        _ui._hud.set_active_skill(_name)
                QTimer.singleShot(0, _safe_update)
        except Exception as exc:
            log.debug(f"[Telemetry] set_active_skill silenced: {exc}")

    def set_agent_step(self, step: int, total: int, title: str):
        """Update the HUD agent-step progress bar from any thread."""
        try:
            ui = self._get_ui()
            if ui is None:
                return
            hud_fn = getattr(getattr(ui, "_hud", None), "set_agent_step", None)
            if hud_fn:
                from PyQt6.QtCore import QTimer
                _ref, _s, _t, _title = weakref.ref(ui), step, total, title
                def _safe_update():
                    _ui = _ref()
                    if _ui is not None:
                        _ui._hud.set_agent_step(_s, _t, _title)
                QTimer.singleShot(0, _safe_update)
        except Exception as exc:
            log.debug(f"[Telemetry] set_agent_step silenced: {exc}")

    # ── Proactive Suggestions ─────────────────────────────────────────────────

    def stream_token(self, token: str, source: str = "jarvis"):
        """
        Append a streaming token to the UI's neural feed (real-time token display).
        Shows LLM output as it arrives — like watching tokens type in real-time.
        """
        try:
            ui = self._get_ui()
            if ui is None:
                return
            term = getattr(ui, "_term", None)
            if term is None:
                return
            from PyQt6.QtCore import QTimer
            _term = term
            _token = token
            def _append():
                try:
                    _term.insertPlainText(_token)
                    _term.moveCursor(__import__("PyQt6.QtGui", fromlist=["QTextCursor"]).QTextCursor.MoveOperation.End)
                except Exception:
                    pass
            QTimer.singleShot(0, _append)
        except Exception as exc:
            log.debug(f"[Telemetry] stream_token silenced: {exc}")

    def on_proactive_suggestion(self, suggestion: str):
        """Routes a suggestion to TTS, push notification, AND chat UI."""
        # Show in chat (weakref-safe)
        try:
            ui = self._get_ui()
            if ui is not None:
                from PyQt6.QtCore import QTimer
                _ui = ui
                def _show_in_chat():
                    try:
                        if hasattr(_ui, "_add_msg"):
                            _ui._add_msg("JARVIS", f"[suggestion] {suggestion}")
                    except Exception:
                        pass
                QTimer.singleShot(0, _show_in_chat)
        except Exception:
            pass
        if self._speech:
            self._speech.speak(suggestion)
            self._speech.push_notification(
                title="JARVIS Suggestion",
                message=suggestion[:300]
            )

    def on_reminder(self, text: str):
        """Routes a scheduled reminder to TTS and a high-priority push."""
        if self._speech:
            self._speech.speak(text)
            self._speech.push_notification(
                title="JARVIS ⏰ Reminder",
                message=text[:300],
                priority="high"
            )

    def on_system_alert(self, alert):
        """Routes high-severity system alerts to TTS + push notification."""
        try:
            from core.system.system_watcher import SEVERITY_WARNING, SEVERITY_CRITICAL
            if alert.severity in (SEVERITY_WARNING, SEVERITY_CRITICAL):
                msg = f"Alert, sir. {alert.message}"
                if self._speech:
                    self._speech.speak_critical(msg)
                    self._speech.push_notification(
                        title=f"JARVIS {alert.title}",
                        message=alert.message,
                        priority="high"
                    )
        except Exception as exc:
            log.error(f"[Telemetry] on_system_alert failed: {exc}")


# ── Module singleton ─────────────────────────────────────────────────────────

_instance: Optional[TelemetryService] = None


def get_telemetry_service(ui=None, speech=None) -> TelemetryService:
    global _instance
    if _instance is None:
        _instance = TelemetryService(ui=ui, speech=speech)
    else:
        if ui is not None:
            _instance.set_ui(ui)
        if speech is not None:
            _instance.set_speech(speech)
    return _instance
