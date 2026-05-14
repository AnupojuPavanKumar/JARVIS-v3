from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class MemoryBrain:
    """Legacy memory graph facade backed by SQLite."""

    def __init__(self, db_path: str = "memory/memory_brain.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, ts TEXT)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, relation TEXT, object TEXT)"
            )
            self.db.commit()

    def log_action(self, action: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO actions (action, ts) VALUES (?, ?)",
                (action, datetime.now().isoformat()),
            )
            self.db.commit()

    def get_recent_actions(self, limit: int = 5) -> list[str]:
        with self._lock:
            rows = self.db.execute(
                "SELECT action FROM actions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def save_relationship(self, subject: str, relation: str, obj: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO relationships (subject, relation, object) VALUES (?, ?, ?)",
                (subject, relation, obj),
            )
            self.db.commit()

    def search_graph(self, query: str) -> list[str]:
        q = f"%{query.lower()}%"
        with self._lock:
            rows = self.db.execute(
                """
                SELECT subject, relation, object FROM relationships
                WHERE lower(subject) LIKE ? OR lower(relation) LIKE ? OR lower(object) LIKE ?
                ORDER BY id DESC LIMIT 10
                """,
                (q, q, q),
            ).fetchall()
        return [f"{s} {r} {o}" for s, r, o in rows]
