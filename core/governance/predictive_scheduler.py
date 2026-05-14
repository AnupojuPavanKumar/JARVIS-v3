# core/governance/predictive_scheduler.py
"""
Predictive resource scheduling - P5.
Workload prediction, upcoming load estimation, model pre-unloading,
adaptive model switching, proactive throttling.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, List, Tuple, Optional

log = logging.getLogger("PredictiveScheduler")


class WorkloadPrediction(Enum):
    IDLE = auto()
    LIGHT = auto()
    MODERATE = auto()
    HEAVY = auto()
    SPIKE = auto()


@dataclass
class WorkloadSnapshot:
    timestamp: float
    prediction: WorkloadPrediction
    confidence: float
    trigger: str
    recommended_actions: List[str]


PredictorFn = Callable[[], Tuple[WorkloadPrediction, str, float]]


class PredictiveScheduler:
    """
    Predictive resource scheduling.
    Analyzes workload trends to predict upcoming resource pressure.
    Proactively throttles or preloads based on prediction.
    """

    def __init__(self):
        self._history: deque = deque(maxlen=60)
        self._lock = threading.RLock()
        self._predictors: List[PredictorFn] = []
        self._recommended_actions: List[Callable] = []
        self._last_prediction = WorkloadPrediction.IDLE
        self._spike_detection_threshold = 3
        self._recent_spikes = deque(maxlen=10)

    def register_predictor(self, predictor: PredictorFn) -> None:
        self._predictors.append(predictor)

    def on_prediction(self, action: Callable) -> None:
        self._recommended_actions.append(action)

    def predict(self) -> WorkloadSnapshot:
        predictions: List[Tuple] = []
        for predictor in self._predictors:
            try:
                result = predictor()
                predictions.append(result)
            except Exception as e:
                log.debug(f"[PredictiveScheduler] Predictor error: {e}")
        if not predictions:
            predictions = [(self._last_prediction, "default", 0.5)]
        best = max(predictions, key=lambda x: x[0].value * x[2])
        prediction, trigger, confidence = best
        actions = self._get_actions_for_prediction(prediction)
        snapshot = WorkloadSnapshot(
            timestamp=time.time(), prediction=prediction,
            confidence=confidence, trigger=trigger,
            recommended_actions=actions,
        )
        with self._lock:
            self._history.append(snapshot)
            if prediction == WorkloadPrediction.SPIKE:
                self._recent_spikes.append(time.time())
            self._last_prediction = prediction
        if prediction != self._last_prediction:
            for action in self._recommended_actions:
                try:
                    action(prediction)
                except Exception as e:
                    log.warning(f"[PredictiveScheduler] Action error: {e}")
        return snapshot

    def _get_actions_for_prediction(self, prediction: WorkloadPrediction) -> List[str]:
        if prediction == WorkloadPrediction.SPIKE:
            return ["throttle_heavy_reasoning", "disable_background_agents", "switch_to_lightweight_model"]
        elif prediction == WorkloadPrediction.HEAVY:
            return ["throttle_heavy_reasoning", "limit_concurrent_actions"]
        elif prediction == WorkloadPrediction.MODERATE:
            return ["monitor_resources", "enable_adaptive_throttling"]
        elif prediction == WorkloadPrediction.LIGHT:
            return ["allow_normal_execution"]
        return ["full_throttle_if_needed"]

    def register_builtin_predictors(self) -> None:
        def resource_predictor() -> Tuple:
            try:
                from core.resource.monitor import get_resource_monitor, ResourceProfile
                mon = get_resource_monitor()
                snap = mon.current_snapshot()
                if not snap:
                    return (WorkloadPrediction.IDLE, "no_data", 0.3)
                profile = snap.profile
                if profile == ResourceProfile.CRITICAL:
                    return (WorkloadPrediction.SPIKE, "resource_critical", 0.9)
                elif profile == ResourceProfile.HEAVY:
                    return (WorkloadPrediction.HEAVY, "resource_heavy", 0.8)
                elif profile == ResourceProfile.MODERATE:
                    return (WorkloadPrediction.MODERATE, "resource_moderate", 0.6)
                elif profile == ResourceProfile.LIGHT:
                    return (WorkloadPrediction.LIGHT, "resource_light", 0.7)
                return (WorkloadPrediction.IDLE, "resource_idle", 0.5)
            except Exception:
                return (WorkloadPrediction.IDLE, "predictor_error", 0.1)

        def process_predictor() -> Tuple:
            try:
                from core.platform import get_platform
                p = get_platform()
                running = p.get_running_processes()
                high_load_names = {"minecraft", "valorant", "fortnite", "csgo", "dota", "pubg",
                                   "gta", "overwatch", "apex", "elden ring", "cyberpunk",
                                   "leagueclient", "steam", "epicgames"}
                high_load = [n for n in running.keys() if any(g in n.lower() for g in high_load_names)]
                if high_load:
                    return (WorkloadPrediction.SPIKE, f"game_detected:{high_load[0]}", 0.9)
                if len(running) > 80:
                    return (WorkloadPrediction.HEAVY, "high_process_count", 0.7)
                return (WorkloadPrediction.IDLE, "normal", 0.5)
            except Exception:
                return (WorkloadPrediction.IDLE, "predictor_error", 0.1)

        self.register_predictor(resource_predictor)
        self.register_predictor(process_predictor)

    def is_spike_trend(self) -> bool:
        with self._lock:
            recent = [t for t in self._recent_spikes if time.time() - t < 60]
            return len(recent) >= self._spike_detection_threshold

    def get_trend(self) -> List:
        with self._lock:
            return [s.prediction for s in list(self._history)[-10:]]

    def stats(self) -> dict:
        with self._lock:
            history = list(self._history)
        if not history:
            return {"prediction": "unknown", "confidence": 0, "spikes": 0}
        latest = history[-1]
        spike_count = sum(1 for s in history if s.prediction == WorkloadPrediction.SPIKE)
        trend = [s.prediction.name for s in history[-5:]]
        return {
            "prediction": latest.prediction.name,
            "confidence": latest.confidence,
            "trigger": latest.trigger,
            "spikes": spike_count,
            "spike_trend": self.is_spike_trend(),
            "trend": trend,
            "samples": len(history),
        }


_global_predictive: Optional = None
_ps_lock = threading.Lock()


def get_predictive_scheduler():
    global _global_predictive
    with _ps_lock:
        if _global_predictive is None:
            _global_predictive = PredictiveScheduler()
            _global_predictive.register_builtin_predictors()
        return _global_predictive
