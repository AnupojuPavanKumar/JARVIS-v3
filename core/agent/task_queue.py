# core/task_queue.py — UNIFIED TASK QUEUE
from __future__ import annotations
import threading
import datetime
import logging
import time
import json
from typing import Optional
from core.system.db import get_db
from core.system.thread_manager import is_shutdown_requested

log = logging.getLogger("task_queue")

class PersistentTaskQueue:
    """
    Background task queue using the central SystemDB.
    """

    def __init__(self, agent_fn=None, speak_fn=None):
        self.db = get_db()
        self._agent_fn = agent_fn
        self._speak_fn = speak_fn
        self._paused   = False
        self._running  = False
        self._thread   = None

    def enqueue(self, task: str, priority: int = 5) -> int:
        task = task.strip()
        if not task: return -1
        with self.db._lock:
            cur = self.db._conn.execute(
                "INSERT INTO tasks (task, priority, state, created) VALUES (?,?,?,?)",
                (task, priority, "pending", datetime.datetime.now().isoformat())
            )
            self.db._conn.commit()
            task_id = cur.lastrowid
        log.info(f"[TaskQueue] Enqueued #{task_id}: '{task[:60]}'")
        return task_id

    def enqueue_multi(self, tasks: list[str]) -> list[int]:
        return [self.enqueue(t, priority=i + 5) for i, t in enumerate(tasks)]

    def cancel(self, task_id: int) -> bool:
        with self.db._lock:
            r = self.db._conn.execute(
                "UPDATE tasks SET state='cancelled' WHERE id=? AND state='pending'",
                (task_id,)
            )
            self.db._conn.commit()
        return r.rowcount > 0

    def clear_pending(self) -> int:
        with self.db._lock:
            r = self.db._conn.execute("UPDATE tasks SET state='cancelled' WHERE state='pending'")
            self.db._conn.commit()
        return r.rowcount

    def pause(self): self._paused = True
    def resume(self): self._paused = False

    def status_summary(self) -> str:
        cursor = self.db._conn.cursor()
        cursor.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state")
        counts = {r[0]: r[1] for r in cursor.fetchall()}
        p = counts.get("pending", 0); r = counts.get("running", 0); d = counts.get("done", 0); f = counts.get("failed", 0)
        parts = []
        if r: parts.append(f"{r} running")
        if p: parts.append(f"{p} pending")
        if d: parts.append(f"{d} completed")
        if f: parts.append(f"{f} failed")
        if not parts: return "Task queue is empty, sir."
        status = ", ".join(parts)
        if self._paused: status += " (PAUSED)"
        return f"Queue: {status}."

    def list_pending(self, n: int = 5) -> str:
        cursor = self.db._conn.cursor()
        cursor.execute("SELECT id, task FROM tasks WHERE state='pending' ORDER BY priority, id LIMIT ?", (n,))
        rows = cursor.fetchall()
        if not rows: return "No pending tasks, sir."
        items = "\n".join(f"  #{r[0]}: {r[1][:70]}" for r in rows)
        return f"Pending tasks:\n{items}"

    def start_worker(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="task_queue")
        self._thread.start()
        log.info("[TaskQueue] Worker started.")

    def stop_worker(self): self._running = False

    def _worker_loop(self):
        while self._running and not is_shutdown_requested():
            if self._paused:
                time.sleep(2); continue
            task_row = self._next_pending()
            if not task_row:
                time.sleep(3); continue
            task_id, task_text = task_row
            self._set_state(task_id, "running", started=datetime.datetime.now().isoformat())
            result, state = "", "failed"
            try:
                if self._agent_fn:
                    result = self._agent_fn(task_text) or "Task completed."
                    state = "done"
                else: result = "No agent function wired."
            except Exception as e:
                result = f"Error: {e}"
                log.warning(f"[TaskQueue] Task #{task_id} failed: {e}")
            self._set_state(task_id, state, finished=datetime.datetime.now().isoformat(), result=result[:500])
            if self._speak_fn:
                threading.Thread(target=self._speak_fn, args=(f"Task {task_id} complete.",), daemon=True).start()
            self._notify(task_id, task_text, result, state)

    def _next_pending(self) -> Optional[tuple[int, str]]:
        cursor = self.db._conn.cursor()
        cursor.execute("SELECT id, task FROM tasks WHERE state='pending' ORDER BY priority, id LIMIT 1")
        return cursor.fetchone()

    def _set_state(self, task_id: int, state: str, **kwargs):
        sets = ["state=?"]; vals = [state]
        for k, v in kwargs.items():
            sets.append(f"{k}=?"); vals.append(v)
        vals.append(task_id)
        with self.db._lock:
            self.db._conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
            self.db._conn.commit()

    def _notify(self, task_id: int, task: str, result: str, state: str):
        try:
            from core.system.event_bus import get_event_bus
            from core.system.events import EventNtfyPush
            get_event_bus().publish(EventNtfyPush(
                title=f"{'✅' if state == 'done' else '❌'} Task #{task_id} {state.upper()}",
                message=f"{task[:80]}\n{result[:200]}"
            ))
        except Exception as e:
            log.error(f"Silent error caught: {e}")

def parse_queued_tasks(command: str) -> list[str]:
    import re
    splitters = r"\band then\b|\bthen\b|\bafter that\b|\bnext\b|\bafterward\b|\bfinally\b"
    parts = re.split(splitters, command, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 5]

_instance: PersistentTaskQueue | None = None
_instance_lock = threading.Lock()

def get_task_queue() -> PersistentTaskQueue:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PersistentTaskQueue()
    return _instance
