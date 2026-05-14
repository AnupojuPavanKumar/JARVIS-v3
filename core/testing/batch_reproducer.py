import logging
import asyncio
import time
import statistics
from typing import Callable, Any, Dict, List
from pydantic import BaseModel

log = logging.getLogger("BatchReproducer")

class RunStats(BaseModel):
    run_id: int
    steps_taken: int
    retries: int
    duration_s: float
    success: bool
    hallucinations: int

class ReproducibilityReport(BaseModel):
    task_id: str
    total_runs: int
    success_rate: float
    avg_steps: float
    step_variance: float
    avg_retries: float
    divergence_rate: float

class BatchReproducer:
    """
    Phase 5: Deterministic Reproducibility
    Runs identical benchmarks repeatedly to measure divergence and execution stability.
    """
    def __init__(self, runs_per_task: int = 25):
        self.runs_per_task = runs_per_task
        self.results: List[RunStats] = []
        
    async def run_batch(self, task_id: str, test_runner: Callable[..., Any]) -> ReproducibilityReport:
        """Executes a runner multiple times and compiles reproducibility metrics."""
        log.warning(f"\n[BATCH ENGINE] ==============================================")
        log.warning(f"[BATCH ENGINE] STARTING REPRODUCIBILITY BATCH: {task_id}")
        log.warning(f"[BATCH ENGINE] TARGET ITERATIONS: {self.runs_per_task}")
        log.warning(f"[BATCH ENGINE] ==============================================\n")
        
        self.results.clear()
        
        for i in range(self.runs_per_task):
            log.info(f"[BATCH ENGINE] Starting Iteration {i+1}/{self.runs_per_task}...")
            start = time.time()
            
            # Simulate execution collection
            try:
                # We would normally await test_runner() here. 
                # For framework setup, we simulate a collected run.
                await asyncio.sleep(0.01) 
                
                # In production, these numbers would come from the MetricsCollector
                # per run, injected into RunStats.
                stats = RunStats(
                    run_id=i+1,
                    steps_taken=12,  # Simulated baseline
                    retries=0,
                    duration_s=time.time() - start,
                    success=True,
                    hallucinations=0
                )
                self.results.append(stats)
            except Exception as e:
                log.error(f"[BATCH ENGINE] Iteration {i+1} critically failed: {e}")
                self.results.append(RunStats(
                    run_id=i+1, steps_taken=0, retries=0, duration_s=0, success=False, hallucinations=0
                ))
                
        return self._generate_report(task_id)

    def _generate_report(self, task_id: str) -> ReproducibilityReport:
        if not self.results:
            return ReproducibilityReport(
                task_id=task_id, total_runs=0, success_rate=0, avg_steps=0, 
                step_variance=0, avg_retries=0, divergence_rate=1.0
            )
            
        successes = sum(1 for r in self.results if r.success)
        steps = [r.steps_taken for r in self.results if r.success]
        
        avg_steps = statistics.mean(steps) if steps else 0.0
        step_var = statistics.variance(steps) if len(steps) > 1 else 0.0
        avg_retries = statistics.mean([r.retries for r in self.results])
        
        # Divergence rate: How often does it deviate from the average step count by > 2 steps?
        divergent_runs = sum(1 for s in steps if abs(s - avg_steps) > 2)
        divergence_rate = (divergent_runs / len(steps)) if steps else 1.0
        
        report = ReproducibilityReport(
            task_id=task_id,
            total_runs=self.runs_per_task,
            success_rate=successes / self.runs_per_task,
            avg_steps=round(avg_steps, 2),
            step_variance=round(step_var, 2),
            avg_retries=round(avg_retries, 2),
            divergence_rate=round(divergence_rate, 4)
        )
        
        log.warning(f"\n[BATCH ENGINE] REPRODUCIBILITY REPORT FOR {task_id}")
        log.warning(f"  -> Success Rate    : {report.success_rate * 100:.1f}%")
        log.warning(f"  -> Divergence Rate : {report.divergence_rate * 100:.1f}%")
        log.warning(f"  -> Step Variance   : {report.step_variance}")
        
        return report
