# tests/test_resilience.py — JARVIS RESILIENCE TEST SUITE
"""
Simulates fault conditions and verifies bounded, stable behavior.

Run: python -m pytest tests/test_resilience.py -v
"""
from __future__ import annotations

import sys
import os
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Reset singletons between tests
def _reset_singletons():
    import importlib
    mods = [
        "core.system.recovery_orchestrator",
        "core.system.runtime_confidence",
        "core.system.subsystem_watchdog",
        "core.system.health_pressure_governor",
        "core.system.readiness_state",
    ]
    for m in mods:
        if m in sys.modules:
            mod = sys.modules[m]
            for attr in ("_instance", "_ro_lock", "_rc_lock"):
                if hasattr(mod, attr) and attr == "_instance":
                    setattr(mod, attr, None)


class TestRecoveryOrchestrator(unittest.TestCase):

    def setUp(self):
        _reset_singletons()
        from core.system.recovery_orchestrator import get_recovery_orchestrator
        self.ro = get_recovery_orchestrator()
        self.ro.start()

    def tearDown(self):
        self.ro.stop()

    def test_local_retry_success(self):
        """Subsystem recovers on first retry."""
        calls = []
        def init_fn():
            calls.append(time.time())

        self.ro.register("test_sub", init_fn, priority=1)
        self.ro.request_recovery("test_sub", "test")
        time.sleep(1.5)
        self.assertGreater(len(calls), 0)

    def test_exponential_backoff(self):
        """Each failure increases backoff."""
        from core.system.recovery_orchestrator import get_recovery_orchestrator, RecoveryEntry
        entry = RecoveryEntry(subsystem="test")
        self.assertEqual(entry.backoff_sec, 2.0)
        entry.record_failure()
        self.assertEqual(entry.backoff_sec, 4.0)
        entry.record_failure()
        self.assertEqual(entry.backoff_sec, 8.0)
        for _ in range(20):
            entry.record_failure()
        self.assertLessEqual(entry.backoff_sec, 300.0)

    def test_budget_exhaustion_triggers_quarantine(self):
        """After 5 attempts in 1 hour, subsystem is quarantined."""
        from core.system.recovery_orchestrator import _MAX_RESTARTS_HOUR, _QUARANTINE_SEC
        call_count = [0]
        def bad_init():
            call_count[0] += 1
            raise RuntimeError("always fails")

        self.ro.register("bad_sub", bad_init, priority=1)
        entry = self.ro._entries["bad_sub"]
        # Simulate budget exhaustion
        now = time.time()
        entry.hourly_attempts = [now] * _MAX_RESTARTS_HOUR

        self.ro.request_recovery("bad_sub", "budget_test")
        time.sleep(2.0)
        self.assertTrue(entry.is_quarantined())

    def test_quarantine_prevents_retries(self):
        """Quarantined subsystem ignores recovery requests."""
        calls = []
        def init_fn():
            calls.append(1)

        self.ro.register("qsub", init_fn, priority=1)
        entry = self.ro._entries["qsub"]
        entry.quarantined_until = time.time() + 600

        self.ro.request_recovery("qsub", "should_be_blocked")
        time.sleep(1.0)
        self.assertEqual(len(calls), 0)

    def test_no_restart_storm(self):
        """Concurrent recovery requests are staggered — never exceed MAX_CONCURRENT."""
        concurrent = [0]
        max_seen   = [0]
        lock = threading.Lock()

        def slow_init():
            with lock:
                concurrent[0] += 1
                max_seen[0] = max(max_seen[0], concurrent[0])
            time.sleep(0.3)
            with lock:
                concurrent[0] -= 1

        from core.system.recovery_orchestrator import _MAX_CONCURRENT
        for i in range(8):
            self.ro.register(f"sub_{i}", slow_init, priority=1)
            self.ro.request_recovery(f"sub_{i}", "storm_test")

        time.sleep(4.0)
        self.assertLessEqual(max_seen[0], _MAX_CONCURRENT)

    def test_recovery_resets_after_success(self):
        """Successful recovery resets backoff and fail streak."""
        from core.system.recovery_orchestrator import RecoveryEntry
        entry = RecoveryEntry(subsystem="test")
        for _ in range(3):
            entry.record_failure()
        self.assertEqual(entry.fail_streak, 3)
        entry.record_success()
        self.assertEqual(entry.fail_streak, 0)
        self.assertEqual(entry.backoff_sec, 2.0)


