# core/briefing_engine.py — JARVIS DAILY BRIEFING ENGINE
# ──────────────────────────────────────────────────────────────────────────────
# Fires a morning briefing at a configurable time (default 09:00).
# Briefing sections:
#   1. System health (CPU/VRAM/RAM since boot, pending task queue)
#   2. Weather (wttr.in, no key required, offline-graceful)
#   3. Top 3 news headlines (DDG Instant Answer API, no key required)
#   4. Intelligence report (patterns learned, skills generated, failures pending)
#   5. Pending reminders from the scheduler
#
# Also callable manually: "good morning" / "daily briefing" / "status report"
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os, json, datetime, threading, logging
import requests
from core.engines.persona_engine import get_persona_engine

log = logging.getLogger("briefing_engine")

DEFAULT_BRIEFING_TIME = "09:00"   # 24-hr HH:MM

# ── User city config ─────────────────────────────────────────────────────────
# Priority: memory/jarvis_config.json > ENV var > hardcoded default
def _get_city() -> str:
    try:
        cfg_path = os.path.join("memory", "jarvis_config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                return json.load(f).get("city", "Hyderabad")
    except Exception:
        pass
    return os.environ.get("JARVIS_CITY", "Hyderabad")

CITY = _get_city()

# How many lines of the briefing text to pre-buffer
_MAX_BRIEFING_LINES = 30


class BriefingEngine:
    """
    Generates a rich spoken morning briefing and optionally schedules it daily.
    wire into main.py:
        briefing = BriefingEngine(speak_fn=speech.speak)
        briefing.schedule_daily("09:00")
    """

    def __init__(self, speak_fn=None, briefing_time: str = DEFAULT_BRIEFING_TIME):
        self._speak      = speak_fn          # callable(text: str)
        self._time       = briefing_time     # "HH:MM"
        self._running    = False
        self._thread     = None
        self._last_date  = None              # prevent double-fire

    # ── Public API ──────────────────────────────────────────────────────────

    def generate_briefing(self) -> str:
        """
        Build the full briefing text synchronously.
        Returns a multi-sentence string ready to speak or display.
        """
        now  = datetime.datetime.now()
        hour = now.hour
        if   hour < 12: greeting = "Good morning"
        elif hour < 17: greeting = "Good afternoon"
        else:           greeting = "Good evening"

        lines = [f"{greeting}, sir. Here is your status report for {now.strftime('%A, %B %d')}."]

        # 1. System health
        lines.append(self._system_health())

        # 2. Intelligence report (fast — no network)
        lines.append(self._intelligence_report())

        # 3. Pending failures
        lines.append(self._failure_report())

        # 4. Weather (network, graceful fail)
        weather = self._fetch_weather()
        if weather:
            lines.append(f"Weather in {CITY}: {weather}")

        # 5. News headlines (network, graceful fail)
        news = self._fetch_news()
        if news:
            lines.append("Today's top headlines: " + " | ".join(news))

        # 6. Persona & Perspective
        lines.append(self._persona_report())
        
        # 7. Pending reminders
        lines.append(self._pending_reminders())

        lines.append("That is your briefing complete, sir. How may I assist you?")

        # Filter empty lines
        text = "  ".join(l for l in lines if l and l.strip())
        return text

    def deliver(self) -> str:
        """Generate briefing and speak it if a speak_fn is wired."""
        text = self.generate_briefing()
        if self._speak:
            threading.Thread(target=self._speak, args=(text,), daemon=True).start()
        return text

    def schedule_daily(self, time_str: str = DEFAULT_BRIEFING_TIME):
        """Start a background daemon thread that delivers the briefing each day at time_str (HH:MM)."""
        self._time    = time_str
        self._running = True
        self._thread  = threading.Thread(target=self._daily_loop, daemon=True, name="briefing")
        self._thread.start()
        log.info(f"[Briefing] Daily briefing scheduled at {time_str}")

    def stop(self):
        self._running = False

    # ── Section builders ────────────────────────────────────────────────────

    def _system_health(self) -> str:
        try:
            import psutil
            cpu  = psutil.cpu_percent(interval=0.3)
            ram  = psutil.virtual_memory()
            ram_used_gb = ram.used / 1e9
            ram_pct     = ram.percent

            vram_str = ""
            try:
                import pynvml
                pynvml.nvmlInit()
                h    = pynvml.nvmlDeviceGetHandleByIndex(0)
                mem  = pynvml.nvmlDeviceGetMemoryInfo(h)
                vram_pct = round(mem.used / mem.total * 100, 1)
                vram_str = f" GPU VRAM at {vram_pct} percent."
            except Exception:
                pass

            boot = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime_hrs = round((datetime.datetime.now() - boot).seconds / 3600, 1)

            return (f"System health: CPU at {cpu:.0f} percent. "
                    f"RAM at {ram_pct:.0f} percent ({ram_used_gb:.1f} GB used).{vram_str} "
                    f"Uptime {uptime_hrs} hours.")
        except Exception as e:
            return f"System health unavailable: {e}"

    def _intelligence_report(self) -> str:
        try:
            from core.memory.pattern_memory import get_pattern_memory
            pm    = get_pattern_memory()
            count = pm._collection.count() if pm._chroma_ok and pm._collection else "?"

            from core.system.plugin_manager import get_plugin_manager
            n_skills = get_plugin_manager().skill_count()

            facts = get_persona_engine()._persona.get("facts", [])
            n_facts = len(facts)

            return (f"Intelligence: {count} patterns in memory. "
                    f"{n_skills} skills loaded. "
                    f"I have recorded {n_facts} specific facts about your workflow, sir.")
        except Exception:
            return ""

    def _persona_report(self) -> str:
        try:
            persona = get_persona_engine()
            prefs = persona._persona.get("preferences", {})
            facts = persona._persona.get("facts", [])
            
            if not facts: return ""
            
            # Select a random recent fact to show perspective
            import random
            recent_fact = random.choice(facts[-5:])
            return f"Strategic Insight: {recent_fact}."
        except Exception:
            return ""

    def _failure_report(self) -> str:
        try:
            path = os.path.join("memory", "agent_failures.jsonl")
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                n = sum(1 for _ in f)
            if n == 0:
                return "No unresolved commands in the auto-heal queue."
            return (f"Attention: {n} unresolved command"
                    f"{'s' if n != 1 else ''} in the auto-heal queue. "
                    "Say 'auto heal' to generate new skills for them.")
        except Exception:
            return ""

    def _fetch_weather(self, timeout: int = 4) -> str:
        """wttr.in JSON -- no API key, offline-graceful."""
        city = _get_city()   # re-read in case config changed at runtime
        try:
            r = requests.get(
                f"https://wttr.in/{city}?format=j1",
                timeout=timeout,
                headers={"User-Agent": "JARVIS/3.0"}
            )
            if r.status_code == 200 and "location not found" not in r.text.lower():
                data  = r.json()
                cur   = data["current_condition"][0]
                desc  = cur["weatherDesc"][0]["value"]
                temp_c = cur["temp_C"]
                feel_c = cur["FeelsLikeC"]
                return f"{desc}, {temp_c}degC, feels like {feel_c}degC."
        except Exception:
            pass
        return ""

    def _fetch_news(self, timeout: int = 5) -> list[str]:
        """DuckDuckGo Instant Answer API — no key, rate-limit tolerant."""
        try:
            r = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": "today news", "format": "json", "no_redirect": 1, "skip_disambig": 1},
                timeout=timeout,
                headers={"User-Agent": "JARVIS/3.0"}
            )
            if r.status_code == 200:
                data     = r.json()
                topics   = data.get("RelatedTopics", [])
                headlines = []
                for t in topics[:5]:
                    text = t.get("Text", "")
                    if text and len(text) > 20:
                        headlines.append(text[:100])
                    if len(headlines) >= 3:
                        break
                return headlines
        except Exception:
            pass
        return []

    def _pending_reminders(self) -> str:
        try:
            from core.agent.scheduler import get_scheduler
            sched   = get_scheduler()
            listing = sched.list_reminders()
            if "no" in listing.lower() or "none" in listing.lower():
                return "No pending reminders."
            return f"Pending reminders: {listing}"
        except Exception:
            return ""

    # ── Daily scheduler loop ────────────────────────────────────────────────

    def _daily_loop(self):
        log.info(f"[Briefing] Daemon started, fires at {self._time} daily.")
        import time
        while self._running:
            now = datetime.datetime.now()
            today = now.date()
            fire_h, fire_m = map(int, self._time.split(":"))
            fire_dt = now.replace(hour=fire_h, minute=fire_m, second=0, microsecond=0)

            # If we're past today's time, schedule for tomorrow
            if now >= fire_dt:
                fire_dt += datetime.timedelta(days=1)

            wait_s = (fire_dt - now).total_seconds()
            log.info(f"[Briefing] Next briefing in {wait_s/3600:.1f}h at {fire_dt}")

            # Sleep in 60s chunks so stop() can interrupt quickly
            slept = 0
            while self._running and slept < wait_s:
                time.sleep(min(60, wait_s - slept))
                slept += 60

            if not self._running:
                break

            # Only fire once per day
            if self._last_date != fire_dt.date():
                self._last_date = fire_dt.date()
                log.info("[Briefing] Firing daily briefing.")
                self.deliver()


# Module singleton
_instance: BriefingEngine | None = None


def get_briefing_engine() -> BriefingEngine:
    global _instance
    if _instance is None:
        _instance = BriefingEngine()
    return _instance
