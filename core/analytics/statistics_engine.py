import statistics
from typing import List, Dict, Any

class StatisticsEngine:
    """
    Phase 2: Statistical Reliability Analysis
    Calculates hard metrics from the validation data pipeline. No qualitative assumptions.
    """
    
    @staticmethod
    def compute_metrics(runs: List[Dict[str, Any]]) -> Dict[str, float]:
        if not runs:
            return {}
            
        successes = sum(1 for r in runs if r.get("success", False))
        total = len(runs)
        
        steps = [r.get("steps_taken", 0) for r in runs if r.get("success", False)]
        retries = [r.get("retries", 0) for r in runs]
        durations = [r.get("duration_s", 0.0) for r in runs]
        
        avg_steps = statistics.mean(steps) if steps else 0.0
        step_var = statistics.variance(steps) if len(steps) > 1 else 0.0
        step_std_dev = statistics.stdev(steps) if len(steps) > 1 else 0.0
        
        # Execution drift / divergence
        divergent_runs = sum(1 for s in steps if abs(s - avg_steps) > 2)
        divergence_rate = (divergent_runs / len(steps)) if steps else 1.0
        
        hallucinated_tools = sum(r.get("hallucinations", 0) for r in runs)
        
        avg_duration = statistics.mean(durations) if durations else 0.0
        
        return {
            "total_runs": float(total),
            "success_rate": round(successes / total, 4),
            "avg_steps": round(avg_steps, 2),
            "step_variance": round(step_var, 2),
            "step_std_dev": round(step_std_dev, 2),
            "divergence_rate": round(divergence_rate, 4),
            "avg_retries": round(statistics.mean(retries), 2),
            "retry_variance": round(statistics.variance(retries) if len(retries) > 1 else 0.0, 2),
            "hallucination_frequency": round(hallucinated_tools / total, 4),
            "mean_execution_duration": round(avg_duration, 2)
        }
