# core/system/lifecycle_narratives.py — JARVIS LIFECYCLE NARRATIVE DIAGNOSTICS
"""
Human-readable lifecycle summaries.

Instead of raw audit trails, produces narrative explanations:
  "Wake subsystem restarted after microphone contention timeout."
  "Voice capability degraded — Vosk model unavailable."
  "Runtime stable for 4.2 hours with no degraded events."

Narratives are generated from audit trails, readiness states,
capability validation results, and watchdog events.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from core.system.readiness_state import get_readiness_tracker
from core.system.runtime_lifecycle import get_runtime_lifecycle


@dataclass
class NarrativeLine:
    timestamp: float
    severity: str  # INFO | WARN | ERROR | RECOVERY | SUMMARY
    text: str


class LifecycleNarratives:
    """
    Generates human-readable lifecycle narratives from system diagnostics.

    Methods:
      generate()   → full narrative as list of NarrativeLine
      summary()   → one-line runtime status
      incidents() → recent failure/recovery incidents
      timeline() → compressed boot → current timeline
    """

    _instance: Optional[LifecycleNarratives] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def generate(self) -> list[NarrativeLine]:
        """Generate full narrative from all diagnostic sources."""
        lines: list[NarrativeLine] = []

        lines += self._boot_narrative()
        lines += self._readiness_narrative()
        lines += self._capability_narrative()
        lines += self._pressure_narrative()
        lines += self._mic_narrative()
        lines += self._shutdown_narrative()
        lines += self._domain_confidence_narrative()
        lines += self._meta_stability_narrative()
        lines += self._predictive_insights()
        lines += self._summary_line()

        return sorted(lines, key=lambda l: l.timestamp)

    def summary(self) -> str:
        """One-line runtime status."""
        lc = get_runtime_lifecycle()
        rt = get_readiness_tracker()

        state = lc.state.name
        caps = rt.get_capabilities()
        ready = [k for k, v in caps.items() if v]
        degraded = rt.get_degraded()
        failed = rt.get_failed()

        idle_dur = lc.idle_duration_sec()
        idle_str = f"idle {idle_dur:.0f}s" if idle_dur > 5 else "active"

        parts = [f"state={state}", f"{idle_str}"]
        if ready:
            parts.append(f"ready={','.join(ready)}")
        if degraded:
            parts.append(f"degraded={len(degraded)}")
        if failed:
            parts.append(f"failed={len(failed)}")

        return " | ".join(parts)

    def incidents(self) -> list[NarrativeLine]:
        """Recent failure and recovery incidents."""
        lines: list[NarrativeLine] = []
        try:
            rt = get_readiness_tracker()
            for sub in rt.get_failed():
                state = rt.get_state(sub)
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="ERROR",
                    text=f"Subsystem '{sub}' failed",
                ))
        except Exception:
            pass

        try:
            wd_lines = self._watchdog_incidents()
            lines += wd_lines
        except Exception:
            pass

        return sorted(lines, key=lambda l: l.timestamp, reverse=True)

    def timeline(self) -> list[NarrativeLine]:
        """Compressed boot → current timeline."""
        lines: list[NarrativeLine] = []
        now = time.time()

        try:
            rt = get_readiness_tracker()
            audit = rt.get_audit(limit=100)
            boot_start = audit[0]["ts"] if audit else now
            boot_duration = sum(
                rt.init_duration_ms(s) or 0
                for s in rt.get_all() if rt.is_ready(s)
            ) / 1000

            lines.append(NarrativeLine(
                timestamp=boot_start,
                severity="INFO",
                text=f"Booted — {boot_duration:.1f}s total initialization",
            ))

            for ev in audit:
                if ev["event"] == "READY":
                    dur = ev.get("duration_ms", 0)
                    lines.append(NarrativeLine(
                        timestamp=ev["ts"],
                        severity="INFO",
                        text=f"  + {ev['subsystem']}: ready in {dur:.0f}ms" if dur else f"  + {ev['subsystem']}: ready",
                    ))
                elif ev["event"] == "FAILED":
                    lines.append(NarrativeLine(
                        timestamp=ev["ts"],
                        severity="ERROR",
                        text=f"  ! {ev['subsystem']}: FAILED — {ev.get('reason', 'unknown')}",
                    ))
                elif ev["event"] == "DEGRADED":
                    lines.append(NarrativeLine(
                        timestamp=ev["ts"],
                        severity="WARN",
                        text=f"  ~ {ev['subsystem']}: degraded — {ev.get('reason', '')}",
                    ))

        except Exception as e:
            lines.append(NarrativeLine(
                timestamp=now, severity="WARN",
                text=f"Timeline unavailable: {e}",
            ))

        return sorted(lines, key=lambda l: l.timestamp)

    def _boot_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.boot_orchestrator import get_boot_orchestrator
            orch = get_boot_orchestrator()
            durations = orch.get_durations()
            total = sum(durations.values())
            for phase, dur in sorted(durations.items()):
                lines.append(NarrativeLine(
                    timestamp=time.time() - total + dur,
                    severity="INFO",
                    text=f"Phase {phase} completed in {dur:.0f}ms",
                ))
        except Exception:
            pass
        return lines

    def _readiness_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            rt = get_readiness_tracker()
            summary = rt.get_summary()
            if summary["degraded"]:
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="WARN",
                    text=f"{summary['degraded']} subsystems degraded: {', '.join(rt.get_degraded())}",
                ))
            if summary["failed"]:
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="ERROR",
                    text=f"{summary['failed']} subsystems failed: {', '.join(rt.get_failed())}",
                ))
            lines.append(NarrativeLine(
                timestamp=time.time(),
                severity="SUMMARY",
                text=f"Readiness: {summary['ready']}/{summary['total']} ready ({summary['pct']}%)",
            ))
        except Exception:
            pass
        return lines

    def _capability_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.capability_validator import get_capability_validator
            cv = get_capability_validator()
            summary = cv.get_summary()
            for cap, health in cv.get_all().items():
                if health.name != "HEALTHY":
                    lines.append(NarrativeLine(
                        timestamp=time.time(),
                        severity="WARN" if health.name == "STALE" else "ERROR",
                        text=f"Capability '{cap}' is {health.name.lower()}",
                    ))
        except Exception:
            pass
        return lines

    def _pressure_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.health_pressure_governor import get_health_pressure_governor
            gov = get_health_pressure_governor()
            level = gov.level.name
            suppressed = gov.suppressed_systems
            if level != "NOMINAL":
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="WARN",
                    text=f"Pressure level: {level} — mitigations active: {', '.join(suppressed) if suppressed else 'none'}",
                ))
        except Exception:
            pass
        return lines

    def _mic_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.microphone_manager import get_microphone_manager
            mm = get_microphone_manager()
            diag = mm.diagnostics()
            if diag["dead"]:
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="ERROR",
                    text=f"Microphone DEAD — {diag['recovery_count']} recovery attempts",
                ))
            elif diag["owner"]:
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="INFO",
                    text=f"Microphone held by {diag['owner']} ({diag['mode']}) for {diag['held_sec']:.0f}s",
                ))
        except Exception:
            pass
        return lines

    def _shutdown_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.shutdown_escalation import get_shutdown_escalation
            se = get_shutdown_escalation()
            diag = se.diagnostics()
            if diag["results"]:
                last = diag["results"][-1]
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="INFO" if diag["is_clean"] else "ERROR",
                    text=f"Shutdown: {last['stage']} — {len(diag['results'])} stages — "
                         f"errors={last.get('errors', {}) or 'none'} — "
                         f"escalated={last.get('escalated_to', 'none')}",
                ))
        except Exception:
            pass
        return lines

    def _watchdog_incidents(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.subsystem_watchdog import get_watchdog
            wd = get_watchdog()
            for name, count in wd._hung_count.items():
                if count > 0:
                    lines.append(NarrativeLine(
                        timestamp=time.time(),
                        severity="WARN",
                        text=f"Subsystem '{name}' timed out {count} time(s)",
                    ))
        except Exception:
            pass
        return lines

    def _domain_confidence_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.domain_confidence import get_domain_confidence, DomainLevel
            dc = get_domain_confidence()
            for domain_name, level_name in dc.get_all_levels().items():
                if level_name in ("UNCERTAIN", "LOW"):
                    score = dc.get_all_scores().get(domain_name, 0)
                    lines.append(NarrativeLine(
                        timestamp=time.time(),
                        severity="WARN" if level_name == "UNCERTAIN" else "ERROR",
                        text=f"Domain '{domain_name}' confidence {level_name} (score={score:.0f})",
                    ))
        except Exception:
            pass
        return lines

    def _meta_stability_narrative(self) -> list[NarrativeLine]:
        lines: list[NarrativeLine] = []
        try:
            from core.system.meta_stability_guard import get_meta_stability_guard
            guard = get_meta_stability_guard()
            diag = guard.get_diagnostics()
            if diag["is_stabilizing"]:
                lines.append(NarrativeLine(
                    timestamp=time.time(),
                    severity="WARN",
                    text=f"Meta-stability freeze active — "
                         f"{diag['stabilization_remaining']:.0f}s remaining "
                         f"({diag['freeze_count']} total freezes)",
                ))
            for ev in diag.get("recent_stability_events", []):
                lines.append(NarrativeLine(
                    timestamp=ev["ts"],
                    severity="ERROR",
                    text=f"Stability event [{ev['type']}]: {ev['reason']}",
                ))
        except Exception:
            pass
        return lines

    def _predictive_insights(self) -> list[NarrativeLine]:
        """Generate operational predictions from repeating patterns."""
        lines: list[NarrativeLine] = []
        try:
            from core.system.readiness_state import get_readiness_tracker
            rt = get_readiness_tracker()
            audit = rt.get_audit(limit=200)

            # Count events per subsystem
            fail_counts: dict[str, int] = {}
            degraded_counts: dict[str, int] = {}
            for ev in audit:
                sub = ev.get("subsystem", "")
                if ev.get("event") == "FAILED":
                    fail_counts[sub] = fail_counts.get(sub, 0) + 1
                elif ev.get("event") == "DEGRADED":
                    degraded_counts[sub] = degraded_counts.get(sub, 0) + 1

            # Repeated audio failures → suggest wake-word tuning
            audio_subs = {"wake_word", "voice_stt", "voice_worker", "voice_interrupt"}
            audio_fails = sum(fail_counts.get(s, 0) + degraded_counts.get(s, 0)
                             for s in audio_subs)
            if audio_fails >= 3:
                lines.append(NarrativeLine(
                    timestamp=time.time(), severity="WARN",
                    text=f"Predictive: Repeated audio subsystem failures ({audio_fails}x) — "
                         "consider reducing wake-word sensitivity or checking microphone hardware.",
                ))

            # Ollama repeatedly failing → suggest resource limits
            ollama_fails = fail_counts.get("ollama_manager", 0) + degraded_counts.get("ollama_manager", 0)
            if ollama_fails >= 2:
                lines.append(NarrativeLine(
                    timestamp=time.time(), severity="WARN",
                    text=f"Predictive: Ollama degraded {ollama_fails}x — "
                         "VRAM pressure or model too large for available memory.",
                ))

            # Memory subsystems degrading → session continuity at risk
            mem_subs = {"checkpoint_manager", "layered_memory", "session_continuity"}
            mem_fails = sum(fail_counts.get(s, 0) for s in mem_subs)
            if mem_fails >= 2:
                lines.append(NarrativeLine(
                    timestamp=time.time(), severity="WARN",
                    text=f"Predictive: Memory subsystem failures ({mem_fails}x) — "
                         "session continuity and checkpoint recovery may be unreliable.",
                ))

            # High recovery churn → likely a structural issue
            try:
                from core.system.recovery_orchestrator import get_recovery_orchestrator
                ro = get_recovery_orchestrator()
                diag = ro.get_diagnostics()
                high_fail = [
                    name for name, info in diag["entries"].items()
                    if info["total_failures"] >= 3
                ]
                if high_fail:
                    lines.append(NarrativeLine(
                        timestamp=time.time(), severity="ERROR",
                        text=f"Predictive: Persistent failures in {high_fail} — "
                             "structural issue likely, not transient. Manual review recommended.",
                    ))
            except Exception:
                pass

        except Exception:
            pass
        return lines

    def _summary_line(self) -> list[NarrativeLine]:
        return [NarrativeLine(
            timestamp=time.time(),
            severity="SUMMARY",
            text=self.summary(),
        )]


_instance: Optional[LifecycleNarratives] = None
_narr_lock = threading.Lock()


def get_lifecycle_narratives() -> LifecycleNarratives:
    global _instance
    with _narr_lock:
        if _instance is None:
            _instance = LifecycleNarratives()
        return _instance
