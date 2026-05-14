import sys
import os
import faulthandler

import atexit

# Enable native crash handler
_crash_log = open("jarvis_crash.log", "w")
faulthandler.enable(file=_crash_log)
atexit.register(lambda: _crash_log.close())

# 🔥 CRITICAL: Fix ChromaDB/Protobuf compatibility
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

import json
import time
import warnings
try:
    import winsound as _winsound   # Windows only — use platform_shim.beep() for cross-platform
except ImportError:
    _winsound = None               # Linux/Mac: winsound unavailable, use platform_shim
import threading
import queue
import multiprocessing
import signal
import logging
import asyncio
import qasync
from qasync import QEventLoop

try:
    import pythoncom
except ImportError:
    pythoncom = None

# ── Suppress noise ───────────────────────────────────────────────────────────
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore")

from identity.identity_manager import IdentityManager
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt

# ═══════════════════════════════════════════════════════════════════
#  SINGLE-THREADED COMMAND ORCHESTRATOR (The "Safe-Path")
# ═══════════════════════════════════════════════════════════════════

class CommandOrchestrator(QObject):
    """
    JARVIS Command Orchestrator — delegates command processing to AutonomousBrain
    while owning the I/O layer (voice listener, UI signals, Qt integration).
    """
    status_signal = pyqtSignal(str)
    result_signal = pyqtSignal(str)

    def __init__(self, identity, ui):
        super().__init__()
        self.identity = identity
        self.ui = ui
        self._cmd_queue = queue.Queue()
        self.running = True
        self.brain = None
        self.voice_engine = None

    def submit_command(self, cmd: str, source: str = "voice"):
        """Thread-safe submission from UI or Voice."""
        self._cmd_queue.put({"cmd": cmd, "source": source})

    def start(self):
        t = threading.Thread(target=self._worker_loop, daemon=True, name="Orchestrator")
        t.start()
        v = threading.Thread(target=self._listener_loop, daemon=True, name="VoiceListener")
        v.start()

    def _listener_loop(self):
        """Dedicated thread for Mic -> Queue."""
        from core.engines.voice_engine import VoiceEngine
        from core.system.thread_manager import is_shutdown_requested
        self.voice_engine = VoiceEngine()
        print("[Voice] Listener active.")

        _consecutive_errors = 0
        _MAX_CONSECUTIVE_ERRORS = 10

        while self.running and not is_shutdown_requested():
            try:
                self.status_signal.emit("Listening")
                command = self.voice_engine.listen()
                if command and command.strip():
                    print(f"[Voice] Heard: {command}")
                    self.submit_command(command, source="voice")
                _consecutive_errors = 0
            except Exception as e:
                _consecutive_errors += 1
                print(f"[Voice] Mic error ({_consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS}): {e}")
                if _consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                    print("[Voice] Too many consecutive mic errors — suspending listener.")
                    break
                try:
                    time.sleep(min(2.0 * _consecutive_errors, 30.0))  # exponential backoff, cap 30s
                except Exception:
                    break

    def _worker_loop(self):
        """Dedicated thread for Brain initialisation and fast-path command dispatch."""
        from core.system.thread_manager import is_shutdown_requested
        if pythoncom: pythoncom.CoInitialize()

        # One persistent event loop for this thread's lifetime.
        # asyncio.run() was creating+destroying a loop PER command which caused
        # the Windows ProactorEventLoop pipe teardown -> access violations.
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

        from core.agent.jarvis_brain import JarvisBrain
        self.brain = JarvisBrain(self.identity, self.ui)
        print("[Brain] Worker active — dual-path routing enabled.")

        while self.running and not is_shutdown_requested():
            try:
                req = self._cmd_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Brain] Worker loop error: {e}")
                continue

            cmd    = req["cmd"]
            source = req["source"]

            self.status_signal.emit("Executing")
            try:
                result = _loop.run_until_complete(self.brain.process_async(cmd))
                if source == "ui":
                    self.result_signal.emit(result or "")
            except Exception as e:
                print(f"[Brain] Command failed: {e}")
                if source == "ui":
                    self.result_signal.emit(f"Error: {e}")
            finally:
                self._cmd_queue.task_done()
                self.status_signal.emit("Listening")

        # Clean up only when self.running is False
        try:
            _loop.close()
        except Exception:
            pass
        if pythoncom: pythoncom.CoUninitialize()

# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    from core.system.service_registry import get_service_registry
    registry = get_service_registry()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app._main_loop = loop

    signal.signal(signal.SIGINT, lambda s, f: app.quit())
    id_manager = IdentityManager()

    def start_main():
        if getattr(app, "_main_started", False): return
        app._main_started = True
        from core.engines.speech_engine import get_speech_engine
        from core.engines.speech_dispatcher import get_speech_dispatcher
        _speech = get_speech_engine()
        dispatcher = get_speech_dispatcher()
        dispatcher.set_engine(_speech)

        from ui.boot_sequence import CinematicBoot
        app._boot = CinematicBoot()
        app._boot.show()

        from ui.jarvis_desktop.jarvis_desktop import JarvisDesktop
        app._ui = JarvisDesktop()
        app._ui.hide()

        def _reveal_ui():
            if getattr(app, "_ui_revealed", False): return
            app._ui_revealed = True
            app._ui.showMaximized(); app._ui.raise_(); app._ui.activateWindow()
            app._boot.close(); app._boot.deleteLater()
            greeting = id_manager.get_greeting()
            app._ui.set_status(greeting)

            continuation_text = ""
            try:
                from core.companion.session_memory import get_session_continuity
                from core.companion.checkpoint import get_checkpoint
                sc = get_session_continuity()
                cp = get_checkpoint()
                sc.start_session(cp._session_id)
                if sc.should_offer_continuation():
                    continuation_text = " " + sc.get_continuation_text()
            except Exception:
                pass

            from core.system.platform import platform_shim
            platform_shim.beep(900, 150)
            _speech.speak(greeting + continuation_text)
            app._ui.set_status("Listening")

            # Start Command Orchestrator
            app._orchestrator = CommandOrchestrator(id_manager, app._ui)
            app._orchestrator.status_signal.connect(app._ui.set_status)
            app._orchestrator.result_signal.connect(app._ui.set_result)
            # Wire UI text commands back to orchestrator
            app._ui.command_submitted.connect(lambda cmd: app._orchestrator.submit_command(cmd, "ui"))
            
            app._orchestrator.start()

        app._boot.finished.connect(_reveal_ui)

        def start_subsystems():
            from core.system.boot_orchestrator import get_boot_orchestrator
            from core.system.readiness_state import get_readiness_tracker
            orch = get_boot_orchestrator()
            app._orch = orch
            app._boot.set_readiness(get_readiness_tracker())

            def _on_boot_complete():
                ready = get_readiness_tracker()
                summary = ready.get_summary()
                print(f"[Boot] Complete — {summary['ready']}/{summary['total']} ready, "
                      f"{summary['degraded']} degraded, {summary['failed']} failed")
                # MUST execute UI reveal on the main Qt thread
                QTimer.singleShot(0, _reveal_ui)

            orch.boot(on_complete=_on_boot_complete)

        QTimer.singleShot(100, start_subsystems)

    if id_manager.initialize() == "owner": start_main()
    else:
        from ui.auth_window import AuthWindow
        app._auth_win = AuthWindow(id_manager)
        app._auth_win.auth_success.connect(start_main)
        app._auth_win.show()

    app.aboutToQuit.connect(lambda: _graceful_shutdown(registry))
    with loop: loop.run_forever()

