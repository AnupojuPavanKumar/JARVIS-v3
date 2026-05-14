# core/jarvis_brain.py
from core.engines.context_engine import ContextEngine
from core.system.plugin_manager import get_plugin_manager
from core.engines.proactive_engine import get_proactive_engine
from core.providers.model_router import get_router
from core.agent.scheduler import get_scheduler
from core.agent.agent import JarvisAgent
from core.agent.mode_manager import get_mode_manager
from core.system.event_bus import get_event_bus
from core.system.events import EventSpeechRequested, EventStatusUpdate, EventNtfyPush
from core.system.bootstrapper import Bootstrapper
from core.context.workspace import get_workspace_observer
from core.context.screen import get_screen_capture

# ── New service layer ───────────────────────────────────────────────
from core.agent.memory_service import get_memory_service
from core.engines.speech_dispatcher import get_speech_dispatcher
from core.agent.telemetry_service import get_telemetry_service

# ── Companion modules ────────────────────────────────────────────────
from core.companion.checkpoint import get_checkpoint
from core.companion.session_memory import get_session_continuity
from core.companion.phrase_rotation import get_rotator
from core.companion.cognitive_continuity import get_cognitive_continuity
from core.companion.fatigue_model import get_fatigue_model
from core.companion.graceful_degradation import get_graceful_degradation
from core.companion.trust_model import get_trust_model
from core.companion.cognitive_compression import get_cognitive_compressor
from core.companion.domain_trust import get_domain_trust
from core.companion.frustration_detector import get_frustration_detector
from core.companion.behavioral_anchors import apply_anchors, get_uncertainty_phrase
from core.companion.layered_memory import get_layered_memory
from core.companion.interaction_closure import get_interaction_closure
from core.companion.confidence_rhythm import get_confidence_rhythm
from core.companion.behavior_drift import get_behavior_drift

import threading
import logging
import time
import asyncio

class JarvisBrain:
    """
    JARVIS Sovereign Brain (V5).
    Now a thin coordinator: delegates memory, speech, and telemetry to
    dedicated service objects instead of managing everything inline.
    """

    def __init__(self, identity, ui=None):
        self.identity = identity
        self.user_name = "Sir"
        self.ui = ui
        self._t_ctx = threading.local()
        self._process_lock = threading.Lock()
        self._boot_time = time.time()

        # Capture the qasync main loop reference lazily via QApplication.
        # DO NOT call asyncio.get_event_loop() here — JarvisBrain is constructed
        # on the Orchestrator worker thread which has its OWN isolated loop
        # (main.py:144-145). Capturing that loop here would cause
        # VoiceInterruption to schedule coroutines on the wrong (worker) loop.
        # Instead, resolve the loop at first use via QApplication._main_loop.
        self._main_loop = None  # resolved lazily in _get_main_loop()

        # ── Service layer (replaces direct inline engine construction) ────────
        self._mem    = get_memory_service()
        self._speech = get_speech_dispatcher()
        self._telem  = get_telemetry_service(ui=ui, speech=self._speech)

        # ── Lightweight core engines (kept directly; not yet service-wrapped) ─
        self.context_engine   = ContextEngine()
        # Backward-compat aliases so external code still works
        self.plugin_manager   = get_plugin_manager()
        self.proactive_engine = get_proactive_engine()
        self.model_router     = get_router()
        self.scheduler        = get_scheduler()

        from core.api.skill_registry import SkillRegistry
        self.skill_registry = SkillRegistry()

        self._mode_manager  = get_mode_manager()
        self._bg_ready      = False

        self._skill_factory   = None
        self._task_queue      = None

        # Agent
        self.agent = JarvisAgent(identity=identity, ui=ui)

