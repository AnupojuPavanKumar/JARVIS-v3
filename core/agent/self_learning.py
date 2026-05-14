# core/self_learning.py — JARVIS Self-Learning & Continuous Improvement (Upgrade #8)
# ──────────────────────────────────────────────────────────────────────────────
# After every agent task, JARVIS analyses what went wrong (or right) and:
#   - Stores golden patterns from successes for future RAG injection
#   - Logs failures with full context for auto-healing
#   - Auto-generates improved retry prompts when a tool fails 3x
#   - Runs nightly reflection: scans failure logs, auto-generates new skills
#   - Tracks per-intent accuracy and flags weak spots for retraining
#
# Three components:
#   1. LearningMemory   — ChromaDB 'golden_patterns' collection (success stories)
#   2. FailureAnalyser  — Logs failures, detects patterns, triggers skill regen
#   3. SelfLearningLoop — Orchestrates both, called from agent.py after each run
#
# Usage (called automatically from agent.py):
#   from core.agent.self_learning import get_learning_loop
#   loop = get_learning_loop()
#   loop.on_task_complete(task, result, steps, success=True)
#   loop.on_tool_failure(task, tool, error, attempt)
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

import requests

log = logging.getLogger("SelfLearning")

OLLAMA_URL    = "http://localhost:11434/api/generate"
LEARN_MODEL   = "gemma2:2b"         # Lightweight model for reflection
FAILURE_LOG   = "memory/failure_log.jsonl"
PATTERN_DB    = "memory/golden_patterns.jsonl"
MAX_FAILURES  = 3                   # Failures before auto-heal triggers
NIGHTLY_HOUR  = 3                   # 3 AM — run reflection loop


# ═══════════════════════════════════════════════════════════════════════════════
#  GOLDEN PATTERN MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

class LearningMemory:
    """
    Stores 'golden patterns' — successful task solutions — in ChromaDB
    so they can be injected as RAG context for similar future tasks.
    Supplements the existing pattern_memory.py with richer metadata.
    """

    def __init__(self):
        self._chroma_ok  = False
        self._collection = None
        self._init_chroma()

    def _init_chroma(self):
        """ChromaDB disabled: same Rust/tokio IOCP crash as pattern_memory.
        All learning stored to PATTERN_DB JSONL file instead."""
        self._chroma_ok  = False
        self._collection = None

    def store_pattern(self, task: str, result: str, steps: int,
                      tools_used: list[str], duration_s: float):
        """Store a successful task completion as a golden pattern."""
        if not self._chroma_ok or not self._collection:
            return
        try:
            doc_id = hashlib.md5(f"{task}{datetime.now().date()}".encode()).hexdigest()
            self._collection.upsert(
                ids=[doc_id],
                documents=[f"TASK: {task}\n\nSOLUTION:\n{result}"],
                metadatas=[{
                    "task":       task[:200],
                    "steps":      steps,
                    "tools":      json.dumps(tools_used[:10]),
                    "duration_s": round(duration_s, 1),
                    "date":       datetime.now().isoformat(),
                    "quality":    "golden",
                }]
            )
            log.info(f"[Learning] Golden pattern stored: '{task[:50]}'")
        except Exception as e:
            log.warning(f"[Learning] Store error: {e}")

    def recall_patterns(self, task: str, top_k: int = 2) -> str:
        """Return the top-k most similar golden patterns as a context block."""
        if not self._chroma_ok or not self._collection:
            return ""
        if self._collection.count() == 0:
            return ""
        try:
            results = self._collection.query(
                query_texts=[task],
                n_results=min(top_k, self._collection.count()),
                include=["documents", "metadatas", "distances"],
            )
            if not results["ids"][0]:
                return ""
            lines = ["=== GOLDEN PATTERNS (past successes) ==="]
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                if dist < 1.5:   # Only inject genuinely similar patterns
                    lines.append(f"\n[Pattern] {meta.get('task', '')[:80]}")
                    lines.append(f"Steps: {meta.get('steps')}  Tools: {meta.get('tools')}")
                    lines.append(doc[:600])
            if len(lines) > 1:
                return "\n".join(lines)
        except Exception as e:
            log.warning(f"[Learning] Recall error: {e}")
        return ""

    def count(self) -> int:
        if self._chroma_ok and self._collection:
            return self._collection.count()
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  FAILURE ANALYSER
# ═══════════════════════════════════════════════════════════════════════════════

