# core/system/boot_orchestrator.py — JARVIS 4-PHASE STAGED BOOT
"""
Staged initialization — each phase runs without blocking the UI thread.

Phase 1 (<150ms): UI shell only — window, animation, minimal signals
Phase 2 (<300ms): Core runtime — event bus, execution queue, fast router, lightweight managers
Phase 3 (background): Background services — memory systems, trust, fatigue, continuity, observers
Phase 4 (background, on idle): Heavy systems — Ollama, Vosk, wake-word, model prewarming

Rules:
  - NOTHING blocks the UI thread
  - Heavy systems always initialize in background threads
  - Subsystems mark their own readiness via ReadinessTracker
  - UI can query readiness at any time
  - Failed subsystems don't block boot
"""
from __future__ import annotations

import threading
import time
import logging
import traceback
from typing import Callable, Optional

from core.system.cancellation_token import CancellationToken
from core.system.runtime_lifecycle import get_runtime_lifecycle
from core.system.subsystem_watchdog import get_watchdog
from core.system.capability_validator import get_capability_validator
from core.system.health_pressure_governor import get_health_pressure_governor

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QApplication = None

log = logging.getLogger("BootOrchestrator")


def _build_orchestrator():
    """Build and wire CommandOrchestrator on the calling thread (not UI thread)."""
    from core.system.service_registry import get_service_registry
    registry = get_service_registry()
    app = QApplication.instance() if QApplication else None
    ui = getattr(app, '_ui', None) if app else None

    id_manager = _get_id_manager()
    # Import here to avoid circular import — CommandOrchestrator lives in main.py
    import main as _main_module
    orch = _main_module.CommandOrchestrator(id_manager.identity, ui)

    registry.register("orchestrator_service", orch)
    registry.register("worker", orch)
    registry.mark_ready("worker")

    if ui:
        orch.status_signal.connect(ui.set_status)
        orch.result_signal.connect(ui.set_result)

        from core.engines.speech_engine import get_speech_engine
        from core.engines.speech_dispatcher import get_speech_dispatcher
        speech = get_speech_engine()
        get_speech_dispatcher().set_engine(speech)

        def handle_speech(text: str):
            if not text:
                return
            if hasattr(ui, 'set_speaking'):
                app._main_loop.call_soon_threadsafe(lambda: ui.set_speaking(True))

            def _speak():
                speech.speak(text)
                if hasattr(ui, 'set_speaking'):
                    app._main_loop.call_soon_threadsafe(lambda: ui.set_speaking(False))

            threading.Thread(target=_speak, daemon=True, name="SpeechOut").start()

        if hasattr(ui, 'request_speak_signal'):
            ui.request_speak_signal.connect(handle_speech)
            
        if hasattr(ui, 'command_requested_signal'):
            ui.command_requested_signal.connect(lambda cmd: orch.submit_command(cmd, source="ui"))
        elif hasattr(ui, 'command_submitted'):
            ui.command_submitted.connect(lambda cmd: orch.submit_command(cmd, source="ui"))
            
        if hasattr(ui, 'shutdown_signal'):
            ui.shutdown_signal.connect(app.quit)

    return orch


def _get_id_manager():
    from identity.identity_manager import IdentityManager
    return IdentityManager()


class BootPhase:
    PHASE1_SHELL     = 1
    PHASE2_CORE      = 2
    PHASE3_BACKGROUND = 3
    PHASE4_HEAVY     = 4