# ── Companion modules ─────────────────────────────────────────────────
        self._checkpoint    = get_checkpoint()
        self._continuity    = get_session_continuity()
        self._rotator       = get_rotator()
        self._cognitive     = get_cognitive_continuity()
        self._fatigue       = get_fatigue_model()
        self._degrade       = get_graceful_degradation()
        self._trust         = get_trust_model()
        self._compressor    = get_cognitive_compressor()
        self._domain_trust  = get_domain_trust()
        self._frustration   = get_frustration_detector()
        self._layered_mem  = get_layered_memory()
        self._closure      = get_interaction_closure()
        self._confidence   = get_confidence_rhythm()
        self._drift        = get_behavior_drift()

        self._drift.start_session(self._checkpoint._session_id)

    @property
    def _calm_engine(self):
        from core.companion.calm_engine import get_calm_engine
        return get_calm_engine()

    def _mid_post_telemetry(self, command: str, result: str) -> str:
        """Record JARVIS response in history."""
        if result and result not in ("STOP", "EXIT"):
            try:
                self._mem.record_jarvis(result)
            except Exception as e:
                logging.error(f"[Brain] Error in post-telemetry: {e}")
        return result

    def _mid_post_speak(self, command: str, result: str) -> str:
        """Route the final text to the TTS engine via UI events."""
        if result and result not in ("STOP", "EXIT") and not getattr(self._t_ctx, 'already_spoken', False):
            adapted = self._adapt_verbosity(result)
            if adapted:
                degrade = self._degrade
                frustration = self._frustration
                confidence = self._confidence
                drift = self._drift

                # Layer 1: behavioral anchor hard cap
                adapted = apply_anchors(adapted)

                # Layer 2: confidence rhythm — soften phrasing when uncertain
                if confidence.should_soften_phrase() and not frustration.should_be_minimal():
                    adapted = confidence.adapt_acknowledgment(adapted)

                # Layer 3: behavior drift correction
                corrections = drift.get_correction()
                max_s = int(3 * corrections.get("sentence_mult", 1.0))
                max_s = max(1, max_s)
                sentences = [s.strip() for s in adapted.split(". ") if s.strip()]
                if len(sentences) > max_s:
                    adapted = ". ".join(sentences[:max_s])
                    if adapted and not adapted.endswith("."):
                        adapted += "."

                # Layer 4: graceful degradation
                verb_mult = degrade.get_smoothed_verbosity()
                verb_limit = max(1, int(max_s * verb_mult))
                if len(sentences) > verb_limit:
                    adapted = ". ".join(sentences[:verb_limit])
                    if adapted and not adapted.endswith("."):
                        adapted += "."

                # Layer 5: frustration — strip to single sentence
                if frustration.should_simplify():
                    if ". " in adapted:
                        adapted = adapted.split(". ")[0].strip() + "."
                    elif len(adapted.split()) > 6:
                        adapted = " ".join(adapted.split()[:6]) + "."

                # Track metrics for drift detection
                try:
                    self._drift.record_response(len(adapted), len(adapted.split(". ")))
                    self._drift.record_speech()
                except Exception:
                    pass

                # Phrase rotation (only when not fatigued/frustrated)
                if not self._fatigue.should_skip_completion() and not frustration.should_be_minimal():
                    words = adapted.split()
                    if len(words) <= 8 and "." in adapted:
                        varied = self._rotator.vary_response(adapted, "acknowledgment")
                        if varied != adapted:
                            adapted = varied

                # Pacing delay: graceful degradation density + confidence rhythm
                conf_delay = confidence.get_pacing_delay()
                degrade_delay = degrade.pacing_delay()
                density = degrade.get_smoothed_speech_density()
                if density < 0.7:
                    degrade_delay = (1.0 - density) * 0.3
                total_delay = max(conf_delay, degrade_delay)
                if total_delay > 0:
                    import time as _time
                    _time.sleep(total_delay)

                self._speak_via_ui(adapted)
                try:
                    self._fatigue.record("speech")
                except Exception:
                    pass
        return result

    # ── Main Processing Loop ───────────────────────────────────────

    async def process_async(self, command: str) -> str:
        """Async version of the processing pipeline."""
        # 0. Wake-word instant response — no processing, just acknowledge
        if command == "_WAKE_WORD_":
            self._speak_via_ui("Yes sir?")
            return "Yes sir?"

        # 0. Session continuity: detect "continue" signals → offer restoration
        try:
            session = self._continuity.get_session()
            if session and session.can_continue(command):
                continuation = session.format_continuation()
                if continuation:
                    self._speak_via_ui(continuation)
                    return continuation
        except Exception:
            pass

        # 0. Mode-change shortcut — intercept before any other processing
        mode_greeting = self._mode_manager.set_mode_by_voice(command)
        if mode_greeting:
            adapted = self._adapt_verbosity(mode_greeting)
            if adapted:
                self._speak_via_ui(adapted)
            return adapted or mode_greeting

        # 0. Context-aware commands: capture screen context for certain requests
        ctx_summary = self._get_context_summary()

        # 1. Noise Filter
        if time.time() - self._boot_time < 10.0:
            if len(command.split()) < 2: return ""

        # 2. Pre-telemetry (record user input)
        self._mem.record_user(command)
        try:
            self.proactive_engine.record_command(command)
        except Exception:
            pass

        # Track cognitive context (what the user is mentally working on)
        try:
            intent_name = ""
            self._cognitive.track_command(command, intent=intent_name)
            self._fatigue.record("command")
        except Exception:
            pass

        # 3. Contextual Memory Grounding
        self._t_ctx.memory_context = self._mem.build_context_block(command)

        # 4. Core Execution (STRICTLY SYNCHRONOUS on this thread)
        try:
            result = self._process_inner(command)
        except Exception as e:
            # Phase 2: Failure Journaling
            from core.analytics.failure_journal import get_failure_journal
            get_failure_journal().log_failure(
                task_objective=command,
                context=getattr(self._t_ctx, 'memory_context', ''),
                root_cause=str(e),
                category="execution_drift",
                recovery_attempt="Fallthrough to stop",
                retry_count=0,
                human_intervention_required=True,
                operational_impact_severity="HIGH"
            )
            result = f"Operational Failure: {e}"
            logging.error(f"[Brain] FATAL: {e}")

        # 5. Post-processing
        if result:
            # Human-friendly failure translation (no technical panic)
            is_error = result.startswith("Error")
            if is_error:
                result = self._translate_failure(result)

            self._mid_post_speak(command, result)
            # Post-telemetry (record JARVIS response)
            if result and result not in ("STOP", "EXIT"):
                self._mem.record_jarvis(result)

            success = not is_error and result not in ("STOP", "EXIT")

            # Frustration detection
            try:
                self._frustration.record(
                    command, result, success=success, latency_s=0.5
                )
            except Exception:
                pass

            # Session continuity + checkpoint
            try:
                self._continuity.record_command(
                    command, result,
                    intent=getattr(self._t_ctx, 'last_intent', ''),
                    success=success
                )
                ws = get_workspace_observer()
                ctx = ws.get_context_summary()
                self._checkpoint.update(
                    last_mode=self._mode_manager.current_mode,
                    last_app=ctx.get("app", ""),
                    last_category=ctx.get("category", "unknown"),
                    workflow=ctx.get("workflow"),
                )
                self._checkpoint.record_command()
            except Exception:
                pass

            # Cognitive continuity: track what JARVIS did
            try:
                self._track_cognitive_action(command, result)
                if self._cognitive._dirty:
                    self._compressor.add_event(
                        category=getattr(self._t_ctx, 'last_category', 'unknown'),
                        topic=getattr(self._t_ctx, 'last_workflow', '') or command[:40],
                        detail=result[:80],
                    )
                    self._cognitive._dirty = False
                    self._compressor.compress()
                    # Push L1 narrative into layered memory
                    try:
                        from core.companion.cognitive_compression import get_cognitive_compressor
                        cc = get_cognitive_compressor()
                        last = cc.get_last_narrative()
                        if last:
                            self._layered_mem.push_l1(
                                summary=last.narrative,
                                category=last.category,
                                topic=last.topic,
                                confidence=last.confidence,
                            )
                    except Exception:
                        pass
            except Exception:
                pass

            # Domain trust update
            try:
                domain = self._infer_domain(command)
                if success:
                    self._domain_trust.record_accept(domain)
                else:
                    self._domain_trust.record_reject(domain)
            except Exception:
                pass

            # Confidence rhythm + interaction closure
            try:
                self._confidence.update_success(success)
                self._closure.record_command(command, success,
                    category=getattr(self._t_ctx, 'last_category', 'unknown'))
                completion = self._closure.detect_completion()
                if completion:
                    self._speak_via_ui(completion)
                self._drift.record_command()
            except Exception:
                pass

            # Layered memory: L4 raw event
            try:
                self._layered_mem.push_raw(
                    command=command, result=result, success=success,
                    category=getattr(self._t_ctx, 'last_category', 'unknown'),
                    intent=getattr(self._t_ctx, 'last_intent', ''),
                )
            except Exception:
                pass

        return result

    def _translate_failure(self, result: str) -> str:
        """Convert technical error messages into calm human explanations."""
        low = result.lower()
        translations = [
            ("ollama", "The local model stopped responding."),
            ("timeout", "The operation took too long. Let me try again."),
            ("connection refused", "The service is unavailable right now."),
            ("file not found", "That file isn't where I expected it to be."),
            ("permission denied", "I don't have access to that resource."),
            ("out of memory", "The system is running low on resources."),
            ("cuda", "The GPU encountered an issue."),
            ("provider unavailable", "The AI service isn't responding."),
            ("syntax error", "There's a syntax issue in the code."),
        ]
        for technical, human in translations:
            if technical in low:
                return human
        return "Something didn't work as expected."

    def _infer_domain(self, command: str) -> str:
        """Infer which trust domain a command belongs to."""
        low = command.lower()
        if any(k in low for k in ["continue", "resume", "restore", "back to"]):
            return "workspace_restore"
        if any(k in low for k in ["open", "close", "tab", "browser", "navigate"]):
            return "browser_actions"
        if any(k in low for k in ["create", "delete", "edit", "file", "folder", "mkdir"]):
            return "file_operations"
        if any(k in low for k in ["system", "setting", "registry", "admin", "permission"]):
            return "system_changes"
        if any(k in low for k in ["suggest", "recommend", "should", "maybe"]):
            return "proactive_suggestions"
        return "automation_execution"

    def _track_cognitive_action(self, command: str, result: str):
        """Extract action from result and record in cognitive continuity."""
        low = command.lower()

        action_map = {
            "open": ("open", "app"),
            "close": ("close", "app"),
            "search": ("search", "web"),
            "build": ("build", "code"),
            "fix": ("fix", "bug"),
            "run": ("run", "command"),
            "create": ("create", "file"),
            "delete": ("delete", "file"),
            "analyze": ("analyze", "analysis"),
            "review": ("review", "review"),
            "generate": ("generate", "output"),
            "deploy": ("deploy", "deployment"),
        }

        for key, (action, impact) in action_map.items():
            if key in low:
                target = result[:60] if result and not result.startswith("Error") else command[:40]
                self._cognitive.track_action(action, target, command, success=True, impact=impact)
                break



    def _process_inner(self, command: str) -> str:
        """Routes command using Two-Layer Architecture: Fast Deterministic + AI Fallback."""
        print(f"[Brain] {command}")

        # 0. Pattern cache (JSONL-backed, thread-safe)
        cached = self._mem.recall_best(command)
        if cached:
            return cached

        # ── LAYER 1: Fast Deterministic Execution ───────────────────────────────
        # Regex/keyword routing — no LLM, <100ms latency
        from core.router.fast_router import get_fast_router
        fast_router = get_fast_router()
        result = fast_router.route_for_brain(command)
        if result is not None:
            print(f"[Brain] Fast-path executed: {result}")
            return result

        # ── LAYER 2: AI Reasoning Fallback ────────────────────────────────────
        # Deterministic router returned None → command is ambiguous/planning/coding
        # Fall through to IntentRouter + JarvisAgent for full AI reasoning
        from core.engines.intent_router import get_intent_router
        router = get_intent_router()
        intent, confidence = router.route(command)
        print(f"[Brain] Semantic Intent: {intent} ({confidence:.2f})")

        skill_context = {
            "identity": self.identity,
            "user_name": self.user_name
        }

        # 2. Dispatch based on Intent
        if intent == "STATUS_QUERY":
            return "No active jobs, sir. Orchestrator offline."

        if intent == "SKILL_EXEC":
            registry_result = self.skill_registry.execute_fast(command, skill_context)
            if registry_result: return registry_result

        # ── CHAT fast-path: bypass the full ReAct agent entirely ──────────────
        # For greetings / small-talk, stream_reply is 10-30x faster than
        # agent.run() because it skips model-switching, VRAM ops, and JSON
        # planning. llm_generated=True tells _mid_post_naturalize_async to
        # skip the second LLM pass (already a natural reply).
        if intent == "CHAT":
            self._hud_set_skill("chat")
            self._t_ctx.llm_generated = True
            try:
                from core.agent.llm_stream import stream_reply_async
                from core.agent.telemetry_service import get_telemetry_service

                # Build conversation history for contextual responses
                _history = self._mem.get_recent(6)
                _hist_msgs = [
                    {"role": "user" if t["speaker"] == "user" else "assistant",
                     "content": t["text"]}
                    for t in (_history[:-1] if _history else [])
                ]

                # Streaming token display in UI chat
                def _on_token(token: str):
                    get_telemetry_service().stream_token(token, source="jarvis")

                def _on_done(result: str):
                    pass  # Final result spoken via _mid_post_speak

                stream_reply_async(
                    user_input=command,
                    speak_cb=self._speak_via_ui,
                    done_cb=_on_done,
                    history=_hist_msgs,
                )

                # Streaming returns empty — TTS streams via speak_cb, UI via _on_token
                return ""

            except Exception as e:
                logging.error(f"[Brain] CHAT fast-path failed: {e}")
            # Fallthrough to agent if stream_reply fails

        if intent == "AGENT_TASK":
            self._hud_set_skill("agent")
            self._t_ctx.llm_generated = True
            return self.agent.run(command)

        if intent == "WEB_RESEARCH":
            self._hud_set_skill("agent")
            self._t_ctx.llm_generated = True
            return self.agent.run(command)

        self._hud_set_skill("agent")
        self._t_ctx.llm_generated = True
        return self.agent.run(command)

    # ── Helpers (now delegate to services) ────────────────────────────────

    def _get_main_loop(self):
        """Resolve the qasync main loop lazily.
        JarvisBrain is constructed on a worker thread, so asyncio.get_event_loop()
        at __init__ time returns the worker's own loop — not the qasync loop.
        We always resolve from QApplication._main_loop which is set in main.py
        *before* any worker threads start.
        """
        if self._main_loop is None:
            try:
                from PyQt6.QtWidgets import QApplication
                self._main_loop = getattr(QApplication.instance(), '_main_loop', None)
            except Exception:
                pass
        return self._main_loop

    def _hud_update_progress(self, step: int, total: int, title: str):
        self._telem.set_agent_step(step, total, title)

    def _get_context_summary(self) -> dict:
        """Lazily capture current workspace context for command enrichment."""
        try:
            ws = get_workspace_observer()
            return ws.get_context_summary()
        except Exception:
            return {}



    def _speak_via_ui(self, text: str):
        self._speech.speak(text)

    def _ntfy_push(self, title: str, message: str, priority: str = "default"):
        self._speech.push_notification(title=title, message=message, priority=priority)

    def _on_proactive_suggestion(self, suggestion: str):
        self._telem.on_proactive_suggestion(suggestion)

    def _on_reminder(self, text: str):
        self._telem.on_reminder(text)

    def _hud_set_skill(self, skill_name: str):
        self._telem.set_active_skill(skill_name)

    def process(self, command: str) -> str:
        """
        Sync bridge for callers that cannot await (e.g. VoiceInterruption).

        FIX: Use thread-local event loop that persists across calls on the same thread.
        This avoids creating/destroying event loops on every call while still
        being isolated from the main qasync loop.
        """
        import threading

        # Thread-local storage for event loop
        thread_local = threading.local()

        # Get or create event loop for this thread
        if not hasattr(thread_local, 'event_loop') or thread_local.event_loop is None:
            thread_local.event_loop = asyncio.new_event_loop()
            thread_local.loop_created = True
        else:
            thread_local.loop_created = False

        loop = thread_local.event_loop

        try:
            # Ensure the loop is running (in case it was stopped)
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                thread_local.event_loop = loop
                thread_local.loop_created = True

            return loop.run_until_complete(self.process_async(command)) or ""
        except Exception as exc:
            logging.error(f"[Brain] process() isolated loop failed: {exc}")
            return ""
        finally:
            # Only close if we created it and it's not being reused
            # We keep the loop alive for future calls on the same thread
            pass

    def wire_voice_interruption(self, speech_engine):
        self._speech_engine = speech_engine
        def _wire():
            try:
                from core.ui.voice_interruption import get_voice_interruption
                vi = get_voice_interruption()
                self._voice_interrupt = vi
                vi.set_speech_engine(speech_engine)
                vi.set_command_callback(self.process)  # sync bridge
                vi.set_speak_callback(self._speak_via_ui)
                logging.info("[Brain] VoiceInterruption configured (not started — mic conflict prevention).")
            except Exception as e:
                logging.error(f"[Brain] VoiceInterruption wire failed: {e}")
        
        from core.system.thread_manager import get_thread_manager
        get_thread_manager().run_in_background(_wire, name="BrainWireVoice")


    def teach_new_skill(self, trigger_command: str) -> str:
        self._hud_set_skill("skill_gen")
        if not self._skill_factory: return "Skill factory not ready."
        result = self._skill_factory.generate_skill(trigger_command)
        return f"Skill generated for '{trigger_command}'." if result.endswith(".py") else f"Failed: {result}"

    def _run_agent_task(self, task: str) -> str:
        return self.agent.run(task)

    def _handle_system_alert(self, alert: any):
        """Handle background system alerts from SystemWatcher."""
        from core.system.system_watcher import SEVERITY_WARNING, SEVERITY_CRITICAL
        
        # 1. High-priority alerts -> TTS + HUD
        if alert.severity in (SEVERITY_WARNING, SEVERITY_CRITICAL):
            msg = f"Alert, sir. {alert.message}"
            self._speak_via_ui(msg)
            self._ntfy_push(f"JARVIS {alert.title}", alert.message, priority="high")
            return

        # 2. Python File Modified -> Proactive Code Health Check
        if alert.title == "File Modified":
            # Alert message format: "Modified: {filename}"
            # Alert source format:  "file_watcher"
            fname = alert.message.split(": ", 1)[-1].strip()
            if fname.endswith(".py"):
                from core.system.thread_manager import get_thread_manager
                get_thread_manager().run_in_background(
                    self._proactive_code_check,
                    args=(fname,),
                    name="Proactive-CodeCheck"
                )

    def _proactive_code_check(self, file_path: str):
        """Perform a non-blocking compile check on modified code."""
        try:
            from core.agent.runtime_executor import RuntimeExecutor
            from pathlib import Path
            
            p = Path(file_path)
            if not p.exists(): return
            
            executor = RuntimeExecutor(timeout=10)
            result = executor.py_compile([p])
            
            if not result.success:
                # Extract the error summary
                err = result.stderr.splitlines()[-1] if result.stderr else "Syntax error"
                suggestion = (
                    f"Sir, I noticed a syntax error in {p.name}: '{err}'. "
                    f"Would you like me to repair it?"
                )
                self._on_proactive_suggestion(suggestion)
        except Exception as e:
            logging.error(f"Silent error caught: {e}")
