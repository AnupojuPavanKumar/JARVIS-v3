import asyncio
import logging
import time
from typing import List

from core.system.task_graph import get_task_engine, TaskState, TaskNode
from core.evaluation.metrics import get_metrics
from core.testing.chaos_engine import ChaosEngine
from core.testing.adversarial_suite import get_adversarial_suite

log = logging.getLogger("LongHorizonTesting")

class LongHorizonRunner:
    """
    Phase 4: Long-Horizon Autonomy Testing
    Executes massive multi-stage tasks to measure execution drift and memory degradation.
    """
    def __init__(self):
        self.task_engine = get_task_engine()
        self.chaos_engine = ChaosEngine()
        
    async def run_long_horizon_test(self, test_id: str = "LHT-001"):
        log.warning(f"\n[LONG HORIZON] Initiating test: {test_id}")
        start_time = time.time()
        
        # 1. Generate Massive DAG
        graph = self._generate_massive_dag(test_id)
        
        # 2. Run under Chaos Engine (Adversarial simulation)
        # For simulation, we'll process the DAG while injecting faults.
        await self.chaos_engine.run_adversarial_scenario(
            "execution_chaos", 
            lambda: self._execute_dag(graph.graph_id)
        )
        
        duration = time.time() - start_time
        metrics = get_metrics()
        
        log.warning(f"[LONG HORIZON] Test {test_id} complete. Duration: {duration:.2f}s")
        # In a real run, this would output execution drift, memory pollution stats, etc.
        
    def _generate_massive_dag(self, test_id: str):
        objective = "Build a full-stack e-commerce application with React, Node, PostgreSQL, and Redis caching. Must include user authentication, product catalog, shopping cart, and Stripe payment integration."
        graph = self.task_engine.create_graph(objective, graph_id=test_id)
        
        # Simulate 100+ steps by creating a deep dependency chain
        prev_node_id = None
        for i in range(1, 101):
            node_id = f"step_{i:03d}"
            deps = [prev_node_id] if prev_node_id else []
            node = TaskNode(
                node_id=node_id,
                description=f"Long Horizon Step {i}",
                dependencies=deps
            )
            self.task_engine.add_node(graph.graph_id, node)
            prev_node_id = node_id
            
        return graph

    async def _execute_dag(self, graph_id: str):
        """Simulates processing a massive DAG."""
        while True:
            executable = self.task_engine.get_executable_nodes(graph_id)
            if not executable:
                # Check if graph is complete or failed
                graph = self.task_engine.active_graphs.get(graph_id)
                if graph and graph.state in [TaskState.COMPLETED, TaskState.FAILED]:
                    break
                await asyncio.sleep(1)
                continue
                
            for node in executable:
                # Simulate execution time and potential failures
                log.info(f"[LONG HORIZON] Executing {node.node_id}...")
                await asyncio.sleep(0.1) # Simulate fast execution for testing
                self.task_engine.update_node_state(graph_id, node.node_id, TaskState.COMPLETED, "Simulated success")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    runner = LongHorizonRunner()
    asyncio.run(runner.run_long_horizon_test())