class BootOrchestrator:
    """
    Manages staged JARVIS boot — each phase returns quickly, heavy work
    is dispatched to background threads.
    """

    def __init__(self, app=None, ui=None):
        self._app    = app
        self._ui     = ui
        self._phase  = 0
        self._done   = False
        self._lock   = threading.RLock()
        self._phase_done: dict[int, threading.Event] = {
            1: threading.Event(), 2: threading.Event(),
            3: threading.Event(), 4: threading.Event(),
        }
        self._phase_start: dict[int, float] = {}
        self._phase_durations: dict[int, float] = {}

        from core.system.readiness_state import get_readiness_tracker
        self._ready = get_readiness_tracker()

    def _boot_phase1(self):
        """Phase 1: UI Shell — render window, animation, minimal signals only."""
        t0 = time.perf_counter()
        self._phase = 1
        self._ready.set_phase(1)
        self._phase_start[1] = t0
        log.info("[Boot] Phase 1: UI shell")

        self._phase_durations[1] = (time.perf_counter() - t0) * 1000
        self._phase_done[1].set()
        log.info(f"[Boot] Phase 1 complete in {self._phase_durations[1]:.1f}ms")

    def _boot_phase2(self):
        """Phase 2: Core Runtime — event bus, execution queue, fast router."""
        t0 = time.perf_counter()
        self._phase = 2
        self._ready.set_phase(2)
        self._phase_start[2] = t0
        log.info("[Boot] Phase 2: Core runtime")

        try:
            self._ready.mark_initializing("event_bus")
            from core.system.event_bus import get_event_bus
            get_event_bus()
            self._ready.mark_ready("event_bus")
        except Exception as e:
            log.error(f"[Boot] event_bus failed: {e}")
            self._ready.mark_failed("event_bus", str(e))

        try:
            self._ready.mark_initializing("execution_queue")
            from core.executor.execution_queue import get_execution_queue
            q = get_execution_queue()
            q.start()
            self._ready.mark_ready("execution_queue")
        except Exception as e:
            log.error(f"[Boot] execution_queue failed: {e}")
            self._ready.mark_failed("execution_queue", str(e))

        try:
            self._ready.mark_initializing("fast_router")
            from core.router.fast_router import FastRouter
            FastRouter()  # singleton init
            self._ready.mark_ready("fast_router")
        except Exception as e:
            log.error(f"[Boot] fast_router failed: {e}")
            self._ready.mark_failed("fast_router", str(e))

        try:
            self._ready.mark_initializing("deterministic_executor")
            from core.executor.deterministic_executor import get_executor
            get_executor()
            self._ready.mark_ready("deterministic_executor")
        except Exception as e:
            log.error(f"[Boot] deterministic_executor failed: {e}")
            self._ready.mark_failed("deterministic_executor", str(e))

        # CommandOrchestrator + JarvisBrain — the core command processing pipeline
        try:
            if CancellationToken.cancelled():
                log.warning("[Boot] Cancelled — skipping command_orchestrator")
                return
            self._ready.mark_initializing("command_orchestrator")
            from core.agent.jarvis_brain import JarvisBrain
            from core.system.service_registry import get_service_registry
            registry = get_service_registry()

            orch = _build_orchestrator()
            self._orchestrator = orch
            orch.status_signal.connect(self._on_status_update)
            orch.result_signal.connect(self._on_result_update)
            orch.start()
            registry.register("worker", orch)
            registry.mark_ready("worker")
            self._ready.mark_ready("command_orchestrator")
        except Exception as e:
            log.error(f"[Boot] command_orchestrator failed: {e}")
            self._ready.mark_failed("command_orchestrator", str(e))

        self._phase_durations[2] = (time.perf_counter() - t0) * 1000
        self._phase_done[2].set()
        log.info(f"[Boot] Phase 2 complete in {self._phase_durations[2]:.1f}ms")

    def _on_status_update(self, status: str):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and hasattr(app, '_ui'):
                self._ui_ref().set_status(status)
        except Exception:
            pass

    def _on_result_update(self, result: str):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and hasattr(app, '_ui'):
                self._ui_ref().set_result(result)
        except Exception:
            pass

    def _ui_ref(self):
        return self._ui or getattr(QApplication.instance(), '_ui', None)

    def _boot_phase3(self):
        """Phase 3: Background services — all companion/memory systems."""
        t0 = time.perf_counter()
        self._phase = 3
        self._ready.set_phase(3)
        self._phase_start[3] = t0
        log.info("[Boot] Phase 3: Background services")

        services = [
            ("checkpoint_manager", "core.companion.checkpoint", "get_checkpoint"),
            ("session_continuity", "core.companion.session_memory", "get_session_continuity"),
            ("phrase_rotation", "core.companion.phrase_rotation", "get_rotator"),
            ("cognitive_continuity", "core.companion.cognitive_continuity", "get_cognitive_continuity"),
            ("cognitive_compression", "core.companion.cognitive_compression", "get_cognitive_compressor"),
            ("fatigue_model", "core.companion.fatigue_model", "get_fatigue_model"),
            ("graceful_degradation", "core.companion.graceful_degradation", "get_graceful_degradation"),
            ("trust_model", "core.companion.trust_model", "get_trust_model"),
            ("domain_trust", "core.companion.domain_trust", "get_domain_trust"),
            ("frustration_detector", "core.companion.frustration_detector", "get_frustration_detector"),
            ("behavior_drift", "core.companion.behavior_drift", "get_behavior_drift"),
            ("layered_memory", "core.companion.layered_memory", "get_layered_memory"),
            ("interaction_closure", "core.companion.interaction_closure", "get_interaction_closure"),
            ("confidence_rhythm", "core.companion.confidence_rhythm", "get_confidence_rhythm"),
            ("calm_engine", "core.companion.calm_engine", "get_calm_engine"),
            ("recovery_engine", "core.companion.recovery", "get_recovery_engine"),
        ]

        for sub_name, module_path, fn_name in services:
            if CancellationToken.cancelled():
                log.warning(f"[Boot] Cancelled — abandoning Phase 3 at '{sub_name}'")
                self._phase_done[3].set()
                return
            try:
                self._ready.mark_initializing(sub_name)
                mod = __import__(module_path, fromlist=[fn_name])
                getattr(mod, fn_name)()
                self._ready.mark_ready(sub_name)
            except Exception as e:
                log.error(f"[Boot] {sub_name} failed: {e}")
                self._ready.mark_failed(sub_name, str(e))

        if CancellationToken.cancelled():
            self._phase_done[3].set()
            return

        try:
            self._ready.mark_initializing("workspace_observer")
            from core.context.workspace import get_workspace_observer
            ws = get_workspace_observer()
            ws.start()
            self._ready.mark_ready("workspace_observer")
        except Exception as e:
            log.error(f"[Boot] workspace_observer failed: {e}")
            self._ready.mark_failed("workspace_observer", str(e))

        # Hardware telemetry — non-blocking, spawns daemon thread internally
        try:
            self._ready.mark_initializing("hardware_sentinel")
            from core.system.hardware_sentinel import HardwareSentinel
            from core.system.service_registry import get_service_registry
            registry = get_service_registry()
            sentinel = HardwareSentinel()
            registry.register("hardware_sentinel", sentinel)
            sentinel.start()
            self._ready.mark_ready("hardware_sentinel")
        except Exception as e:
            log.error(f"[Boot] hardware_sentinel failed: {e}")
            self._ready.mark_failed("hardware_sentinel", str(e))

        try:
            self._ready.mark_initializing("suggestion_engine")
            from core.context.suggestions import get_suggestion_engine
            se = get_suggestion_engine()

            def _on_suggestion(text: str):
                try:
                    from core.agent.telemetry_service import get_telemetry_service
                    get_telemetry_service().on_proactive_suggestion(text)
                except Exception:
                    pass

            se.start(callback=_on_suggestion)
            self._ready.mark_ready("suggestion_engine")
        except Exception as e:
            log.error(f"[Boot] suggestion_engine failed: {e}")
            self._ready.mark_failed("suggestion_engine", str(e))

        # Resilience subsystems: watchdog, capability validator, pressure governor
        try:
            self._ready.mark_initializing("watchdog")
            wd = get_watchdog()
            wd.start()
            self._ready.mark_ready("watchdog")
        except Exception as e:
            log.error(f"[Boot] watchdog failed: {e}")
            self._ready.mark_failed("watchdog", str(e))

        try:
            self._ready.mark_initializing("capability_validator")
            cv = get_capability_validator()
            cv.register_socket_probe("ollama", "127.0.0.1", 11434, timeout=1.0)
            cv.start()
            self._ready.mark_ready("capability_validator")
        except Exception as e:
            log.error(f"[Boot] capability_validator failed: {e}")
            self._ready.mark_failed("capability_validator", str(e))

        try:
            self._ready.mark_initializing("pressure_governor")
            gov = get_health_pressure_governor()

            def _on_mitigation(level, action):
                log.warning(f"[HealthGovernor] Mitigation: {action} at {level.name}")

            gov.on_mitigation(_on_mitigation)
            gov.start()
            self._ready.mark_ready("pressure_governor")
        except Exception as e:
            log.error(f"[Boot] pressure_governor failed: {e}")
            self._ready.mark_failed("pressure_governor", str(e))

        # Recovery orchestrator
        try:
            self._ready.mark_initializing("recovery_orchestrator")
            from core.system.recovery_orchestrator import get_recovery_orchestrator
            ro = get_recovery_orchestrator()
            ro.start()
            self._ready.mark_ready("recovery_orchestrator")
        except Exception as e:
            log.error(f"[Boot] recovery_orchestrator failed: {e}")
            self._ready.mark_failed("recovery_orchestrator", str(e))

        # Meta-stability guard
        try:
            self._ready.mark_initializing("meta_stability_guard")
            from core.system.meta_stability_guard import get_meta_stability_guard
            guard = get_meta_stability_guard()
            guard.start()
            self._ready.mark_ready("meta_stability_guard")
        except Exception as e:
            log.error(f"[Boot] meta_stability_guard failed: {e}")
            self._ready.mark_failed("meta_stability_guard", str(e))

        # Domain confidence
        try:
            self._ready.mark_initializing("domain_confidence")
            from core.system.domain_confidence import get_domain_confidence
            dc = get_domain_confidence()
            dc.start()
            self._ready.mark_ready("domain_confidence")
        except Exception as e:
            log.error(f"[Boot] domain_confidence failed: {e}")
            self._ready.mark_failed("domain_confidence", str(e))

        # Runtime confidence model
        try:
            self._ready.mark_initializing("runtime_confidence")
            from core.system.runtime_confidence import get_runtime_confidence
            rc = get_runtime_confidence()
            rc.on_change(lambda level, score: log.info(f"[Confidence] Level={level.name} score={score:.1f}"))
            rc.start()
            self._ready.mark_ready("runtime_confidence")
        except Exception as e:
            log.error(f"[Boot] runtime_confidence failed: {e}")
            self._ready.mark_failed("runtime_confidence", str(e))

        # Equilibrium monitor
        try:
            self._ready.mark_initializing("equilibrium_monitor")
            from core.system.equilibrium_monitor import get_equilibrium_monitor, Trajectory
            em = get_equilibrium_monitor()
            def _on_trajectory(traj, snap):
                if traj in (Trajectory.DETERIORATING, Trajectory.CRITICAL):
                    try:
                        from core.system.runtime_explainability import get_runtime_explainability
                        get_runtime_explainability().equilibrium_warn(
                            traj.name, snap.confidence_slope, snap.churn_rate
                        )
                    except Exception:
                        pass
            em.on_trajectory_change(_on_trajectory)
            em.start()
            self._ready.mark_ready("equilibrium_monitor")
        except Exception as e:
            log.error(f"[Boot] equilibrium_monitor failed: {e}")
            self._ready.mark_failed("equilibrium_monitor", str(e))

        # Degradation persona — wire speech engine after boot
        try:
            self._ready.mark_initializing("degradation_persona")
            from core.system.degradation_persona import get_degradation_persona
            dp = get_degradation_persona()
            try:
                from core.engines.speech_engine import get_speech_engine
                dp.set_speak_callback(get_speech_engine().speak)
            except Exception:
                pass
            self._ready.mark_ready("degradation_persona")
        except Exception as e:
            log.error(f"[Boot] degradation_persona failed: {e}")
            self._ready.mark_failed("degradation_persona", str(e))



        # Functional capability probes (Ollama AI + socket)
        try:
            cv = get_capability_validator()
            # Functional AI probe: tiny inference call
            def _ollama_fn_probe() -> bool:
                try:
                    import urllib.request, json as _json
                    req = urllib.request.Request(
                        "http://127.0.0.1:11434/api/generate",
                        data=_json.dumps({"model": "llama3.2:3b", "prompt": "hi", "max_tokens": 1, "stream": False}).encode(),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status == 200
                except Exception:
                    return False
            cv.register_function_probe("ollama_inference", _ollama_fn_probe, timeout_sec=8.0)

            # TTS smoke probe: check engine is responsive
            def _tts_probe() -> bool:
                try:
                    from core.engines.speech_engine import get_speech_engine
                    eng = get_speech_engine()
                    return eng is not None and hasattr(eng, 'speak')
                except Exception:
                    return False
            cv.register_function_probe("tts", _tts_probe, timeout_sec=3.0)
        except Exception as e:
            log.error(f"[Boot] functional probes failed: {e}")

        self._phase_durations[3] = (time.perf_counter() - t0) * 1000
        self._phase_done[3].set()
        log.info(f"[Boot] Phase 3 complete in {self._phase_durations[3]:.1f}ms")


    def _boot_phase4(self):
        """Phase 4: Heavy systems — Ollama, Vosk, wake-word, model warmup."""
        if CancellationToken.cancelled():
            log.warning("[Boot] Cancelled — skipping Phase 4")
            self._phase_done[4].set()
            return
        t0 = time.perf_counter()
        self._phase = 4
        self._ready.set_phase(4)
        self._phase_start[4] = t0
        log.info("[Boot] Phase 4: Heavy systems")

        # Ollama manager — non-blocking async probe
        try:
            self._ready.mark_initializing("ollama_manager")
            from core.providers.ollama_manager import get_ollama_manager
            _ollama = get_ollama_manager()

            def _on_ready():
                log.info("[Boot] Ollama ONLINE")
                self._ready.mark_ready("ollama_manager")
                try:
                    from PyQt6.QtWidgets import QApplication
                    app = QApplication.instance()
                    if app and hasattr(app, '_ui') and hasattr(app._ui, '_dot_ollama'):
                        def _u():
                            app._ui._dot_ollama.set("ONLINE", True)
                        from PyQt6.QtCore import QTimer
                        QTimer.singleShot(0, _u)
                except Exception:
                    pass

            def _on_fail():
                log.warning("[Boot] Ollama OFFLINE — degraded mode")
                self._ready.mark_degraded("ollama_manager", "Ollama not available")

            _ollama.ensure_running_async(on_ready=_on_ready, on_fail=_on_fail)
        except Exception as e:
            log.error(f"[Boot] ollama_manager init failed: {e}")
            self._ready.mark_failed("ollama_manager", str(e))

        # Model prewarmer — background thread
        try:
            self._ready.mark_initializing("model_prewarmer")
            from core.agent.model_prewarmer import get_prewarmer
            get_prewarmer().start()
            self._ready.mark_ready("model_prewarmer")
        except Exception as e:
            log.error(f"[Boot] model_prewarmer failed: {e}")
            self._ready.mark_failed("model_prewarmer", str(e))

        # Voice STT — deferred (Vosk loads large model)
        try:
            self._ready.mark_initializing("voice_stt")
            from core.engines.voice_engine import VoiceEngine
            self._ready.mark_degraded("voice_stt", "deferred — loads on first use")
        except Exception as e:
            log.error(f"[Boot] voice_stt failed: {e}")
            self._ready.mark_failed("voice_stt", str(e))

        # Voice TTS
        try:
            self._ready.mark_initializing("voice_tts")
            from core.engines.speech_engine import get_speech_engine
            get_speech_engine()
            self._ready.mark_ready("voice_tts")
        except Exception as e:
            log.error(f"[Boot] voice_tts failed: {e}")
            self._ready.mark_failed("voice_tts", str(e))

        # Voice output worker
        try:
            self._ready.mark_initializing("voice_worker")
            from workers.voice_output_worker import get_voice_output_worker
            worker = get_voice_output_worker()
            worker.start()
            self._ready.mark_ready("voice_worker")
            app = QApplication.instance()
            if app:
                app._voice_worker = worker
        except Exception as e:
            log.error(f"[Boot] voice_worker failed: {e}")
            self._ready.mark_failed("voice_worker", str(e))

        # Wake word — deferred activation after UI is stable
        try:
            self._ready.mark_initializing("wake_word")
            from core.ui.wake_word import get_wake_daemon

            def _on_wake():
                log.info("[WakeWord] Wake-word fired — activating command mode.")
                try:
                    from PyQt6.QtWidgets import QApplication
                    app = QApplication.instance()
                    if app and hasattr(app, '_ui'):
                        app._ui.activateWindow()
                        app._ui.raise_()
                except Exception:
                    pass

            daemon = get_wake_daemon(on_wake=_on_wake)
            daemon.start()
            self._ready.mark_ready("wake_word")

            app = QApplication.instance()
            if app:
                app._wake_daemon = daemon
        except Exception as e:
            log.error(f"[Boot] wake_word failed: {e}")
            self._ready.mark_failed("wake_word", str(e))

        # Telemetry
        try:
            self._ready.mark_initializing("telemetry")
            from core.agent.telemetry_service import get_telemetry_service
            get_telemetry_service()
            self._ready.mark_ready("telemetry")
        except Exception as e:
            log.error(f"[Boot] telemetry failed: {e}")
            self._ready.mark_failed("telemetry", str(e))

        # Voice interruption — deferred until after boot so brain is ready
        def _init_voice_interrupt():
            if CancellationToken.cancelled():
                return
            try:
                self._ready.mark_initializing("voice_interrupt")
                from core.ui.voice_interruption import get_voice_interruption
                vi = get_voice_interruption()

                try:
                    from core.engines.speech_engine import get_speech_engine
                    vi.set_speech_engine(get_speech_engine())
                except Exception:
                    pass

                def _speak_cb(text):
                    try:
                        from core.engines.speech_engine import get_speech_engine
                        get_speech_engine().speak(text)
                    except Exception:
                        pass

                vi.set_speak_callback(_speak_cb)

                app = QApplication.instance()
                if hasattr(self, '_orchestrator') and self._orchestrator and self._orchestrator.brain:
                    vi.set_command_callback(self._orchestrator.brain.process_async)

                vi.start()
                self._ready.mark_ready("voice_interrupt")

                if app:
                    app._voice_interrupt = vi

                log.info("[Boot] VoiceInterruption started.")
            except Exception as e:
                log.error(f"[Boot] voice_interrupt failed: {e}")
                self._ready.mark_failed("voice_interrupt", str(e))

        threading.Thread(target=_init_voice_interrupt, daemon=True, name="VoiceInterruptInit").start()

        # Memory service
        try:
            self._ready.mark_initializing("memory_service")
            from core.agent.memory_service import get_memory_service
            get_memory_service()
            self._ready.mark_ready("memory_service")
        except Exception as e:
            log.error(f"[Boot] memory_service failed: {e}")
            self._ready.mark_failed("memory_service", str(e))

        self._phase_durations[4] = (time.perf_counter() - t0) * 1000
        self._phase_done[4].set()
        log.info(f"[Boot] Phase 4 complete in {self._phase_durations[4]:.1f}ms")

        with self._lock:
            self._done = True
        log.info(f"[Boot] All phases complete. Total: {sum(self._phase_durations.values()):.1f}ms")

    def boot(self, on_complete: Callable[[], None] | None = None):
        """
        Execute all 4 boot phases.
        Phases 1 and 2 run synchronously (fast, <300ms total).
        Phases 3 and 4 run in background threads while the UI animation plays.

        All init tasks check CancellationToken.cancelled() — if shutdown arrives
        during init, remaining tasks abandon their work and clean up.
        """
        lc = get_runtime_lifecycle()
        lc._thread.start()  # start the RuntimeLifecycle monitor

        # Phase 1: UI shell — already running (CinematicBoot + JarvisUI visible)
        self._boot_phase1()
        if CancellationToken.cancelled():
            log.warning("[Boot] Cancelled during Phase 1 — abandoning boot.")
            return

        # Phase 2: Core runtime — synchronous, <300ms, no UI impact
        self._boot_phase2()
        if CancellationToken.cancelled():
            log.warning("[Boot] Cancelled during Phase 2 — abandoning boot.")
            return

        # Phase 3: Background services — daemon thread (companion/memory/observer systems)
        t3 = threading.Thread(target=self._boot_phase3, daemon=True, name="BootPhase3")
        t3.start()

        # Phase 4: Heavy systems — daemon thread, after phase 3 completes
        def phase4_wrapper():
            self._phase_done[3].wait(timeout=30.0)
            if not CancellationToken.cancelled():
                self._boot_phase4()
            else:
                log.warning("[Boot] Cancelled before Phase 4 — abandoning heavy systems.")
            if on_complete and not CancellationToken.cancelled():
                try:
                    on_complete()
                except Exception as e:
                    log.error(f"[Boot] on_complete error: {e}")

        t4 = threading.Thread(target=phase4_wrapper, daemon=True, name="BootPhase4")
        t4.start()

    def get_phase(self) -> int:
        with self._lock:
            return self._phase

    def is_complete(self) -> bool:
        with self._lock:
            return self._done

    def get_durations(self) -> dict[int, float]:
        return dict(self._phase_durations)

    @property
    def readiness(self):
        return self._ready


_instance: Optional[BootOrchestrator] = None
_lock = threading.Lock()


def get_boot_orchestrator() -> BootOrchestrator:
    global _instance
    with _lock:
        if _instance is None:
            _instance = BootOrchestrator()
        return _instance