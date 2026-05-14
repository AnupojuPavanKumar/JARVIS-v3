import logging
import random
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

log = logging.getLogger("FailureInjector")

class Fault(BaseModel):
    fault_id: str
    category: str # "filesystem", "model", "execution", "resource", "task_graph"
    fault_type: str
    probability: float
    is_active: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FailureInjector:
    """
    Phase 2: Failure Injection
    Provides deterministic fault injection across the JARVIS architecture.
    """
    def __init__(self):
        self._faults: Dict[str, Fault] = {}
        
    def register_fault(self, category: str, fault_type: str, probability: float = 1.0, metadata: dict = None) -> str:
        fault_id = f"fault_{category}_{fault_type}"
        self._faults[fault_id] = Fault(
            fault_id=fault_id,
            category=category,
            fault_type=fault_type,
            probability=probability,
            is_active=True,
            metadata=metadata or {}
        )
        log.warning(f"[CHAOS] Registered Fault: {fault_id} (prob={probability})")
        return fault_id
        
    def clear_faults(self):
        self._faults.clear()
        log.info("[CHAOS] All faults cleared.")
        
    def should_inject(self, category: str, fault_type: str) -> bool:
        """Determines if a fault should be injected right now based on active faults and probability."""
        fault_id = f"fault_{category}_{fault_type}"
        if fault_id in self._faults and self._faults[fault_id].is_active:
            if random.random() <= self._faults[fault_id].probability:
                log.critical(f"[CHAOS] INJECTING FAULT: {fault_id}")
                return True
        return False

# ── Singleton ──────────────────────────────────────────────────────────────────
_failure_injector_instance: Optional[FailureInjector] = None

def get_failure_injector() -> FailureInjector:
    global _failure_injector_instance
    if _failure_injector_instance is None:
        _failure_injector_instance = FailureInjector()
    return _failure_injector_instance
