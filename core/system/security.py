# core/security.py — VIBE-SHIELD v1.0
# ══════════════════════════════════════════════════════════════════════════════
#  Hallucination Firewall for JARVIS-v3 Sovereign Orchestrator
#
#  Architecture:
#    ┌─────────────────────────────────────────────────────────────────┐
#    │  Worker Model  ──►  VibeShield (Judge: gemma2:9b)              │
#    │                         │                                       │
#    │                   Chain-of-Verification (CoVe)                 │
#    │                         │                                       │
#    │              ┌──────────┴──────────┐                           │
#    │           VALID                HALLUCINATION                   │
#    │              │                      │                           │
#    │         Pass-through          Self-Correction Loop             │
#    │                               (re-prompt worker)               │
#    └─────────────────────────────────────────────────────────────────┘
#
#  Hardware-aware:
#    - CUDA GPU offloading via Ollama num_gpu parameter
#    - VRAM-safe: checks usage before every Judge call
#    - Async SQLite logging — non-blocking, background thread queue
#
#  Usage:
#    from core.system.security import VibeShield, vibe_shield_middleware
#    shield = VibeShield()
#    result = shield.audit(claim="...", source_fact="...")
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import logging
import queue
import re
import sqlite3
import threading
import time
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

# ── Logger ─────────────────────────────────────────────────────────────────────
log = logging.getLogger("VibeShield")
logging.basicConfig(
    level=logging.INFO,
    format="[%(name)s] %(levelname)s — %(message)s",
)

# ── Constants ──────────────────────────────────────────────────────────────────
OLLAMA_BASE_URL   = "http://localhost:11434"
OLLAMA_GENERATE   = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_TAGS       = f"{OLLAMA_BASE_URL}/api/tags"

JUDGE_MODEL       = "gemma2:2b"          # CoVe judge — 1.6 GB, fits fully in RTX 4050 6GB VRAM
DB_PATH           = "vibe_shield_logs.db"

# GPU offload: send all layers to CUDA.  Ollama maps this to CUDA automatically.
# If VRAM overflows, Ollama falls back to CPU for excess layers — safe.
JUDGE_OPTIONS = {
    "num_gpu":      99,      # Offload all layers to CUDA (Ollama caps at actual layer count)
    "num_thread":   4,       # Minimal CPU threads — let GPU do the heavy lifting
    "temperature":  0.0,     # Deterministic verdicts — no creative hallucination from the judge
    "top_p":        1.0,
    "num_predict":  512,     # Cap output — verdicts don't need to be long
    # NOTE: no stop tokens — the CoVe prompt itself contains backtick examples
    # which would cause stop tokens to fire before any response is generated.
}

MAX_CORRECTION_LOOPS = 3     # Prevent infinite self-correction spirals
VRAM_WARN_THRESHOLD  = 85.0  # % — evict stale models above this (gemma2:2b fits cleanly, no spill)


# ══════════════════════════════════════════════════════════════════════════════
#  DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditResult:
    """Structured verdict returned by VibeShield.audit()."""
    status:     str   # "VALID" | "HALLUCINATION" | "ERROR"
    reason:     str   # Human-readable explanation
    correction: str   # Suggested correction (empty if VALID)
    latency_ms: float = 0.0
    model_used: str   = JUDGE_MODEL
    caught_by:  str   = "AI-Audit"   # "Pre-Audit" (regex hard guard) | "AI-Audit" (LLM judge)


@dataclass
class LogEntry:
    """One row to be written to vibe_shield_logs.db (non-blocking queue item)."""
    timestamp:      str
    user_prompt:    str
    ai_response:    str
    verdict:        str
    reason:         str
    correction:     str
    latency_ms:     float
    loop_iteration: int = 0


# ══════════════════════════════════════════════════════════════════════════════
#  ASYNC SQLITE LOGGER
# ══════════════════════════════════════════════════════════════════════════════

