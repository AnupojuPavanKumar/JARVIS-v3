import logging
from typing import Dict, Any

from core.evaluation.metrics import get_metrics
from core.testing.recovery_validator import get_recovery_validator

log = logging.getLogger("HealthScoring")

class SystemHealthScore:
    """
    Phase 8: System Health Scoring
    Computes a deterministic numerical score based on live metrics and tested integrity.
    """
    def calculate_score(self) -> Dict[str, Any]:
        metrics = get_metrics()
        
        # Pull actual numbers from live telemetry
        total_tasks = metrics.total_tasks_run
        # If no tasks run yet, default to perfect to avoid division by zero during boot checks
        success_rate = (metrics.successful_tasks / total_tasks) if total_tasks > 0 else 1.0
        
        # Penalties based on observed negative behaviors
        hallucination_penalty = min(1.0, (metrics.hallucinated_tool_calls * 0.15))
        retry_penalty = min(1.0, (metrics.total_retries * 0.05))
        
        # Pull empirical recovery integrity from the autonomous validator
        val_report = get_recovery_validator().validate_system_integrity()
        recovery_integrity = 1.0 if val_report.passed else max(0.0, 1.0 - (len(val_report.errors) * 0.25))
        
        # Calculate categorical sub-scores
        execution_stability = max(0.0, success_rate - retry_penalty)
        hallucination_resistance = max(0.0, 1.0 - hallucination_penalty)
        
        # Final Aggregate Score (out of 100)
        # Weights: 40% Recovery | 40% Execution | 20% Hallucination Resistance
        final_score = (
            (execution_stability * 40.0) +
            (recovery_integrity * 40.0) +
            (hallucination_resistance * 20.0)
        )
        
        report = {
            "overall_health": round(final_score, 2),
            "execution_stability": round(execution_stability * 100, 2),
            "recovery_integrity": round(recovery_integrity * 100, 2),
            "hallucination_resistance": round(hallucination_resistance * 100, 2),
            "is_production_ready": final_score >= 90.0,
            "corruptions_detected": len(val_report.errors)
        }
        
        log.warning(f"\n[HEALTH SCORE] ==============================================")
        log.warning(f"[HEALTH SCORE] JARVIS-v3 SYSTEM HEALTH RATING: {report['overall_health']}/100")
        log.warning(f"[HEALTH SCORE] ==============================================")
        log.warning(f"  -> Recovery Integrity      : {report['recovery_integrity']}%")
        log.warning(f"  -> Execution Stability     : {report['execution_stability']}%")
        log.warning(f"  -> Hallucination Resistance: {report['hallucination_resistance']}%")
        
        if report['is_production_ready']:
            log.warning("\n[HEALTH SCORE] STATUS: PRODUCTION READY (STABLE)")
        else:
            log.critical("\n[HEALTH SCORE] STATUS: UNSTABLE (REQUIRES IMMEDIATE TUNING)")
            
        return report

# ── Singleton ──────────────────────────────────────────────────────────────────
_health_scorer_instance = None
def get_health_scorer() -> SystemHealthScore:
    global _health_scorer_instance
    if _health_scorer_instance is None:
        _health_scorer_instance = SystemHealthScore()
    return _health_scorer_instance
