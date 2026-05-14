from pydantic import BaseModel
from typing import Dict, Tuple
import logging

from core.analytics.run_aggregator import get_run_aggregator

log = logging.getLogger("RegressionGuard")

class RegressionThresholds(BaseModel):
    max_divergence_rate: float = 0.05      # 5%
    min_success_rate: float = 0.90         # 90%
    max_hallucination_freq: float = 0.01   # 1%
    max_retry_variance: float = 2.0
    min_rollback_integrity: float = 0.95   # 95%

class RegressionGuard:
    """
    Phase 4: Regression Locking
    Prevents silent architectural degradation by halting validation 
    if key statistical metrics cross deterministic thresholds.
    """
    def __init__(self, thresholds: RegressionThresholds = RegressionThresholds()):
        self.thresholds = thresholds
        self.aggregator = get_run_aggregator()

    def run_regression_check(self) -> Tuple[bool, list[str]]:
        """
        Validates the longitudinal system stability against hard thresholds.
        Returns (passed: bool, violations: list).
        """
        metrics = self.aggregator.get_system_longitudinal_stability()
        violations = []

        if not metrics:
            log.info("[RegressionGuard] Not enough data for regression check.")
            return True, []

        div_rate = metrics.get("divergence_rate", 0.0)
        succ_rate = metrics.get("success_rate", 1.0)
        hal_freq = metrics.get("hallucination_frequency", 0.0)
        ret_var = metrics.get("retry_variance", 0.0)

        if div_rate > self.thresholds.max_divergence_rate:
            violations.append(f"Divergence Rate {div_rate*100:.1f}% > limit {self.thresholds.max_divergence_rate*100:.1f}%")
            
        if succ_rate < self.thresholds.min_success_rate:
            violations.append(f"Success Rate {succ_rate*100:.1f}% < limit {self.thresholds.min_success_rate*100:.1f}%")
            
        if hal_freq > self.thresholds.max_hallucination_freq:
            violations.append(f"Hallucination Freq {hal_freq*100:.1f}% > limit {self.thresholds.max_hallucination_freq*100:.1f}%")
            
        if ret_var > self.thresholds.max_retry_variance:
            violations.append(f"Retry Variance {ret_var} > limit {self.thresholds.max_retry_variance}")

        if violations:
            log.critical("\n[REGRESSION GUARD] ========================================")
            log.critical("[REGRESSION GUARD] SYSTEM VALIDATION FAILED: ARCHITECTURAL DRIFT DETECTED")
            for v in violations:
                log.critical(f"  -> {v}")
            log.critical("[REGRESSION GUARD] ========================================")
            return False, violations

        log.info("[RegressionGuard] All thresholds passed. No silent degradation detected.")
        return True, []

# ── Singleton ──────────────────────────────────────────────────────────────────
_guard_instance = None
def get_regression_guard() -> RegressionGuard:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = RegressionGuard()
    return _guard_instance