class _AsyncSQLiteLogger:
    """
    Background-thread SQLite writer.
    Main loop enqueues log entries and continues immediately.
    The worker thread drains the queue and persists to disk.

    This ensures VibeShield audits NEVER block the JARVIS main loop.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._queue: queue.Queue[Optional[LogEntry]] = queue.Queue()
        self._init_db()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="VibeShield-Logger")
        self._thread.start()
        log.info(f"Async SQLite logger started → {db_path}")

    def _init_db(self):
        """Create the audit log table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT    NOT NULL,
                    user_prompt     TEXT    NOT NULL,
                    ai_response     TEXT    NOT NULL,
                    verdict         TEXT    NOT NULL,
                    reason          TEXT    NOT NULL,
                    correction      TEXT    NOT NULL DEFAULT '',
                    latency_ms      REAL    NOT NULL DEFAULT 0.0,
                    loop_iteration  INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_verdict   ON audit_log(verdict);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_log(timestamp);
            """)
            conn.commit()

    def _worker(self):
        """Drains the queue and writes to SQLite + Text Log. Runs in a daemon thread."""
        os.makedirs("logs", exist_ok=True)
        log_file = "logs/vibe_shield.log"
        
        while True:
            entry = self._queue.get()
            if entry is None:   # Poison pill — shut down gracefully
                break
            try:
                # 1. Write to SQLite
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        """INSERT INTO audit_log
                           (timestamp, user_prompt, ai_response, verdict, reason,
                            correction, latency_ms, loop_iteration)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entry.timestamp,
                            entry.user_prompt,
                            entry.ai_response,
                            entry.verdict,
                            entry.reason,
                            entry.correction,
                            entry.latency_ms,
                            entry.loop_iteration,
                        ),
                    )
                    conn.commit()

                # 2. Append to Text Log for real-time tailing
                with open(log_file, "a", encoding="utf-8") as f:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    status_icon = "✅" if entry.verdict == "VALID" else "🚨" if entry.verdict == "HALLUCINATION" else "⚠️"
                    log_line = (
                        f"[{ts}] {status_icon} {entry.verdict.ljust(13)} | "
                        f"Loop: {entry.loop_iteration} | Latency: {entry.latency_ms:.0f}ms | "
                        f"Reason: {entry.reason}\n"
                    )
                    f.write(log_line)

            except Exception as exc:
                log.error(f"DB/File write failed: {exc}")
            finally:
                self._queue.task_done()

    def enqueue(self, entry: LogEntry):
        """Non-blocking — puts entry onto the queue and returns immediately."""
        self._queue.put_nowait(entry)

    def shutdown(self):
        """Flush pending writes and stop the background thread."""
        self._queue.join()          # Wait for all queued items to be written
        self._queue.put(None)       # Send poison pill
        self._thread.join(timeout=5)
        log.info("Async SQLite logger shut down.")

    def query_recent(self, limit: int = 20) -> list[dict]:
        """Synchronously fetch recent audit entries (for dashboard / debug)."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error(f"Query failed: {exc}")
            return []

    def stats(self) -> dict:
        """Return aggregate statistics (total, valid count, hallucination count)."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
                valid = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE verdict='VALID'"
                ).fetchone()[0]
                hall  = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE verdict='HALLUCINATION'"
                ).fetchone()[0]
                avg_lat = conn.execute(
                    "SELECT AVG(latency_ms) FROM audit_log"
                ).fetchone()[0] or 0.0
                return {
                    "total_audits":       total,
                    "valid":              valid,
                    "hallucinations":     hall,
                    "error":              total - valid - hall,
                    "hallucination_rate": round(hall / total * 100, 2) if total else 0.0,
                    "avg_latency_ms":     round(avg_lat, 1),
                }
        except Exception as exc:
            log.error(f"Stats query failed: {exc}")
            return {}


# ══════════════════════════════════════════════════════════════════════════════
#  VIBE-SHIELD — THE HALLUCINATION FIREWALL
# ══════════════════════════════════════════════════════════════════════════════