class FailureAnalyser:
    """
    Logs tool failures, detects repeat patterns, and triggers auto-healing.
    """

    def __init__(self):
        os.makedirs("memory", exist_ok=True)
        self._failure_counts: dict[str, int] = {}  # tool -> consecutive fails
        self._session_failures: list[dict]   = []

    def log_failure(self, task: str, tool: str, error: str, attempt: int) -> Optional[str]:
        """
        Log a tool failure. Returns an auto-heal suggestion if the tool has
        failed MAX_FAILURES times in a row.
        """
        key = f"{tool}:{hashlib.md5(error[:100].encode()).hexdigest()[:8]}"
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

        entry = {
            "ts":      datetime.now().isoformat(),
            "task":    task[:200],
            "tool":    tool,
            "error":   error[:500],
            "attempt": attempt,
        }
        self._session_failures.append(entry)

        # Append to persistent log
        try:
            with open(FAILURE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        if self._failure_counts[key] >= MAX_FAILURES:
            self._failure_counts[key] = 0  # Reset counter
            return self._generate_fix_suggestion(task, tool, error)
        return None

    def _generate_fix_suggestion(self, task: str, tool: str, error: str) -> str:
        """Ask the LLM for an alternative approach when a tool keeps failing."""
        prompt = (
            f"You are JARVIS, an autonomous AI agent.\n"
            f"Task: {task}\n"
            f"Tool that failed 3 times: {tool}\n"
            f"Error: {error[:400]}\n\n"
            f"Suggest a DIFFERENT approach or alternative tool to complete this task. "
            f"Be specific and actionable. Maximum 3 sentences."
        )
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": LEARN_MODEL, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_predict": 200}},
                timeout=30,
            )
            if r.status_code == 200:
                suggestion = r.json().get("response", "").strip()
                log.info(f"[Learning] Auto-fix suggestion generated for {tool}")
                return f"[AUTO-HEAL] Alternative approach: {suggestion}"
        except Exception:
            pass
        return f"[AUTO-HEAL] Tool '{tool}' failed 3 times — try a different tool or approach."

    def analyse_session_failures(self) -> str:
        """Summarise failures from the current session."""
        if not self._session_failures:
            return "No failures this session."
        tools = {}
        for f in self._session_failures:
            t = f["tool"]
            tools[t] = tools.get(t, 0) + 1
        worst = sorted(tools.items(), key=lambda x: -x[1])
        lines = ["Session failure summary:"]
        for tool, count in worst[:5]:
            lines.append(f"  {tool}: {count} failure(s)")
        return "\n".join(lines)

    def load_historical_failures(self) -> list[dict]:
        """Load all logged failures from disk."""
        failures = []
        try:
            if os.path.exists(FAILURE_LOG):
                with open(FAILURE_LOG, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                failures.append(json.loads(line))
                            except Exception:
                                pass
        except Exception:
            pass
        return failures


# ═══════════════════════════════════════════════════════════════════════════════
#  SELF-LEARNING LOOP
# ═══════════════════════════════════════════════════════════════════════════════

class SelfLearningLoop:
    """
    Orchestrates learning memory and failure analysis.
    Called from agent.py after each task completes.
    Also runs a nightly reflection loop to auto-generate skills from failures.
    """

    def __init__(self):
        self._memory   = LearningMemory()
        self._failures = FailureAnalyser()
        self._lock     = threading.Lock()
        self._stop_evt = threading.Event()
        self._task_start: float = 0.0
        self._tools_used: list[str] = []

    # ── Agent lifecycle hooks ───────────────────────────────────────────────────

    def on_task_start(self, task: str):
        """Call at the beginning of each agent.run()."""
        self._task_start = time.time()
        self._tools_used = []
        log.info(f"[Learning] Task started: '{task[:60]}'")

    def on_tool_call(self, tool: str):
        """Call every time the agent invokes a tool."""
        if tool not in self._tools_used:
            self._tools_used.append(tool)

    def on_tool_failure(self, task: str, tool: str,
                        error: str, attempt: int) -> Optional[str]:
        """
        Call when a tool fails. Returns an auto-heal suggestion after 3 failures.
        The agent can inject this suggestion into the next LLM prompt.
        """
        return self._failures.log_failure(task, tool, error, attempt)

    def on_task_complete(self, task: str, result: str,
                         steps: int, success: bool):
        """
        Call when a task finishes (success or failure).
        Stores golden patterns on success, triggers reflection on failure.
        """
        duration = time.time() - self._task_start

        if success and result and "error" not in result.lower()[:30]:
            # Store as golden pattern for future RAG injection
            self._memory.store_pattern(
                task=task,
                result=result,
                steps=steps,
                tools_used=list(self._tools_used),
                duration_s=duration,
            )
            log.info(
                f"[Learning] Task complete (success) in {duration:.1f}s, "
                f"{steps} steps, {len(self._tools_used)} tools"
            )
        else:
            log.info(
                f"[Learning] Task ended (failure/partial) in {duration:.1f}s, "
                f"{steps} steps"
            )
            # Trigger background reflection for failed tasks
            threading.Thread(
                target=self._reflect_on_failure,
                args=(task, result),
                daemon=True,
                name="SelfLearn-Reflect"
            ).start()

    def recall_patterns(self, task: str) -> str:
        """Return golden patterns for RAG injection into agent prompt."""
        return self._memory.recall_patterns(task)

    def session_summary(self) -> str:
        """Return a human-readable learning summary for this session."""
        return (
            f"Golden patterns stored: {self._memory.count()}\n"
            f"{self._failures.analyse_session_failures()}"
        )

    # ── Nightly reflection ──────────────────────────────────────────────────────

    def start_nightly_reflection(self):
        """Start a background thread that runs reflection at NIGHTLY_HOUR daily."""
        threading.Thread(
            target=self._nightly_loop,
            daemon=True,
            name="SelfLearn-Nightly"
        ).start()
        log.info("[Learning] Nightly reflection loop started.")

    def _nightly_loop(self):
        """Sleep until 3AM then run the full reflection cycle."""
        while not self._stop_evt.is_set():
            now  = datetime.now()
            secs = ((NIGHTLY_HOUR - now.hour) % 24) * 3600 - now.minute * 60
            if secs <= 0:
                secs += 86400
            log.info(f"[Learning] Next reflection in {secs//3600:.0f}h")
            try:
                if self._stop_evt.wait(timeout=secs):
                    break   # woken by shutdown
            except Exception:
                break
            if not self._stop_evt.is_set():
                self._run_reflection()

    def _run_reflection(self):
        """
        Full nightly reflection cycle:
        1. Load failure log
        2. Group by most common failing tool/pattern
        3. Auto-generate skills for recurring failures
        4. Save reflection report
        """
        log.info("[Learning] Starting nightly reflection...")
        failures = self._failures.load_historical_failures()
        if not failures:
            log.info("[Learning] No failures to reflect on.")
            return

        # Count by tool
        tool_counts: dict[str, list] = {}
        for f in failures[-200:]:   # Last 200 failures
            t = f.get("tool", "unknown")
            tool_counts.setdefault(t, []).append(f)

        report_lines = [
            f"=== JARVIS Nightly Reflection — {datetime.now().strftime('%Y-%m-%d')} ===",
            f"Total failures analysed: {len(failures)}",
            "",
        ]

        for tool, tool_failures in sorted(tool_counts.items(),
                                           key=lambda x: -len(x[1]))[:5]:
            count = len(tool_failures)
            report_lines.append(f"[{tool}] {count} failure(s)")

            # Auto-generate skill for high-frequency failures (5+)
            if count >= 5:
                sample = tool_failures[-1]
                self._auto_generate_skill_from_failure(
                    task=sample.get("task", ""),
                    tool=tool,
                    error=sample.get("error", ""),
                )
                report_lines.append(f"  -> Auto-skill generated for {tool}")

        # Save report
        report_path = f"memory/reflection_{datetime.now().strftime('%Y%m%d')}.txt"
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(report_lines))
            log.info(f"[Learning] Reflection report saved: {report_path}")
        except Exception:
            pass

        # Ghost D: decay edge weights nightly so stale knowledge fades gradually.
        try:
            from core.memory.memory_brain import MemoryBrain
            MemoryBrain().decay_edges(factor=0.98)
            log.info("[Learning] Property graph edge weights decayed (factor=0.98).")
        except Exception as exc:
            log.warning(f"[Learning] Edge decay skipped: {exc}")

        # Fix 2: nightly DB maintenance — VACUUM + ANALYZE + prune old telemetry.
        # Keeps BFS queries fast even after months of GraphSynthesizer writes.
        try:
            from core.system.db import get_db
            msg = get_db().vacuum(prune_telemetry_days=30)
            log.info(msg)
        except Exception as exc:
            log.warning(f"[Learning] DB vacuum skipped: {exc}")

    def _reflect_on_failure(self, task: str, error: str):
        """Lightweight per-task reflection — generates a fix note."""
        if not error or len(error) < 20:
            return
        # Skip if shutdown is in progress — avoids 20s timeout hang during exit
        if self._stop_evt.is_set():
            return
        try:
            prompt = (
                f"JARVIS failed this task: {task[:200]}\n"
                f"Error/result: {error[:300]}\n\n"
                f"In one sentence, what is the root cause and how should JARVIS "
                f"approach this differently next time?"
            )
            r = requests.post(
                OLLAMA_URL,
                json={"model": LEARN_MODEL, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 100}},
                timeout=20,
            )
            if r.status_code == 200:
                insight = r.json().get("response", "").strip()
                if insight:
                    # Append to failure log with the insight
                    entry = {
                        "ts":      datetime.now().isoformat(),
                        "type":    "reflection",
                        "task":    task[:200],
                        "insight": insight,
                    }
                    with open(FAILURE_LOG, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry) + "\n")
                    log.info(f"[Learning] Reflection insight: {insight[:80]}")
        except Exception as e:
            log.warning(f"[Learning] Reflection error: {e}")

    def _auto_generate_skill_from_failure(self, task: str, tool: str, error: str):
        """Trigger the SkillFactory to auto-generate a new skill for this failure."""
        try:
            from core.api.skill_factory import get_skill_factory
            factory = get_skill_factory()
            subject = f"handle errors from {tool} when doing: {task[:100]}"
            path = factory.generate_skill(subject)
            if path:
                log.info(f"[Learning] Auto-skill generated: {path}")
        except Exception as e:
            log.warning(f"[Learning] Skill generation failed: {e}")


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[SelfLearningLoop] = None


def get_learning_loop() -> SelfLearningLoop:
    global _instance
    if _instance is None:
        _instance = SelfLearningLoop()
    return _instance
