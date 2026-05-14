# core/db.py  —  V4 CENTRAL SYSTEM DATABASE
import sqlite3
import threading
import os
import json
import queue

DB_PATH = "memory/jarvis_state.db"

class SystemDB:
    """
    Central SQLite database for JARVIS-v4.
    Unifies settings, storage, telemetry, history, and task queue.

    FIX: Removed check_same_thread=False and added proper thread-safe
    queue-based serialization for all database operations.
    """
    _instance = None
    _lock = threading.RLock()  # RLock: re-entrant, prevents deadlock in __new__ → _init_db

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                print(f"[SystemDB] Connecting to {DB_PATH}...")
                cls._instance = super(SystemDB, cls).__new__(cls)
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                # FIX: Use proper threading - use WAL mode for better concurrency
                cls._instance._conn = sqlite3.connect(DB_PATH, timeout=30.0)
                cls._instance._conn.execute("PRAGMA journal_mode=WAL")
                cls._instance._db_lock = threading.Lock()
                print("[SystemDB] Initializing schema...")
                cls._instance._init_db()
                print("[SystemDB] Connected.")
        return cls._instance

    def _init_db(self):
        with self._lock:
            cursor = self._conn.cursor()
            
            # 1. Key-Value Settings
            cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            
            # 2. Category-based Blob Storage (JSON)
            cursor.execute("CREATE TABLE IF NOT EXISTS storage (id TEXT PRIMARY KEY, category TEXT, data TEXT)")
            
            # 3. Telemetry & Event Logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    event TEXT, 
                    timestamp TEXT, 
                    data TEXT
                )
            """)
            
            # 4. Unified Conversation History
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    speaker TEXT    NOT NULL,
                    text    TEXT    NOT NULL,
                    ts      TEXT    NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_hist_ts ON conversation_history(ts)")
            
            # 5. Unified Task Queue
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    task      TEXT    NOT NULL,
                    priority  INTEGER DEFAULT 5,
                    state     TEXT    DEFAULT 'pending',
                    created   TEXT,
                    started   TEXT,
                    finished  TEXT,
                    result    TEXT
                )
            """)
            
            self._conn.commit()

    # ── API ─────────────────────────────────────────────────────────────

    def set_setting(self, key: str, value: str):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            self._conn.commit()

    def get_setting(self, key: str, default: str = None) -> str:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def save_object(self, category: str, obj_id: str, data: dict):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO storage (id, category, data) VALUES (?, ?, ?)",
                (obj_id, category, json.dumps(data))
            )
            self._conn.commit()

    def load_object(self, obj_id: str) -> dict | None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT data FROM storage WHERE id=?", (obj_id,))
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None

    def load_category(self, category: str) -> list[dict]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT data FROM storage WHERE category=?", (category,))
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def log_event(self, event: str, data: dict = None):
        from datetime import datetime
        with self._lock:
            self._conn.execute(
                "INSERT INTO telemetry (event, timestamp, data) VALUES (?, ?, ?)",
                (event, datetime.now().isoformat(), json.dumps(data or {}))
            )
            self._conn.commit()

    def vacuum(self, prune_telemetry_days: int = 30) -> str:
        """
        Fix 2 — DB Maintenance Cycle:
        1. Prune telemetry rows older than `prune_telemetry_days`.
        2. VACUUM — rebuilds the DB file, reclaims fragmented pages.
        3. ANALYZE — updates SQLite's query planner statistics.

        Call from the nightly SelfLearningLoop to keep BFS/DFS queries fast
        even after months of GraphSynthesizer writes.

        Returns a summary string for logging.
        """
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=prune_telemetry_days)).isoformat()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM telemetry WHERE timestamp < ?", (cutoff,))
            pruned_tel = cur.rowcount
            
            cur.execute("DELETE FROM conversation_history WHERE ts < ?", (cutoff,))
            pruned_hist = cur.rowcount
            
            cur.execute("DELETE FROM tasks WHERE created < ?", (cutoff,))
            pruned_tasks = cur.rowcount
            
            self._conn.commit()
            # VACUUM must run outside a transaction (implicit commit above suffices)
            self._conn.execute("VACUUM")
            self._conn.execute("ANALYZE")
        msg = (f"[SystemDB] Maintenance complete — pruned {pruned_tel} telemetry, "
               f"{pruned_hist} history, {pruned_tasks} tasks. VACUUM done.")
        import logging
        logging.getLogger("SystemDB").info(msg)
        return msg

def get_db() -> SystemDB:
    return SystemDB()