class VibeShield:
    """
    Chain-of-Verification (CoVe) Hallucination Firewall.

    Connects to the local Ollama API and uses gemma2:9b as a Judge model.
    Every audit is persisted asynchronously to SQLite without blocking callers.

    Typical flow:
        shield = VibeShield()
        result = shield.audit(
            claim       = "The Eiffel Tower is 500 meters tall.",
            source_fact = "The Eiffel Tower is 330 meters tall.",
            user_prompt = "How tall is the Eiffel Tower?",
        )
        # result.status → "HALLUCINATION"
        # result.reason → "The claim states 500m but the source fact states 330m."
        # result.correction → "The Eiffel Tower is 330 meters tall."
    """

    def __init__(
        self,
        judge_model: str = JUDGE_MODEL,
        db_path: str     = DB_PATH,
        timeout: int     = 90,   # 90s: covers cold first-load of gemma2:9b from disk
    ):
        self._judge_model = judge_model
        self._timeout     = timeout
        self._db          = _AsyncSQLiteLogger(db_path)
        log.info(f"VibeShield initialized — Judge: {self._judge_model}")

    # ── VRAM Guard ──────────────────────────────────────────────────────────────

    def _check_vram(self) -> float | None:
        """Return VRAM % usage, or None if pynvml isn't available."""
        try:
            import pynvml                                       # type: ignore[import]
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem    = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return round(100 * mem.used / mem.total, 1)
        except Exception:
            return None

    def _evict_stale(self):
        """Ask Ollama to drop all loaded models from VRAM before judge runs."""
        try:
            requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": self._judge_model, "keep_alive": 0},
                timeout=5,
            )
            log.warning("VRAM critical — evicted stale models.")
        except Exception:
            pass

    def _guard_vram(self):
        """Evict stale models if VRAM is dangerously full."""
        pct = self._check_vram()
        if pct is not None and pct > VRAM_WARN_THRESHOLD:
            log.warning(f"VRAM at {pct:.1f}% (>{VRAM_WARN_THRESHOLD}%) — evicting before Judge call.")
            self._evict_stale()

    # ── Ollama Connectivity ─────────────────────────────────────────────────────

    def _is_ollama_running(self) -> bool:
        try:
            r = requests.get(OLLAMA_TAGS, timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _is_judge_available(self) -> bool:
        """Check if the judge model is installed in Ollama."""
        try:
            r = requests.get(OLLAMA_TAGS, timeout=3)
            models = [m.get("name", "") for m in r.json().get("models", [])]
            base   = self._judge_model.split(":")[0]
            return any(self._judge_model in m or m.startswith(base) for m in models)
        except Exception:
            return False

    # ── CoVe Prompt Builder (Rubric-Based) ─────────────────────────────────────

    def _build_cove_prompt(self, claim: str, source_fact: str) -> str:
        """
        Constructs the rubric-based Chain-of-Verification prompt.

        The rubric explicitly handles the four accuracy failure modes:
          - False Positive: numerical rounding (300,000 ≈ 299,792)
          - False Positive: technical aliases (port 80 = TCP port 80)
          - False Negative: date mismatches (1965 ≠ 1969)
          - False Negative: entity mismatches (wrong person/location)
        """
        return f"""You are a strict factual verification judge performing a Chain-of-Verification (CoVe) audit.

## CLAIM TO VERIFY
{claim.strip()}

## GROUND TRUTH (Source Fact)
{source_fact.strip()}

## VERIFICATION RUBRIC — Apply ALL four rules before deciding:

**Rule 1 — Numerical Tolerance (VALID):**
Scientific and common numerical approximations are VALID. If the claim uses a standard rounded value (e.g. "300,000 km/s") and the ground truth gives a precise value (e.g. "299,792 km/s"), treat this as VALID. Do NOT penalise correct rounding.

**Rule 2 — Technical Aliases (VALID):**
Protocol names, technical synonyms, and common abbreviations are interchangeable. Example: "port 80" is identical to "TCP port 80". "HTTP" is identical to "HyperText Transfer Protocol". Do NOT flag technically equivalent terms as hallucinations.

**Rule 3 — Strict Date Audit (HALLUCINATION if wrong):**
4-digit year numbers MUST match the ground truth exactly. If the claim states a different year than the ground truth (e.g. claim says 1965, ground truth says 1969), this is a HALLUCINATION. There is ZERO tolerance for year mismatches.

**Rule 4 — Entity Matching (HALLUCINATION if wrong):**
Proper nouns — person names, city names, country names, organisation names — must align with the ground truth. A wrong person, city, or country is always a HALLUCINATION.

## YOUR TASK
1. Extract every key factual assertion in the CLAIM.
2. Apply Rules 1–4 to each assertion against the GROUND TRUTH.
3. If ALL assertions pass → verdict is VALID.
4. If ANY assertion fails Rules 3 or 4, or makes a factually wrong claim not covered by Rules 1–2 → verdict is HALLUCINATION.

## OUTPUT FORMAT — STRICT JSON ONLY
Respond with ONLY this JSON object. No markdown fences. No text before or after the JSON:

{{
  "status": "VALID" or "HALLUCINATION",
  "reason": "One concise sentence citing which rule was applied and why.",
  "correction": "The corrected factual statement (empty string if VALID)."
}}"""

    # ── Pre-Audit Hard Guard (Regex, Zero GPU Cost) ───────────────────────────

    # Matches 4-digit years: 1000–2099 range covers all historical/modern dates.
    _YEAR_RE = re.compile(r'\b(1[0-9]{3}|20[0-9]{2})\b')

    def _pre_audit_check(self, claim: str, source_fact: str) -> Optional[AuditResult]:
        """
        Regex-based pre-processor. Runs BEFORE any Ollama call (zero GPU cost).

        Enforces:
          - Year mismatch: If a 4-digit year appears in the claim but NOT in
            the ground truth, immediately return HALLUCINATION.
            This catches false negatives (e.g. 1965 vs 1969) with 100% accuracy
            without consuming VRAM or latency.

        Returns:
            AuditResult(caught_by="Pre-Audit") if a violation is found.
            None if clean — proceed to AI audit.
        """
        claim_years = set(self._YEAR_RE.findall(claim))
        truth_years = set(self._YEAR_RE.findall(source_fact))

        # Years present in claim but absent from ground truth are mismatches
        mismatched = claim_years - truth_years
        if mismatched:
            return AuditResult(
                status     = "HALLUCINATION",
                reason     = (
                    f"Year mismatch detected by pre-processor. "
                    f"Claim year(s) {sorted(mismatched)} not found in ground truth "
                    f"(ground truth year(s): {sorted(truth_years) if truth_years else 'none stated'})."
                ),
                correction = "",
                caught_by  = "Pre-Audit",
            )
        return None

    # ── Core Audit ──────────────────────────────────────────────────────────────

    def audit(
        self,
        claim:       str,
        source_fact: str,
        user_prompt: str  = "",
        loop_iter:   int  = 0,
    ) -> AuditResult:
        """
        Run a Chain-of-Verification audit on `claim` against `source_fact`.

        Args:
            claim:       The AI-generated text to be verified.
            source_fact: The authoritative ground-truth context.
            user_prompt: The original user query (for logging only).
            loop_iter:   Which self-correction iteration this is (for logging).

        Returns:
            AuditResult with status, reason, and correction.
        """
        t0 = time.perf_counter()

        # ── Pre-flight checks ────────────────────────────────────────────────
        if not self._is_ollama_running():
            log.error("Ollama is not running. Cannot perform audit.")
            return AuditResult(
                status="ERROR",
                reason="Ollama server is offline. Start it with: ollama serve",
                correction="",
            )

        if not self._is_judge_available():
            log.warning(f"Judge model '{self._judge_model}' not found. Pull it: ollama pull {self._judge_model}")
            return AuditResult(
                status="ERROR",
                reason=f"Judge model {self._judge_model} is not installed.",
                correction="",
            )

        # ── Pre-Audit Hard Guard (regex, zero GPU cost) ──────────────────────
        pre_result = self._pre_audit_check(claim, source_fact)
        if pre_result is not None:
            pre_result.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info(
                f"[Pre-Audit] ⚡ HALLUCINATION caught instantly — {pre_result.reason[:80]}"
            )
            self._db.enqueue(LogEntry(
                timestamp      = datetime.now(timezone.utc).isoformat(),
                user_prompt    = user_prompt,
                ai_response    = claim,
                verdict        = pre_result.status,
                reason         = pre_result.reason,
                correction     = pre_result.correction,
                latency_ms     = pre_result.latency_ms,
                loop_iteration = loop_iter,
            ))
            return pre_result
        # ─────────────────────────────────────────────────────────────────────

        self._guard_vram()

        # ── Call the Judge ───────────────────────────────────────────────────
        prompt = self._build_cove_prompt(claim, source_fact)
        payload = {
            "model":   self._judge_model,
            "prompt":  prompt,
            "stream":  False,
            "options": JUDGE_OPTIONS,
        }

        try:
            response = requests.post(OLLAMA_GENERATE, json=payload, timeout=self._timeout)
            response.raise_for_status()
            raw_text = response.json().get("response", "").strip()
        except requests.exceptions.Timeout:
            log.error(f"Judge timed out after {self._timeout}s.")
            return AuditResult(status="ERROR", reason="Judge model timed out.", correction="")
        except requests.exceptions.ConnectionError:
            log.error("Lost connection to Ollama during audit.")
            return AuditResult(status="ERROR", reason="Ollama connection lost mid-audit.", correction="")
        except Exception as exc:
            log.error(f"Unexpected Ollama error: {exc}")
            return AuditResult(status="ERROR", reason=str(exc), correction="")

        # ── Parse Verdict ────────────────────────────────────────────────────
        result = self._parse_verdict(raw_text)
        result.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        result.model_used = self._judge_model

        log.info(
            f"[Audit] Status={result.status} | Latency={result.latency_ms}ms "
            f"| Loop={loop_iter} | Reason={result.reason[:60]}..."
        )

        # ── Async Log (non-blocking) ─────────────────────────────────────────
        self._db.enqueue(LogEntry(
            timestamp      = datetime.now(timezone.utc).isoformat(),
            user_prompt    = user_prompt,
            ai_response    = claim,
            verdict        = result.status,
            reason         = result.reason,
            correction     = result.correction,
            latency_ms     = result.latency_ms,
            loop_iteration = loop_iter,
        ))

        return result

    def _parse_verdict(self, raw: str) -> AuditResult:
        """
        Robustly extracts JSON from the Judge's raw output.
        Handles cases where the model wraps the JSON in markdown fences.
        """
        # Strip possible markdown fences
        cleaned = raw
        for fence in ("```json", "```JSON", "```"):
            if fence in cleaned:
                cleaned = cleaned.split(fence, 1)[-1].rsplit("```", 1)[0]

        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
            status     = data.get("status", "ERROR").upper()
            reason     = data.get("reason", "No reason provided.")
            correction = data.get("correction", "")

            # Normalise: only accept known statuses
            if status not in ("VALID", "HALLUCINATION"):
                log.warning(f"Unexpected status '{status}' — treating as ERROR.")
                status = "ERROR"

            return AuditResult(status=status, reason=reason, correction=correction)

        except json.JSONDecodeError:
            log.warning(f"Judge returned non-JSON output: {raw[:200]}")
            # Heuristic fallback: keyword scan
            upper = raw.upper()
            if "HALLUCINATION" in upper:
                return AuditResult(
                    status="HALLUCINATION",
                    reason="Judge flagged hallucination (non-JSON response fallback).",
                    correction=raw[:500],
                )
            if "VALID" in upper:
                return AuditResult(
                    status="VALID",
                    reason="Judge confirmed valid (non-JSON response fallback).",
                    correction="",
                )
            return AuditResult(
                status="ERROR",
                reason=f"Judge output unparseable: {raw[:200]}",
                correction="",
            )

    # ── Convenience Helpers ─────────────────────────────────────────────────────

    def recent_logs(self, limit: int = 20) -> list[dict]:
        """Return the most recent audit log entries."""
        return self._db.query_recent(limit)

    def stats(self) -> dict:
        """Return aggregate stats: total, valid, hallucinations, rate, avg latency."""
        return self._db.stats()

    def shutdown(self):
        """Gracefully flush all pending log writes. Call on JARVIS exit."""
        log.info("VibeShield shutting down — flushing log queue...")
        self._db.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
#  ORCHESTRATOR MIDDLEWARE — DROP-IN WRAPPER FOR JARVIS WORKER CALLS
# ══════════════════════════════════════════════════════════════════════════════

def vibe_shield_middleware(
    worker_fn:      Callable[..., str],
    user_prompt:    str,
    source_fact:    str,
    shield:         Optional[VibeShield] = None,
    max_loops:      int = MAX_CORRECTION_LOOPS,
    **worker_kwargs,
) -> dict:
    """
    Drop-in middleware that wraps any JARVIS Worker model call with the
    VibeShield hallucination firewall.

    USAGE — Replace your current worker call:
        # BEFORE
        response = jarvis_brain.ask(prompt)

        # AFTER  (one-liner swap)
        result = vibe_shield_middleware(
            worker_fn   = jarvis_brain.ask,
            user_prompt = prompt,
            source_fact = retrieved_context,   # RAG chunk, tool output, etc.
        )
        response = result["final_response"]

    Args:
        worker_fn:      Any callable that takes user_prompt as first arg and
                        returns a string (the AI's raw response).
        user_prompt:    The original user query.
        source_fact:    Ground-truth context (from RAG, tool result, web search).
                        If empty, the shield uses the prompt itself as context.
        shield:         Optional pre-initialized VibeShield instance.
                        If None, a new instance is created (singleton pattern).
        max_loops:      Maximum self-correction attempts before giving up.
        **worker_kwargs: Extra kwargs forwarded to worker_fn.

    Returns:
        {
            "final_response":  str,   # The verified (or best-effort corrected) response
            "status":          str,   # "VALID" | "HALLUCINATION" | "ERROR"
            "loops":           int,   # How many correction loops were needed
            "audit_trail":     list,  # AuditResult from each loop
            "flagged":         bool,  # True if any loop was HALLUCINATION
        }
    """
    # ── Init shield (lazy singleton) ─────────────────────────────────────────
    _shield = shield or _get_default_shield()

    # Use source_fact if provided; fall back to prompt itself (softer check)
    ground_truth = source_fact.strip() if source_fact.strip() else user_prompt

    audit_trail: list[AuditResult] = []
    current_prompt = user_prompt
    flagged = False

    for loop in range(max_loops + 1):
        # ── Step 1: Call the Worker model ────────────────────────────────────
        log.info(f"[Middleware] Worker call — loop {loop}/{max_loops}")
        try:
            raw_response: str = worker_fn(current_prompt, **worker_kwargs)
        except Exception as exc:
            log.error(f"[Middleware] Worker model threw an exception: {exc}")
            return {
                "final_response": f"Worker model error: {exc}",
                "status":         "ERROR",
                "loops":          loop,
                "audit_trail":    [r.__dict__ for r in audit_trail],
                "flagged":        flagged,
            }

        # ── Step 2: Audit the Worker's output ────────────────────────────────
        verdict: AuditResult = _shield.audit(
            claim       = raw_response,
            source_fact = ground_truth,
            user_prompt = user_prompt,
            loop_iter   = loop,
        )
        audit_trail.append(verdict)

        # ── Step 3: Branch on verdict ─────────────────────────────────────────
        _layer = verdict.caught_by   # "Pre-Audit" or "AI-Audit"

        if verdict.status == "VALID":
            log.info(f"[Middleware] ✅ VALID on loop {loop} [{_layer}].")
            print(
                f"[VibeShield] ✅  VALID     │ [{_layer}] │ Loop {loop} "
                f"│ {verdict.latency_ms:.0f}ms"
            )
            return {
                "final_response": raw_response,
                "status":         "VALID",
                "loops":          loop,
                "caught_by":      _layer,
                "audit_trail":    [r.__dict__ for r in audit_trail],
                "flagged":        flagged,
            }

        if verdict.status == "ERROR":
            # Judge itself failed — pass through without blocking JARVIS
            log.warning("[Middleware] Judge returned ERROR — passing worker response through.")
            print(
                f"[VibeShield] ⚠️  ERROR     │ [{_layer}] │ Loop {loop} "
                f"│ {verdict.latency_ms:.0f}ms │ {verdict.reason[:60]}"
            )
            return {
                "final_response": raw_response,
                "status":         "ERROR",
                "loops":          loop,
                "caught_by":      _layer,
                "audit_trail":    [r.__dict__ for r in audit_trail],
                "flagged":        flagged,
            }

        # ── HALLUCINATION detected ────────────────────────────────────────────
        flagged = True
        _retry_msg = "Retrying..." if loop < max_loops else "Max loops reached — giving up."
        log.warning(
            f"[Middleware] 🚨 HALLUCINATION on loop {loop} [{_layer}] — "
            f"Reason: {verdict.reason[:80]}. {_retry_msg}"
        )
        print(
            f"[VibeShield] 🚨  HALLUCINATION │ [{_layer}] │ Loop {loop} "
            f"│ {verdict.latency_ms:.0f}ms │ {verdict.reason[:60]}"
        )

        if loop >= max_loops:
            # Exhausted retries — return best available with correction note
            best_response = (
                verdict.correction
                if verdict.correction.strip()
                else f"[VibeShield] Response flagged as hallucination after {max_loops} attempts. "
                     f"Reason: {verdict.reason}\n\nLast model output:\n{raw_response}"
            )
            return {
                "final_response": best_response,
                "status":         "HALLUCINATION",
                "loops":          loop,
                "audit_trail":    [r.__dict__ for r in audit_trail],
                "flagged":        True,
            }

        # ── Self-Correction: Re-prompt the Worker with the firewall's reason ──
        current_prompt = _build_correction_prompt(
            original_prompt = user_prompt,
            bad_response    = raw_response,
            reason          = verdict.reason,
            correction_hint = verdict.correction,
            ground_truth    = ground_truth,
        )

    # Should never reach here, but satisfy type checker
    return {
        "final_response": "",
        "status":         "ERROR",
        "loops":          max_loops,
        "audit_trail":    [r.__dict__ for r in audit_trail],
        "flagged":        flagged,
    }


def _build_correction_prompt(
    original_prompt: str,
    bad_response:    str,
    reason:          str,
    correction_hint: str,
    ground_truth:    str,
) -> str:
    """Constructs a self-correction re-prompt for the Worker model."""
    return f"""Your previous response was flagged as INACCURATE by the Vibe-Shield verification system.

## ORIGINAL QUESTION
{original_prompt}

## YOUR PREVIOUS (INCORRECT) RESPONSE
{bad_response}

## WHY IT WAS WRONG
{reason}

## CORRECTION HINT
{correction_hint if correction_hint.strip() else "See the ground truth below and revise."}

## VERIFIED GROUND TRUTH
{ground_truth}

## YOUR TASK
Please provide a corrected, accurate response to the original question.
Stick strictly to the verified ground truth. Do not add unverified information."""


# ── Lazy singleton shield ───────────────────────────────────────────────────────
_default_shield: Optional[VibeShield] = None
_shield_lock = threading.Lock()


def _get_default_shield() -> VibeShield:
    global _default_shield
    if _default_shield is None:
        with _shield_lock:
            if _default_shield is None:
                _default_shield = VibeShield()
    return _default_shield


def get_shield() -> VibeShield:
    """Return the process-level singleton VibeShield instance."""
    return _get_default_shield()
