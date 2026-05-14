from __future__ import annotations

from pathlib import Path
from typing import Any


def run_project_runtime_smoke(project_dir: str | Path, executor: Any) -> dict:
    root = Path(project_dir)
    candidates = [root / "main.py", root / "app.py"]
    entrypoint = next((p for p in candidates if p.exists()), None)
    if entrypoint is None:
        return {"attempted": False, "success": False, "reason": "No runnable Python entrypoint found."}
    result = executor.run_python_file(entrypoint, ["--help"], cwd=root) if hasattr(executor, "run_python_file") else None
    success = bool(getattr(result, "success", False))
    return {
        "attempted": True,
        "success": success,
        "entrypoint": str(entrypoint),
        "mode": "--help",
        "result": result.to_dict() if hasattr(result, "to_dict") else {},
    }
