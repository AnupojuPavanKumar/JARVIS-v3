import json
import os
import glob
from typing import Dict, Any, List

class FailureAnalyzer:
    """
    Analyzes evaluation metric dumps to identify failure patterns and calculate aggregate statistics.
    """
    def __init__(self, log_dir: str = "logs/evaluation"):
        self.log_dir = log_dir
        
    def analyze(self) -> Dict[str, Any]:
        """Reads all task reports and generates a consolidated reliability report."""
        reports = glob.glob(os.path.join(self.log_dir, "*.json"))
        
        total_tasks = 0
        successful_tasks = 0
        failures: List[Dict[str, Any]] = []
        
        # Aggregated metrics
        total_retries = 0
        total_hallucinations = 0
        total_invalid_cmds = 0
        total_context_corruptions = 0
        total_file_failures = 0
        
        for r in reports:
            with open(r, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    total_tasks += 1
                    
                    if data.get("success", False):
                        successful_tasks += 1
                    else:
                        failures.append(data)
                        
                    # Aggregate counters
                    total_retries += data.get("retry_count", 0)
                    total_hallucinations += data.get("hallucinated_tool_calls", 0)
                    total_invalid_cmds += data.get("invalid_shell_commands", 0)
                    total_context_corruptions += data.get("context_corruption_events", 0)
                    total_file_failures += data.get("file_operation_failures", 0)
                except Exception:
                    pass
                    
        success_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        
        report = {
            "summary": {
                "total_runs": total_tasks,
                "success_rate": f"{success_rate:.2f}%",
                "total_failures": len(failures)
            },
            "system_health": {
                "total_retries": total_retries,
                "total_hallucinations": total_hallucinations,
                "total_invalid_shell_commands": total_invalid_cmds,
                "total_context_corruptions": total_context_corruptions,
                "total_file_operation_failures": total_file_failures
            },
            "common_failure_causes": self._extract_common_causes(failures)
        }
        
        return report
        
    def _extract_common_causes(self, failures: List[Dict[str, Any]]) -> Dict[str, int]:
        causes: Dict[str, int] = {}
        for f in failures:
            err = f.get("error_message") or "Unknown execution error"
            causes[err] = causes.get(err, 0) + 1
        return causes

    def print_report(self):
        report = self.analyze()
        print("\n=== JARVIS-v3 Reliability Report ===")
        print(json.dumps(report, indent=2))
        print("===================================\n")

if __name__ == "__main__":
    analyzer = FailureAnalyzer()
    analyzer.print_report()
