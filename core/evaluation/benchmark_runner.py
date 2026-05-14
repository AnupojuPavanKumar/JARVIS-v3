import asyncio
import logging
from typing import List, Optional
from core.evaluation.metrics import get_metrics
from core.evaluation.task_suite import get_standard_suite, BenchmarkTask
from core.orchestrator import get_autonomous_brain

log = logging.getLogger("BenchmarkRunner")

class BenchmarkRunner:
    """
    Executes the reliability benchmark suite and coordinates metric collection.
    """
    def __init__(self, log_dir: str = "logs/evaluation"):
        self.metrics = get_metrics()
        self.metrics.log_dir = log_dir
        self.suite = get_standard_suite()
        self.brain = get_autonomous_brain(identity="benchmark")
        
    async def run_all(self):
        """Run all tasks in the standard suite sequentially."""
        log.info(f"Starting benchmark suite execution ({len(self.suite)} tasks)")
        for task in self.suite:
            await self.run_task(task)
        log.info("Benchmark suite execution complete.")
            
    async def run_task(self, task: BenchmarkTask) -> bool:
        """
        Execute a single benchmark task and record its metrics.
        Returns True if successful, False otherwise.
        """
        log.info(f"\n{'='*50}\nExecuting Benchmark Task: {task.task_id} - {task.name}\n{'='*50}")
        self.metrics.start_task(task.task_id, task.name)
        
        try:
            # 1. Setup phase
            if task.setup_instructions:
                log.info(f"Running setup for {task.task_id}...")
                # Mock setup for now
                pass

            # 2. Execution phase
            # We inject the task description directly into the orchestrator.
            # In a true autonomous test, we wait for completion or timeout.
            log.info(f"Injecting task into AutonomousBrain...")
            
            # Since this is a stabilization framework, we are building the scaffolding.
            # Real execution would hook into task completion callbacks.
            # For now, we simulate sending the task.
            await self.brain.ingest_voice(text=task.description, identity="benchmark")
            
            # Wait a short duration to allow processing (simulated)
            await asyncio.sleep(2)
            
            # 3. Validation phase
            # Mock validation: we assume success for the scaffolding.
            success = True
            error_message = None
            
        except Exception as e:
            log.error(f"Task {task.task_id} failed with exception: {e}")
            success = False
            error_message = str(e)
            
        self.metrics.end_task(success=success, error_message=error_message)
        return success

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    runner = BenchmarkRunner()
    asyncio.run(runner.run_all())
