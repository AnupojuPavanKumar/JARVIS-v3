# tests/test_vibe_shield.py — VibeShield Smoke Test
# ══════════════════════════════════════════════════════════════════════════════
#  Run with:  python -m pytest tests/test_vibe_shield.py -v
#  OR standalone:  python tests/test_vibe_shield.py
#
#  Tests covered:
#    1. VibeShield class instantiates cleanly
#    2. Async SQLite logger creates DB and writes rows
#    3. CoVe prompt builder produces correct structure
#    4. Verdict parser handles valid JSON, hallucination JSON, bad JSON
#    5. vibe_shield_middleware passes VALID responses through unchanged
#    6. Middleware triggers self-correction loop on HALLUCINATION
#    7. Middleware respects max_loops ceiling
#    8. Stats & recent_logs queries return correct shape
#    9. Graceful degradation when Ollama is offline (mock)
# ══════════════════════════════════════════════════════════════════════════════

import json
import os
import sys
import time
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Keep standalone script output working on Windows cp1252 consoles.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Ensure project root is on path when run standalone ───────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.system.security import (
    VibeShield,
    AuditResult,
    _AsyncSQLiteLogger,
    LogEntry,
    vibe_shield_middleware,
    _build_correction_prompt,
)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _tmp_db() -> str:
    """Return a unique temp DB path for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="vibe_test_")
    os.close(fd)
    return path


def _make_shield(db_path: str) -> VibeShield:
    return VibeShield(judge_model="gemma2:9b", db_path=db_path)


# ══════════════════════════════════════════════════════════════════════════════
#  TEST: AsyncSQLiteLogger
# ══════════════════════════════════════════════════════════════════════════════

class TestAsyncSQLiteLogger(unittest.TestCase):

    def setUp(self):
        self.db_path = _tmp_db()
        self.logger  = _AsyncSQLiteLogger(self.db_path)

    def tearDown(self):
        self.logger.shutdown()
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_db_created(self):
        """DB file must exist after logger init."""
        self.assertTrue(os.path.exists(self.db_path))

    def test_enqueue_and_persist(self):
        """Enqueued entry must appear in DB after queue drain."""
        entry = LogEntry(
            timestamp="2026-01-01T00:00:00+00:00",
            user_prompt="test prompt",
            ai_response="test response",
            verdict="VALID",
            reason="All good.",
            correction="",
            latency_ms=123.4,
            loop_iteration=0,
        )
        self.logger.enqueue(entry)
        self.logger._queue.join()   # block until written

        rows = self.logger.query_recent(limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "VALID")
        self.assertEqual(rows[0]["user_prompt"], "test prompt")

    def test_stats_correct(self):
        """Stats must count verdicts correctly."""
        for verdict in ("VALID", "VALID", "HALLUCINATION"):
            self.logger.enqueue(LogEntry(
                timestamp="2026-01-01T00:00:00+00:00",
                user_prompt="q", ai_response="a",
                verdict=verdict, reason="r", correction="",
                latency_ms=0, loop_iteration=0,
            ))
        self.logger._queue.join()

        s = self.logger.stats()
        self.assertEqual(s["total_audits"],   3)
        self.assertEqual(s["valid"],          2)
        self.assertEqual(s["hallucinations"], 1)
        self.assertAlmostEqual(s["hallucination_rate"], 33.33, places=1)


# ══════════════════════════════════════════════════════════════════════════════
#  TEST: VibeShield — prompt builder & verdict parser (no Ollama needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestVibeShieldOffline(unittest.TestCase):

    def setUp(self):
        self.db_path = _tmp_db()
        self.shield  = _make_shield(self.db_path)

    def tearDown(self):
        self.shield.shutdown()
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    # ── CoVe Prompt Builder ──────────────────────────────────────────────────

    def test_cove_prompt_contains_claim(self):
        prompt = self.shield._build_cove_prompt("Paris is the capital of France.", "Paris is France's capital.")
        self.assertIn("Paris is the capital of France.", prompt)
        self.assertIn("GROUND TRUTH", prompt)
        self.assertIn('"status"', prompt)

    def test_cove_prompt_contains_json_schema(self):
        prompt = self.shield._build_cove_prompt("claim", "fact")
        self.assertIn('"correction"', prompt)
        self.assertIn("VALID", prompt)
        self.assertIn("HALLUCINATION", prompt)

    # ── Verdict Parser — happy path ──────────────────────────────────────────

    def test_parse_valid_json_valid(self):
        raw = json.dumps({"status": "VALID", "reason": "Correct.", "correction": ""})
        result = self.shield._parse_verdict(raw)
        self.assertEqual(result.status, "VALID")
        self.assertEqual(result.reason, "Correct.")
        self.assertEqual(result.correction, "")

    def test_parse_valid_json_hallucination(self):
        raw = json.dumps({
            "status": "HALLUCINATION",
            "reason": "Wrong height.",
            "correction": "330 meters."
        })
        result = self.shield._parse_verdict(raw)
        self.assertEqual(result.status, "HALLUCINATION")
        self.assertEqual(result.correction, "330 meters.")

    # ── Verdict Parser — markdown-fenced JSON ────────────────────────────────

    def test_parse_fenced_json(self):
        raw = "```json\n" + json.dumps({"status": "VALID", "reason": "OK", "correction": ""}) + "\n```"
        result = self.shield._parse_verdict(raw)
        self.assertEqual(result.status, "VALID")

    # ── Verdict Parser — bad JSON fallback ──────────────────────────────────

    def test_parse_bad_json_hallucination_keyword(self):
        result = self.shield._parse_verdict("This is clearly a HALLUCINATION detected.")
        self.assertEqual(result.status, "HALLUCINATION")

    def test_parse_bad_json_valid_keyword(self):
        result = self.shield._parse_verdict("The response is VALID and accurate.")
        self.assertEqual(result.status, "VALID")

    def test_parse_completely_unparseable(self):
        result = self.shield._parse_verdict("¯\\_(ツ)_/¯ no idea mate")
        self.assertEqual(result.status, "ERROR")

    def test_parse_unknown_status_normalised_to_error(self):
        raw = json.dumps({"status": "UNCERTAIN", "reason": "dunno", "correction": ""})
        result = self.shield._parse_verdict(raw)
        self.assertEqual(result.status, "ERROR")


# ══════════════════════════════════════════════════════════════════════════════
#  TEST: vibe_shield_middleware — mocked Ollama
# ══════════════════════════════════════════════════════════════════════════════

class TestMiddleware(unittest.TestCase):

    def setUp(self):
        self.db_path = _tmp_db()
        self.shield  = _make_shield(self.db_path)

    def tearDown(self):
        self.shield.shutdown()
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def _mock_audit(self, status: str, reason: str = "test", correction: str = "") -> AuditResult:
        return AuditResult(status=status, reason=reason, correction=correction, latency_ms=1.0)

    def test_valid_response_passes_through(self):
        """VALID verdict → middleware returns original worker response unchanged."""
        worker = MagicMock(return_value="The sky is blue.")
        self.shield.audit = MagicMock(return_value=self._mock_audit("VALID"))

        result = vibe_shield_middleware(
            worker_fn   = worker,
            user_prompt = "What colour is the sky?",
            source_fact = "The sky is blue.",
            shield      = self.shield,
            max_loops   = 3,
        )
        self.assertEqual(result["status"],         "VALID")
        self.assertEqual(result["final_response"], "The sky is blue.")
        self.assertFalse(result["flagged"])
        self.assertEqual(result["loops"],          0)

    def test_hallucination_triggers_correction_loop(self):
        """HALLUCINATION on loop 0 → worker called twice (once to correct)."""
        call_count = [0]

        def fake_worker(prompt, **_kw):
            call_count[0] += 1
            return "corrected answer" if call_count[0] > 1 else "wrong answer"

        # Loop 0 → HALLUCINATION, Loop 1 → VALID
        audit_responses = [
            self._mock_audit("HALLUCINATION", "Wrong.", "corrected answer"),
            self._mock_audit("VALID"),
        ]
        self.shield.audit = MagicMock(side_effect=audit_responses)

        result = vibe_shield_middleware(
            worker_fn   = fake_worker,
            user_prompt = "What is X?",
            source_fact = "X is correct.",
            shield      = self.shield,
            max_loops   = 3,
        )
        self.assertEqual(result["status"],  "VALID")
        self.assertTrue(result["flagged"])
        self.assertEqual(result["loops"],   1)
        self.assertEqual(call_count[0],     2)

    def test_max_loops_ceiling_respected(self):
        """If hallucination persists past max_loops, middleware gives up gracefully."""
        worker = MagicMock(return_value="still wrong")
        self.shield.audit = MagicMock(return_value=self._mock_audit(
            "HALLUCINATION", "Wrong.", "The correction."
        ))

        result = vibe_shield_middleware(
            worker_fn   = worker,
            user_prompt = "Q",
            source_fact = "A",
            shield      = self.shield,
            max_loops   = 2,
        )
        self.assertEqual(result["status"],  "HALLUCINATION")
        self.assertTrue(result["flagged"])
        self.assertEqual(result["loops"],   2)
        # Worker called max_loops+1 times (initial + 2 corrections)
        self.assertEqual(worker.call_count, 3)

    def test_error_verdict_passes_through_without_blocking(self):
        """ERROR from judge → response passes through, JARVIS not blocked."""
        worker = MagicMock(return_value="some answer")
        self.shield.audit = MagicMock(return_value=self._mock_audit("ERROR", "Ollama offline."))

        result = vibe_shield_middleware(
            worker_fn   = worker,
            user_prompt = "Q",
            source_fact = "A",
            shield      = self.shield,
        )
        self.assertEqual(result["status"],         "ERROR")
        self.assertEqual(result["final_response"], "some answer")
        self.assertFalse(result["flagged"])

    def test_worker_exception_returns_error_dict(self):
        """If worker itself throws, middleware returns error dict, never crashes."""
        def bad_worker(prompt, **_kw):
            raise RuntimeError("model crashed")

        result = vibe_shield_middleware(
            worker_fn   = bad_worker,
            user_prompt = "Q",
            source_fact = "A",
            shield      = self.shield,
        )
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("model crashed", result["final_response"])

    def test_audit_trail_populated(self):
        """audit_trail must have one entry per loop."""
        audit_responses = [
            self._mock_audit("HALLUCINATION", "Wrong."),
            self._mock_audit("VALID"),
        ]
        self.shield.audit = MagicMock(side_effect=audit_responses)
        worker = MagicMock(return_value="answer")

        result = vibe_shield_middleware(
            worker_fn   = worker,
            user_prompt = "Q",
            source_fact = "A",
            shield      = self.shield,
            max_loops   = 3,
        )
        self.assertEqual(len(result["audit_trail"]), 2)


# ══════════════════════════════════════════════════════════════════════════════
#  TEST: Graceful degradation — Ollama offline
# ══════════════════════════════════════════════════════════════════════════════

class TestOllamaOffline(unittest.TestCase):

    def setUp(self):
        self.db_path = _tmp_db()

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_audit_returns_error_when_ollama_down(self):
        """audit() must return ERROR gracefully when Ollama is unreachable."""
        shield = _make_shield(self.db_path)
        with patch.object(shield, "_is_ollama_running", return_value=False):
            result = shield.audit(claim="anything", source_fact="fact")
        self.assertEqual(result.status, "ERROR")
        self.assertIn("Ollama", result.reason)
        shield.shutdown()

    def test_audit_returns_error_when_judge_missing(self):
        """audit() must return ERROR gracefully when gemma2:9b not installed."""
        shield = _make_shield(self.db_path)
        with patch.object(shield, "_is_ollama_running", return_value=True), \
             patch.object(shield, "_is_judge_available", return_value=False):
            result = shield.audit(claim="anything", source_fact="fact")
        self.assertEqual(result.status, "ERROR")
        self.assertIn("gemma2", result.reason)
        shield.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
#  TEST: Correction prompt builder
# ══════════════════════════════════════════════════════════════════════════════

class TestCorrectionPrompt(unittest.TestCase):

    def test_contains_all_components(self):
        prompt = _build_correction_prompt(
            original_prompt = "Who wrote Hamlet?",
            bad_response    = "Beethoven wrote Hamlet.",
            reason          = "Beethoven was a composer, not a playwright.",
            correction_hint = "Shakespeare wrote Hamlet.",
            ground_truth    = "Hamlet was written by William Shakespeare.",
        )
        self.assertIn("Who wrote Hamlet?",           prompt)
        self.assertIn("Beethoven wrote Hamlet.",      prompt)
        self.assertIn("Beethoven was a composer",     prompt)
        self.assertIn("Shakespeare wrote Hamlet.",    prompt)
        self.assertIn("William Shakespeare",          prompt)


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT (standalone run)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  🛡️  VIBE-SHIELD SMOKE TEST")
    print("=" * 70)
    unittest.main(verbosity=2)
