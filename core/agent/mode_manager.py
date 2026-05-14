# core/mode_manager.py — JARVIS VOICE PERSONALITY MODES v2
# ──────────────────────────────────────────────────────────────────────────────
# Modes change: TTS verbosity, HUD accent colour, proactive suggestion frequency
#
# Available modes:
#   idle      — default, balanced
#   coding    — terse 1-liners, no filler
#   focus     — silent except critical alerts, no TTS for confirmations
#   gaming    — ultra-short, fastest possible responses
#   briefing  — full formal JARVIS speech, verbose
#   study     — calm, clear explanations
#   danger    — high-alert, priority overrides
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import threading
import logging

log = logging.getLogger("mode_manager")

# ── Mode profiles ─────────────────────────────────────────────────────────────
MODE_PROFILES: dict[str, dict] = {
    "idle": {
        "tts_verbosity":    "normal",    # speak full responses
        "confirmations":    True,        # speak "Done, sir" etc.
        "proactive_hz":     30,          # suggestion refresh every 30s
        "hud_accent":       "#00E5FF",   # cyan
        "greeting":         "Idle mode active.",
    },
    "coding": {
        "tts_verbosity":    "terse",     # 1-line max, no filler
        "confirmations":    False,       # silent confirmations
        "proactive_hz":     120,         # less frequent suggestions
        "hud_accent":       "#B464FF",   # purple
        "greeting":         "Coding mode. Minimal chatter.",
    },
    "focus": {
        "tts_verbosity":    "silent",    # only speak critical alerts
        "confirmations":    False,
        "proactive_hz":     300,
        "hud_accent":       "#00FF9D",   # green
        "greeting":         "Focus mode. I'll stay quiet unless critical.",
    },
    "gaming": {
        "tts_verbosity":    "ultra_terse",  # 2-3 words max
        "confirmations":    False,
        "proactive_hz":     600,
        "hud_accent":       "#FF1744",   # red
        "greeting":         "Gaming.",
    },
    "briefing": {
        "tts_verbosity":    "verbose",   # full formal speech
        "confirmations":    True,
        "proactive_hz":     15,
        "hud_accent":       "#FFD700",   # gold
        "greeting":         "Briefing mode. Standing by for your full attention, sir.",
    },
    "study": {
        "tts_verbosity":    "normal",
        "confirmations":    True,
        "proactive_hz":     60,
        "hud_accent":       "#00B8D4",   # light blue
        "greeting":         "Study mode. I'll explain things clearly.",
    },
    "danger": {
        "tts_verbosity":    "normal",
        "confirmations":    True,
        "proactive_hz":     10,
        "hud_accent":       "#FF6D00",   # orange
        "greeting":         "High-alert mode engaged.",
    },
}

# Aliases from voice commands / gestures → canonical mode names
MODE_ALIASES: dict[str, str] = {
    "idle":          "idle",
    "normal":        "idle",
    "default":       "idle",
    "coding mode":   "coding",
    "coding":        "coding",
    "code":          "coding",
    "focus mode":    "focus",
    "focus":         "focus",
    "do not disturb":"focus",
    "gaming mode":   "gaming",
    "gaming":        "gaming",
    "game":          "gaming",
    "briefing mode": "briefing",
    "briefing":      "briefing",
    "morning":       "briefing",
    "study mode":    "study",
    "study":         "study",
    "learning":      "study",
    "danger":        "danger",
    "lock":          "danger",
    "alert":         "danger",
}


class ModeManager:
    """
    Voice personality mode manager.
    Call set_mode_by_voice("coding mode") to switch cleanly.
    Observers (speech engine, HUD) can subscribe to on_mode_change.
    """

    def __init__(self):
        self.current_mode = "idle"
        self._lock        = threading.Lock()
        self._listeners   = []          # list of callable(mode_name, profile)

    # ── Current profile ─────────────────────────────────────────────────────
    @property
    def profile(self) -> dict:
        return MODE_PROFILES.get(self.current_mode, MODE_PROFILES["idle"])

    @property
    def verbosity(self) -> str:
        return self.profile["tts_verbosity"]

    @property
    def speak_confirmations(self) -> bool:
        return self.profile["confirmations"]

    @property
    def hud_accent(self) -> str:
        return self.profile["hud_accent"]

    # ── Setters ─────────────────────────────────────────────────────────────
    def set_mode(self, mode: str) -> bool:
        """Set mode by canonical name. Returns True if changed."""
        mode = mode.lower().strip()
        if mode not in MODE_PROFILES:
            return False
        with self._lock:
            if self.current_mode == mode:
                return False
            self.current_mode = mode
        log.info(f"[ModeManager] → {mode}")
        self._notify(mode)
        return True

    def set_mode_by_voice(self, phrase: str) -> str | None:
        """
        Parse a voice phrase like 'coding mode' → set mode → return greeting.
        Returns greeting string or None if no mode match.
        """
        phrase  = phrase.lower().strip()
        matched = None

        # Direct alias lookup
        for alias, canonical in MODE_ALIASES.items():
            if alias in phrase:
                matched = canonical
                break

        if not matched:
            return None

        changed = self.set_mode(matched)
        greeting = MODE_PROFILES[matched]["greeting"]
        return greeting

    def get_mode(self) -> str:
        return self.current_mode

    def list_modes(self) -> str:
        modes = list(MODE_PROFILES.keys())
        return f"Available modes: {', '.join(modes)}"

    # ── Observer pattern ─────────────────────────────────────────────────────
    def subscribe(self, callback) -> None:
        """Register a callback(mode_name, profile_dict) called on every mode change."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def _notify(self, mode: str) -> None:
        profile = MODE_PROFILES[mode]
        for cb in self._listeners:
            try:
                cb(mode, profile)
            except Exception as e:
                log.warning(f"[ModeManager] Listener error: {e}")


# Module singleton
_instance: ModeManager | None = None


def get_mode_manager() -> ModeManager:
    global _instance
    if _instance is None:
        _instance = ModeManager()
    return _instance