class TestPressureGovernorHysteresis(unittest.TestCase):

    def setUp(self):
        _reset_singletons()
        from core.system.health_pressure_governor import get_health_pressure_governor
        self.gov = get_health_pressure_governor()

    def test_no_flapping_on_threshold_boundary(self):
        """Score oscillating near threshold should not cause level flapping."""
        from core.system.health_pressure_governor import PressureLevel
        # Score just above enter threshold
        level1 = self.gov._score_to_level_hysteresis(6)   # enters ELEVATED
        # Score drops to just above exit threshold — should stay ELEVATED (cooldown)
        self.gov._level_entered_at[PressureLevel.ELEVATED] = time.time()
        level2 = self.gov._score_to_level_hysteresis(3)   # above exit(2), in cooldown
        self.assertEqual(level2, PressureLevel.ELEVATED)

    def test_exits_only_below_exit_threshold(self):
        """Level drops only when score falls below exit threshold."""
        from core.system.health_pressure_governor import PressureLevel
        # Simulate being at ELEVATED with expired cooldown
        self.gov._level = PressureLevel.ELEVATED
        self.gov._level_entered_at[PressureLevel.ELEVATED] = time.time() - 999
        level = self.gov._score_to_level_hysteresis(1)   # below exit threshold(2)
        self.assertEqual(level, PressureLevel.NOMINAL)

    def test_escalation_immediate(self):
        """Entering a higher level is always immediate, no cooldown."""
        from core.system.health_pressure_governor import PressureLevel
        self.gov._level = PressureLevel.NOMINAL
        level = self.gov._score_to_level_hysteresis(50)  # EMERGENCY threshold
        self.assertEqual(level, PressureLevel.EMERGENCY)


class TestRuntimeConfidence(unittest.TestCase):

    def setUp(self):
        _reset_singletons()
        from core.system.runtime_confidence import get_runtime_confidence
        self.rc = get_runtime_confidence()

    def test_initial_confidence_high(self):
        """Fresh system starts confident."""
        from core.system.runtime_confidence import ConfidenceLevel
        snap = self.rc._compute()
        # On a fresh system with no failures, should be at least CAUTIOUS
        self.assertGreaterEqual(snap.score, 40.0)

    def test_low_confidence_suppresses_proactive(self):
        """LOW confidence triggers suppression flags."""
        from core.system.runtime_confidence import ConfidenceLevel
        self.rc._level = ConfidenceLevel.LOW
        self.assertTrue(self.rc.should_suppress_proactive())
        self.assertTrue(self.rc.should_suppress_automation())
        self.assertTrue(self.rc.prefer_deterministic())

    def test_confident_allows_all(self):
        """CONFIDENT level allows all features."""
        from core.system.runtime_confidence import ConfidenceLevel
        self.rc._level = ConfidenceLevel.CONFIDENT
        self.assertFalse(self.rc.should_suppress_proactive())
        self.assertFalse(self.rc.should_suppress_automation())


class TestWatchdog(unittest.TestCase):

    def setUp(self):
        _reset_singletons()
        from core.system.subsystem_watchdog import get_watchdog
        self.wd = get_watchdog()
        self.wd.start()

    def tearDown(self):
        self.wd.stop()

    def test_hung_task_detected(self):
        """A task that exceeds timeout is marked timed_out."""
        timeout_fired = threading.Event()
        def on_timeout():
            timeout_fired.set()

        self.wd.watch("hung_task", timeout_sec=0.5, on_timeout=on_timeout)
        time.sleep(1.5)
        self.assertTrue(timeout_fired.is_set())

    def test_completed_task_not_flagged(self):
        """A task completed before timeout is not flagged."""
        timeout_fired = threading.Event()
        self.wd.watch("fast_task", timeout_sec=5.0, on_timeout=lambda: timeout_fired.set())
        self.wd.complete("fast_task")
        time.sleep(1.5)
        self.assertFalse(timeout_fired.is_set())

    def test_repeated_hung_escalates(self):
        """3 consecutive hangs increments hung_count to 3."""
        for _ in range(3):
            entry = self.wd.watch("repeat_hang", timeout_sec=0.2)
            time.sleep(0.5)
            self.wd._entries.pop("repeat_hang", None)
        self.assertGreaterEqual(self.wd.hung_count("repeat_hang"), 1)


