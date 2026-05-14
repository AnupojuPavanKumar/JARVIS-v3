# core/companion/behavior_drift.py — JARVIS BEHAVIOR DRIFT PREVENTION
"""
Tracks behavioral stability over time. Prevents:
  - personality drift (JARVIS becoming more chatty/assertive over time)
  - verbosity creep (max_sentences slowly increasing across sessions)
  - suggestion creep (proactive suggestions increasing without reason)
  - interaction inflation (responses getting longer/slower over time)

Wire into: jarvis_brain init + periodic stability checks + on session load.
"""
from __future__ import annotations

import threading
import time
import os
import json
from dataclasses import dataclass, asdict
from typing import Optional

_PATH = "memory/behavior_baseline.json"
_MAX_SESSION_BUCKETS = 10


@dataclass
class SessionMetrics:
    session_id: str
    timestamp: float
    avg_response_length: float
    avg_sentence_count: float
    suggestion_count: int
    command_count: int
    speech_count: int
    proactive_rate: float


class BehaviorDrift:
    """
    Tracks JARVIS behavioral metrics over time and detects drift.
    Baseline established from first 5 sessions. Deviation flagged if >20%.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._sessions: list[SessionMetrics] = []
        self._baseline: Optional[SessionMetrics] = None
        self._current_session_metrics: Optional[SessionMetrics] = None
        self._load()

    def _load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH, "r") as f:
                    data = json.load(f)
                    self._sessions = [SessionMetrics(**s) for s in data.get("sessions", [])]
                    if data.get("baseline"):
                        self._baseline = SessionMetrics(**data["baseline"])
                    print(f"[BehaviorDrift] Loaded {len(self._sessions)} sessions, "
                          f"baseline: {'yes' if self._baseline else 'no'}")
        except Exception as e:
            print(f"[BehaviorDrift] Load error: {e}")

    def save(self):
        with self._lock:
            try:
                os.makedirs("memory", exist_ok=True)
                data = {
                    "sessions": [asdict(s) for s in self._sessions],
                    "baseline": asdict(self._baseline) if self._baseline else None,
                }
                with open(_PATH, "w") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[BehaviorDrift] Save error: {e}")

    def start_session(self, session_id: str):
        """Begin tracking a new session."""
        with self._lock:
            self._current_session_metrics = SessionMetrics(
                session_id=session_id,
                timestamp=time.time(),
                avg_response_length=0.0,
                avg_sentence_count=0.0,
                suggestion_count=0,
                command_count=0,
                speech_count=0,
                proactive_rate=0.0,
            )

    def record_response(self, response_length: int, sentence_count: int):
        """Record a response for the current session."""
        with self._lock:
            if self._current_session_metrics is None:
                return
            m = self._current_session_metrics
            n = m.command_count
            m.avg_response_length = (m.avg_response_length * n + response_length) / (n + 1)
            m.avg_sentence_count = (m.avg_sentence_count * n + sentence_count) / (n + 1)

    def record_command(self):
        with self._lock:
            if self._current_session_metrics:
                self._current_session_metrics.command_count += 1

    def record_speech(self):
        with self._lock:
            if self._current_session_metrics:
                self._current_session_metrics.speech_count += 1

    def record_suggestion(self):
        with self._lock:
            if self._current_session_metrics:
                self._current_session_metrics.suggestion_count += 1

    def end_session(self):
        """Finalize and archive the current session."""
        with self._lock:
            if self._current_session_metrics is None:
                return
            m = self._current_session_metrics
            if m.command_count > 0:
                m.proactive_rate = m.suggestion_count / m.command_count
            self._sessions.append(m)
            if len(self._sessions) > _MAX_SESSION_BUCKETS:
                self._sessions = self._sessions[-_MAX_SESSION_BUCKETS:]
            if self._baseline is None and len(self._sessions) >= 3:
                self._establish_baseline()
            self._current_session_metrics = None

    def _establish_baseline(self):
        recent = self._sessions[-5:]
        self._baseline = SessionMetrics(
            session_id="baseline",
            timestamp=time.time(),
            avg_response_length=sum(s.avg_response_length for s in recent) / len(recent),
            avg_sentence_count=sum(s.avg_sentence_count for s in recent) / len(recent),
            suggestion_count=sum(s.suggestion_count for s in recent) // len(recent),
            command_count=sum(s.command_count for s in recent) // len(recent),
            speech_count=sum(s.speech_count for s in recent) // len(recent),
            proactive_rate=sum(s.proactive_rate for s in recent) / len(recent),
        )
        print(f"[BehaviorDrift] Baseline established: "
              f"sentences={self._baseline.avg_sentence_count:.1f}, "
              f"proactive={self._baseline.proactive_rate:.2f}")

    def get_drift(self) -> dict:
        """Return drift metrics if baseline exists. Empty dict if stable."""
        with self._lock:
            if self._baseline is None or self._current_session_metrics is None:
                return {}
            current = self._current_session_metrics
            baseline = self._baseline

            drift = {}
            for field_name in ["avg_sentence_count", "avg_response_length",
                               "proactive_rate", "suggestion_count"]:
                base_val = getattr(baseline, field_name, 0)
                cur_val = getattr(current, field_name, 0)
                if base_val > 0:
                    change = (cur_val - base_val) / base_val
                    drift[field_name] = round(change, 3)

            return drift

    def get_stability(self) -> bool:
        """Is current behavior within 20% of baseline?"""
        drift = self.get_drift()
        if not drift:
            return True
        return all(abs(v) <= 0.2 for v in drift.values())

    def get_correction(self) -> dict:
        """
        Return correction multipliers to bring behavior back to baseline.
        Keys: sentence_mult, length_mult, proactive_mult
        """
        drift = self.get_drift()
        if not drift:
            return {"sentence_mult": 1.0, "length_mult": 1.0, "proactive_mult": 1.0}

        return {
            "sentence_mult": max(0.7, 1.0 - drift.get("avg_sentence_count", 0) * 0.5),
            "length_mult": max(0.7, 1.0 - drift.get("avg_response_length", 0) * 0.5),
            "proactive_mult": max(0.5, 1.0 - drift.get("proactive_rate", 0) * 0.5),
        }

    def get_state(self) -> dict:
        with self._lock:
            return {
                "baseline_established": self._baseline is not None,
                "current_session_commands": (
                    self._current_session_metrics.command_count
                    if self._current_session_metrics else 0
                ),
                "sessions_tracked": len(self._sessions),
                "is_stable": self.get_stability(),
                "drift": self.get_drift(),
            }


_instance: Optional[BehaviorDrift] = None
_lock = threading.Lock()


def get_behavior_drift() -> BehaviorDrift:
    global _instance
    with _lock:
        if _instance is None:
            _instance = BehaviorDrift()
        return _instance