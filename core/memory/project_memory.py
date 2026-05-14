from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class ProjectMemory:
    """JSONL-backed compatibility store for project/job events."""

    def __init__(self, path: str | Path = "memory/project_memory.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record_job(self, job: str | dict[str, Any], **metadata: Any) -> dict[str, Any]:
        entry = {
            "ts": datetime.now().isoformat(),
            "job": job if isinstance(job, str) else job.get("job", job.get("task", "")),
            "metadata": metadata,
        }
        if isinstance(job, dict):
            entry.update(job)
            if metadata:
                entry["metadata"] = {**entry.get("metadata", {}), **metadata}

        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def recent_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows[-limit:]


_instance: ProjectMemory | None = None


def get_project_memory() -> ProjectMemory:
    global _instance
    if _instance is None:
        _instance = ProjectMemory()
    return _instance
