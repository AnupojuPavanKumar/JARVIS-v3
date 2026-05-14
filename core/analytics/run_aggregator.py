import logging
from typing import List, Dict, Any

from core.analytics.validation_store import get_validation_store
from core.analytics.statistics_engine import StatisticsEngine

log = logging.getLogger("RunAggregator")

class RunAggregator:
    """
    Phase 1: Validation Data Pipeline
    Aggregates validation runs and calculates longitudinal statistics.
    """
    def __init__(self):
        self.store = get_validation_store()

    def aggregate_benchmark(self, task_id: str) -> Dict[str, float]:
        """Calculates hard statistics for a specific benchmark task."""
        all_runs = self.store.load_all_runs()
        task_runs = [r for r in all_runs if r.get("task_id") == task_id]
        
        if not task_runs:
            log.warning(f"[Analytics] No historical data found for {task_id}")
            return {}
            
        metrics = StatisticsEngine.compute_metrics(task_runs)
        log.info(f"[Analytics] Aggregated {len(task_runs)} runs for {task_id}.")
        return metrics

    def get_system_longitudinal_stability(self) -> Dict[str, float]:
        """Calculates overarching stability metrics across ALL tasks."""
        all_runs = self.store.load_all_runs()
        if not all_runs:
            return {}
            
        return StatisticsEngine.compute_metrics(all_runs)

# ── Singleton ──────────────────────────────────────────────────────────────────
_aggregator_instance = None
def get_run_aggregator() -> RunAggregator:
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = RunAggregator()
    return _aggregator_instance
