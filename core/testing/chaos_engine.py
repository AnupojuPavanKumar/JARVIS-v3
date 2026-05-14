import logging
import asyncio
from typing import Callable, Any
from core.testing.failure_injector import get_failure_injector
from core.testing.recovery_validator import get_recovery_validator

log = logging.getLogger("ChaosEngine")

class ChaosEngine:
    """
    Phase 1: Chaos Testing Framework
    Orchestrates adversarial scenarios and monitors system survival.
    """
    def __init__(self):
        self.injector = get_failure_injector()
        
    async def run_adversarial_scenario(self, scenario_name: str, test_runner: Callable[[], Any]):
        """Runs a task while injecting specific fault profiles."""
        log.warning(f"\n[CHAOS ENGINE] ==============================================")
        log.warning(f"[CHAOS ENGINE] INITIATING SCENARIO: {scenario_name}")
        log.warning(f"[CHAOS ENGINE] ==============================================\n")
        self.injector.clear_faults()
        
        # Profile Configuration
        if scenario_name == "filesystem_chaos":
            self.injector.register_fault("filesystem", "locked_file", probability=0.3)
            self.injector.register_fault("filesystem", "corrupted_write", probability=0.2)
        elif scenario_name == "model_chaos":
            self.injector.register_fault("model", "malformed_json", probability=0.4)
            self.injector.register_fault("model", "hallucinated_tool", probability=0.3)
        elif scenario_name == "execution_chaos":
            self.injector.register_fault("execution", "subprocess_crash", probability=0.3)
            self.injector.register_fault("execution", "validator_rejection", probability=0.5)
        elif scenario_name == "task_graph_chaos":
            self.injector.register_fault("task_graph", "interrupted_execution", probability=0.2)
        
        try:
            # Execute the adversarial test
            await test_runner()
        finally:
            log.warning(f"[CHAOS ENGINE] Scenario {scenario_name} completed. Verifying recovery...")
            self.injector.clear_faults()
            self._verify_system_integrity()

    def _verify_system_integrity(self):
        """Phase 3: Recovery Validation"""
        log.info("[CHAOS ENGINE] Running Recovery Validation...")
        validator = get_recovery_validator()
        report = validator.validate_system_integrity()
        
        if report.passed:
            log.info("[CHAOS ENGINE] System recovered flawlessly. No corruption detected.")
        else:
            log.error(f"[CHAOS ENGINE] Validation Failed. {len(report.errors)} corruptions detected.")
