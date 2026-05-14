from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class ConversationHistory:
    def __init__(self, db_path: str = "memory/jarvis_state.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = self
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ts TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def add(self, speaker: str, text: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversation_history (speaker, text, ts) VALUES (?, ?, ?)",
                (speaker, text, datetime.now().isoformat()),
            )
            self._conn.commit()

    def get_recent(self, limit: int = 10) -> list[dict[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT speaker, text, ts FROM conversation_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        rows.reverse()
        return [{"speaker": s, "text": t, "ts": ts} for s, t, ts in rows]

    def format_for_prompt(self, limit: int = 8) -> str:
        turns = self.get_recent(limit)
        if not turns:
            return "[CONVERSATION HISTORY]\nNo recent conversation."
        lines = ["[CONVERSATION HISTORY]"]
        lines.extend(f"{t['speaker']}: {t['text']}" for t in turns)
        return "\n".join(lines)

    def recall_what_we_discussed(self) -> str:
        turns = self.get_recent(10)
        if not turns:
            return "We have not discussed anything yet."
        topics = ", ".join(t["text"] for t in turns[-4:])
        return f"Recently we discussed: {topics}"


_history: ConversationHistory | None = None


def get_history() -> ConversationHistory:
    global _history
    if _history is None:
        _history = ConversationHistory()
    return _history