def _graceful_shutdown(registry):
    """
    Multi-stage shutdown with bounded timeouts and escalation.

    All teardown tasks are registered with ShutdownEscalation.
    Each task has a hard timeout. If exceeded, escalation fires immediately.
    os._exit is LAST RESORT only — not in the normal path.
    """
    print("[Shutdown] Initiating JARVIS shutdown...")

    from core.system.shutdown_escalation import ShutdownEscalation, _set_shutdown_escalation
    se = ShutdownEscalation()
    _set_shutdown_escalation(se)

    # Priority: CancellationToken FIRST (stops all init, wakes all loops)
    def _cancel_all():
        from core.system.cancellation_token import CancellationToken
        CancellationToken.request_shutdown("main_shutdown")
        print("[Shutdown] Cancellation signal sent.")

    se.register("CancellationToken", _cancel_all, timeout_sec=0.5, required=False)

    # Voice systems: release OS audio handles quickly
    def _stop_voice_worker():
        try:
            from workers.voice_output_worker import get_voice_output_worker
            vw = get_voice_output_worker()
            if vw and hasattr(vw, 'stop'):
                vw.stop()
        except Exception:
            pass
    se.register("VoiceWorker", _stop_voice_worker, timeout_sec=2.0)

    def _stop_wake_daemon():
        try:
            from core.ui.wake_word import get_wake_daemon
            wd = get_wake_daemon()
            if wd and hasattr(wd, 'stop'):
                wd.stop()
        except Exception:
            pass
    se.register("WakeDaemon", _stop_wake_daemon, timeout_sec=2.0)

    def _stop_voice_interrupt():
        try:
            from core.ui.voice_interruption import get_voice_interruption
            vi = get_voice_interruption()
            if vi and hasattr(vi, 'stop'):
                vi.stop()
        except Exception:
            pass
    se.register("VoiceInterrupt", _stop_voice_interrupt, timeout_sec=2.0)

    # Microphone: force release
    def _release_mic():
        try:
            from core.system.microphone_manager import get_microphone_manager
            mm = get_microphone_manager()
            mm.force_release("shutdown")
        except Exception:
            pass
    se.register("Microphone", _release_mic, timeout_sec=1.0, required=False)

    # RuntimeLifecycle: ordered subsystem teardown
    def _runtime_lifecycle():
        try:
            from core.system.runtime_lifecycle import get_runtime_lifecycle
            errors = get_runtime_lifecycle().shutdown_all(timeout_per_subsystem=1.5)
            if errors:
                print(f"[Shutdown] RuntimeLifecycle errors: {errors}")
        except Exception as e:
            print(f"[Shutdown] RuntimeLifecycle error: {e}")
    se.register("RuntimeLifecycle", _runtime_lifecycle, timeout_sec=5.0)

    # CommandOrchestrator worker loop
    def _stop_orchestrator():
        try:
            from PyQt6.QtWidgets import QApplication
            orch = getattr(QApplication.instance(), '_orchestrator', None)
            if orch:
                orch.running = False
        except Exception:
            pass
    se.register("CommandOrchestrator", _stop_orchestrator, timeout_sec=2.0)

    # Legacy singletons
    def _legacy_singletons():
        for getter, name in [
            ("core.agent.self_learning", "get_learning_loop"),
            ("core.system.system_watcher", "get_system_watcher"),
        ]:
            try:
                mod = __import__(getter, fromlist=[name.split(".")[-1]])
                inst = getattr(mod, name.split(".")[-1])()
                if inst and hasattr(inst, '_stop_evt'):
                    inst._stop_evt.set()
            except Exception:
                pass
    se.register("LegacySingletons", _legacy_singletons, timeout_sec=2.0)

    # Companion memory save: REQUIRED — state preservation is non-negotiable
    def _save_memory():
        saved = []
        for module, fn_name in [
            ("core.companion.layered_memory", "get_layered_memory"),
            ("core.companion.behavior_drift", "get_behavior_drift"),
            ("core.companion.cognitive_compression", "get_cognitive_compressor"),
            ("core.companion.domain_trust", "get_domain_trust"),
            ("core.companion.trust_model", "get_trust_model"),
            ("core.companion.fatigue_model", "get_fatigue_model"),
            ("core.companion.cognitive_continuity", "get_cognitive_continuity"),
        ]:
            try:
                mod = __import__(module, fromlist=[fn_name])
                inst = getattr(mod, fn_name)()
                if inst:
                    if hasattr(inst, 'save'):
                        inst.save()
                    elif hasattr(inst, 'end_session'):
                        inst.end_session()
                        if hasattr(inst, 'save'):
                            inst.save()
                    saved.append(fn_name.split("_")[-1])
            except Exception as e:
                print(f"[Shutdown] Save error for {fn_name}: {e}")
        print(f"[Shutdown] Companion memory saved: {saved or 'none'}")
    se.register("CompanionMemory", _save_memory, timeout_sec=3.0, required=True)

    # Hardware release (camera LED)
    def _release_hardware():
        try:
            from core.api.camera_manager import get_camera_manager
            cam = get_camera_manager()
            if cam and hasattr(cam, 'stop'):
                cam.stop()
        except Exception:
            pass
    se.register("Camera", _release_hardware, timeout_sec=2.0, required=False)

    # Service registry
    def _stop_registry():
        if registry:
            registry.stop_all()
    se.register("ServiceRegistry", _stop_registry, timeout_sec=3.0)

    # Thread pool
    def _stop_threads():
        try:
            from core.system.thread_manager import get_thread_manager, wait_for_shutdown
            wait_for_shutdown(timeout=0.5)
            get_thread_manager().shutdown(wait=False)
        except Exception:
            pass
    se.register("ThreadPool", _stop_threads, timeout_sec=3.0, required=False)

    # Execute all stages with escalation
    result = se.shutdown()

    # Only os._exit if escalation reached FINAL stage
    if not se.is_clean():
        print(f"[Shutdown] Non-clean shutdown — escalated to {result.stage.name}")
        import os as _os
        _os._exit(1)
    else:
        print("[Shutdown] Clean shutdown complete.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