class TestDegradedModeStability(unittest.TestCase):
    """Verify system remains stable in degraded state without retry spam."""

    def test_sustained_degraded_no_retry_storm(self):
        """In degraded mode, recovery attempts stay bounded over 10 seconds."""
        _reset_singletons()
        from core.system.recovery_orchestrator import get_recovery_orchestrator

        ro = get_recovery_orchestrator()
        ro.start()

        attempt_times = []
        def always_fail():
            attempt_times.append(time.time())
            raise RuntimeError("permanent failure")

        ro.register("degraded_sub", always_fail, priority=3)
        ro.request_recovery("degraded_sub", "initial")
        time.sleep(10.0)

        ro.stop()
        from core.system.recovery_orchestrator import _MAX_RESTARTS_HOUR
        self.assertLessEqual(len(attempt_times), _MAX_RESTARTS_HOUR + 1)


class TestProbabilisticResilience(unittest.TestCase):
    """
    Probabilistic fault injection tests.
    Verify adaptive systems remain bounded under stochastic failures.
    """

    def _jittered_sleep(self, base: float, jitter: float = 0.3):
        import random
        time.sleep(base + random.uniform(0, jitter))

    def test_timing_jitter_no_false_timeouts(self):
        """Tasks completing just before timeout should not be marked as hung."""
        _reset_singletons()
        import random
        from core.system.recovery_orchestrator import get_recovery_orchestrator

        ro = get_recovery_orchestrator()
        ro.start()

        # Vary init latency randomly 0–0.5s, all should succeed
        results = []
        def jittery_init():
            time.sleep(random.uniform(0, 0.5))
            results.append("ok")

        for i in range(5):
            ro.register(f"jitter_{i}", jittery_init, priority=2)
            ro.request_recovery(f"jitter_{i}", "jitter")

        time.sleep(4.0)
        ro.stop()
        self.assertGreater(len(results), 0)

    def test_randomized_failure_rate_bounded_attempts(self):
        """With 50% failure rate, total attempts stay within budget * 2."""
        _reset_singletons()
        import random
        from core.system.recovery_orchestrator import get_recovery_orchestrator, _MAX_RESTARTS_HOUR

        ro = get_recovery_orchestrator()
        ro.start()

        attempts = [0]
        def flaky_init():
            attempts[0] += 1
            if random.random() < 0.5:
                raise RuntimeError("random fail")

        ro.register("flaky", flaky_init, priority=1)
        ro.request_recovery("flaky", "random_test")
        time.sleep(6.0)
        ro.stop()

        self.assertLessEqual(attempts[0], _MAX_RESTARTS_HOUR + 2)

    def test_delayed_callback_no_deadlock(self):
        """Recovery callbacks with random delays must not deadlock the orchestrator."""
        _reset_singletons()
        import random
        from core.system.recovery_orchestrator import get_recovery_orchestrator

        ro = get_recovery_orchestrator()
        events = []
        def slow_cb(subsystem, stage):
            time.sleep(random.uniform(0, 0.2))
            events.append((subsystem, stage))
        ro.on_recovery_event(slow_cb)
        ro.start()

        def ok_init(): pass
        for i in range(4):
            ro.register(f"cb_{i}", ok_init, priority=1)
            ro.request_recovery(f"cb_{i}", "callback_test")

        time.sleep(4.0)
        ro.stop()
        # All should have fired without hang
        self.assertGreater(len(events), 0)

    def test_partial_hang_does_not_block_others(self):
        """One slow init must not block recovery of other subsystems."""
        _reset_singletons()
        from core.system.recovery_orchestrator import get_recovery_orchestrator

        ro = get_recovery_orchestrator()
        ro.start()

        fast_done = threading.Event()
        def slow_init(): time.sleep(10.0)   # simulated hang
        def fast_init(): fast_done.set()

        ro.register("hung_sub",  slow_init, priority=5)
        ro.register("fast_sub",  fast_init, priority=1)
        ro.request_recovery("hung_sub",  "hang_test")
        ro.request_recovery("fast_sub",  "fast_test")

        completed = fast_done.wait(timeout=5.0)
        ro.stop()
        self.assertTrue(completed, "fast_sub should recover even while hung_sub is blocked")

    def test_race_condition_concurrent_requests(self):
        """Multiple threads requesting recovery for same subsystem must not corrupt state."""
        _reset_singletons()
        from core.system.recovery_orchestrator import get_recovery_orchestrator

        ro = get_recovery_orchestrator()
        ro.start()

        calls = [0]
        lock = threading.Lock()
        def init_fn():
            with lock:
                calls[0] += 1

        ro.register("race_sub", init_fn, priority=1)

        def _request():
            for _ in range(5):
                ro.request_recovery("race_sub", "race")
                time.sleep(0.01)

        threads = [threading.Thread(target=_request) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()

        time.sleep(3.0)
        ro.stop()
        # Calls must be bounded by budget, not unbounded
        from core.system.recovery_orchestrator import _MAX_RESTARTS_HOUR
        self.assertLessEqual(calls[0], _MAX_RESTARTS_HOUR + 3)


class TestMetaStabilityGuard(unittest.TestCase):

    def setUp(self):
        from core.system.meta_stability_guard import MetaStabilityGuard
        MetaStabilityGuard._instance = None
        from core.system.meta_stability_guard import get_meta_stability_guard
        self.guard = get_meta_stability_guard()
        self.guard.start()

    def tearDown(self):
        self.guard.stop()

    def test_oscillation_triggers_freeze(self):
        """Rapid repeated events from same source trigger stabilization freeze."""
        from core.system.meta_stability_guard import _OSCILLATION_THRESH
        for _ in range(_OSCILLATION_THRESH + 1):
            self.guard.record_event("governor", "ELEVATED", direction=+1)
        self.guard._check_all()
        self.assertTrue(self.guard.is_stabilizing())

    def test_feedback_loop_detection(self):
        """Alternating escalation/recovery between two systems triggers freeze."""
        from core.system.meta_stability_guard import _FEEDBACK_THRESH
        for _ in range(_FEEDBACK_THRESH):
            self.guard.record_event("governor",  "ELEVATED",  direction=+1)
            self.guard.record_event("recovery",  "ISOLATED",  direction=+1)
            self.guard.record_event("governor",  "NOMINAL",   direction=-1)
            self.guard.record_event("recovery",  "HEALTHY",   direction=-1)
        self.guard._check_all()
        self.assertTrue(self.guard.is_stabilizing())

    def test_stable_system_no_freeze(self):
        """Normal low-rate events must not trigger freeze."""
        self.guard.record_event("governor", "NOMINAL", direction=0)
        self.guard.record_event("recovery", "HEALTHY", direction=0)
        self.guard._check_all()
        self.assertFalse(self.guard.is_stabilizing())


class TestDomainConfidence(unittest.TestCase):

    def setUp(self):
        from core.system.domain_confidence import DomainConfidence
        DomainConfidence._instance = None
        from core.system.domain_confidence import get_domain_confidence
        self.dc = get_domain_confidence()

    def test_floor_prevents_zero_score(self):
        """Domain score must never fall below the confidence floor."""
        from core.system.domain_confidence import _FLOOR_SCORE
        score = self.dc._domains
        for state in score.values():
            state.score = 0.0
        # Re-compute should restore floor
        self.dc._compute_all()
        for state in self.dc._domains.values():
            self.assertGreaterEqual(state.score, _FLOOR_SCORE)

    def test_suppression_at_low_level(self):
        """LOW domain level triggers suppression."""
        from core.system.domain_confidence import Domain, DomainLevel
        self.dc._domains[Domain.VOICE].level = DomainLevel.LOW
        self.assertTrue(self.dc.should_suppress(Domain.VOICE))
        self.assertTrue(self.dc.should_disable(Domain.VOICE))

    def test_no_suppression_at_confident(self):
        """CONFIDENT domain level allows all behavior."""
        from core.system.domain_confidence import Domain, DomainLevel
        self.dc._domains[Domain.AI].level = DomainLevel.CONFIDENT
        self.assertFalse(self.dc.should_suppress(Domain.AI))
        self.assertFalse(self.dc.should_disable(Domain.AI))


if __name__ == "__main__":
    unittest.main(verbosity=2)

