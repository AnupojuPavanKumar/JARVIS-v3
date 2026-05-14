import os
import json
import logging
from typing import Dict, Any, List

log = logging.getLogger("ValidationStore")

class ValidationStore:
    """
    Phase 1: Validation Data Pipeline
    Persists benchmark runs, chaos testing outcomes, and recovery metrics.
    Data must survive crashes and interrupted sessions.
    """
    def __init__(self, data_dir="memory/analytics"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "validation_runs.jsonl")

    def save_run(self, run_data: Dict[str, Any]):
        """Persist a single benchmark or chaos test run."""
        try:
            with open(self.db_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(run_data) + "\n")
        except Exception as e:
            log.error(f"[ValidationStore] Failed to save validation run: {e}")

    def load_all_runs(self) -> List[Dict[str, Any]]:
        """Load all historical validation runs for statistical analysis."""
        runs = []
        if os.path.exists(self.db_path):
            with open(self.db_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        runs.append(json.loads(line))
                    except json.JSONDecodeError:
                        log.warning("[ValidationStore] Corrupted line in validation store.")
        return runs

# ── Singleton ──────────────────────────────────────────────────────────────────
_validation_store_instance = None
def get_validation_store() -> ValidationStore:
    global _validation_store_instance
    if _validation_store_instance is None:
        _validation_store_instance = ValidationStore()
    return _validation_store_instance
