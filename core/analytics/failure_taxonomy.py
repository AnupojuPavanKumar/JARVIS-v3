from enum import Enum
from pydantic import BaseModel
from typing import Dict, List
import logging

log = logging.getLogger("FailureTaxonomy")

class FailureCategory(str, Enum):
    PLANNER = "planner"
    EXECUTION = "execution"
    GOVERNANCE = "governance"
    RECOVERY = "recovery"
    MEMORY = "memory"
    DAG_CONSISTENCY = "dag_consistency"
    RESOURCE_VRAM = "resource_vram"
    HALLUCINATION = "hallucination"
    TIMEOUT = "timeout"
    VALIDATION = "validation"

class FailureProfile(BaseModel):
    category: FailureCategory
    frequency: int = 0
    severity: float = 0.0 # 0.0 to 1.0
    recoverability: float = 0.0 # Percentage recovered
    recurrence_rate: float = 0.0
    cascading_impact: int = 0 # How many subsequent nodes/steps failed

class FailureTaxonomyEngine:
    """
    Phase 3: Failure Taxonomy Engine
    Deterministically categorizes and tracks the severity of system failures.
    """
    def __init__(self):
        self.profiles: Dict[FailureCategory, FailureProfile] = {
            cat: FailureProfile(category=cat) for cat in FailureCategory
        }
        self._total_failures = 0
        self._recovered_failures = {cat: 0 for cat in FailureCategory}

    def record_failure(self, category: FailureCategory, severity: float, recovered: bool, cascading: int = 0):
        """Records an isolated failure event."""
        profile = self.profiles[category]
        profile.frequency += 1
        self._total_failures += 1
        
        # Exponential moving average for severity
        profile.severity = (profile.severity * 0.8) + (severity * 0.2)
        
        if recovered:
            self._recovered_failures[category] += 1
            
        profile.recoverability = self._recovered_failures[category] / profile.frequency
        profile.cascading_impact += cascading
        profile.recurrence_rate = profile.frequency / self._total_failures

    def get_highest_instability_hotspots(self) -> List[FailureProfile]:
        """Returns categories sorted by their overall threat to the system."""
        profiles_list = list(self.profiles.values())
        # Threat score = Frequency * Severity * (1.0 - Recoverability)
        profiles_list.sort(
            key=lambda p: p.frequency * p.severity * (1.0 - p.recoverability), 
            reverse=True
        )
        return [p for p in profiles_list if p.frequency > 0]

# ── Singleton ──────────────────────────────────────────────────────────────────
_taxonomy_engine = None
def get_taxonomy_engine() -> FailureTaxonomyEngine:
    global _taxonomy_engine
    if _taxonomy_engine is None:
        _taxonomy_engine = FailureTaxonomyEngine()
    return _taxonomy_engine
