from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path


class LongTermMemory:
    """SQLite-backed compatibility replacement for the removed Chroma wrapper."""

    def __init__(self, db_path: str = "memory/long_term_memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()
        self.collection = self

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, pattern TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            self._conn.commit()

    def commit_memory(self, task: str, pattern: str) -> str:
        with self._lock:
            self._conn.execute(
                "INSERT INTO memories (task, pattern) VALUES (?, ?)",
                (task, pattern),
            )
            self._conn.commit()
        return "Successfully committed memory."

    def search_memory(self, query: str, limit: int = 5) -> str:
        terms = [t.lower() for t in query.split() if len(t) > 2]
        with self._lock:
            rows = self._conn.execute(
                "SELECT task, pattern FROM memories ORDER BY id DESC LIMIT 200"
            ).fetchall()
        scored = []
        for task, pattern in rows:
            haystack = f"{task} {pattern}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score or not terms:
                scored.append((score, task, pattern))
        scored.sort(reverse=True)
        if not scored:
            return "No historic patterns found."
        return "\n".join(
            f"- {task}: {pattern}" for _, task, pattern in scored[:limit]
        )

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def query(self, query_texts, n_results: int = 5, **_kwargs) -> dict:
        query = query_texts[0] if query_texts else ""
        text = self.search_memory(query, limit=n_results)
        docs = [] if text.startswith("No historic") else [text]
        return {"documents": [docs], "metadatas": [[{"query": query} for _ in docs]]}


_instance: LongTermMemory | None = None


def get_memory_instance() -> LongTermMemory:
    global _instance
    if _instance is None:
        _instance = LongTermMemory()
    return _instance
