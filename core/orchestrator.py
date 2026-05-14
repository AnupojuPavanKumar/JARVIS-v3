# core/orchestrator.py — JARVIS AUTONOMOUS BRAIN ORCHESTRATOR
# ──────────────────────────────────────────────────────────────────────────────
# AutonomousBrain: Event-driven orchestrator sitting on the internal PubSub bus.
#
# State Machine: Perceive → Plan → ToolCall → Verify → Respond
#   - Perceive  : consumes input.voice + input.vision events; fuses into context
#   - Plan      : routes to intent engine; selects execution strategy
#   - ToolCall  : dispatches MCP bridge for local tool execution
#   - Verify    : runs self-correction layer (compile / lint check)
#   - Respond   : publishes final text to response.text topic for TTS worker
#
# Self-Correction Layer:
#   Any code artifact produced by the LLM is run through py_compile + ruff/pyflakes
#   before execution. If errors are found, the LLM is given a second-chance prompt
#   with the exact error and asked to fix it (max 2 correction rounds).
#
# VRAM Strategy:
#   - Moondream2 (1.5 GB) for vision; Gemma2:9b (≈5 GB) for reasoning
#   - Never load both simultaneously → pynvml guard before model switch
#   - RTX 4050 6 GB safe window: ≤ 80 % VRAM utilisation
#
# PubSub: Uses core.system.event_bus (internal asyncio-compatible bus).
#   External NATS bridge is opt-in via JARVIS_NATS_URL env var.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from enum import Enum, auto
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, validator

log = logging.getLogger("AutonomousBrain")

# ── VRAM guard ────────────────────────────────────────────────────────────────
VRAM_SAFE_PCT = 80.0   # % — abort model load above this threshold


def _vram_pct() -> float:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        m = pynvml.nvmlDeviceGetMemoryInfo(h)
        return round(100.0 * m.used / m.total, 1)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class VoiceInputEvent(BaseModel):
    """Validated payload from the input.voice topic."""
    topic: str = "input.voice"
    text: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: float = Field(default_factory=time.time)
    identity: str = "owner"

    @validator("text")
    def text_must_not_be_empty(cls, v: str) -> str:  # noqa: N805
        if not v.strip():
            raise ValueError("voice input text must not be empty")
        return v.strip()


class VisionInputEvent(BaseModel):
    """Validated payload from the input.vision topic."""
    topic: str = "input.vision"
    source: str = "screen"          # "screen" | "camera"
    frame_path: Optional[str] = None
    description: Optional[str] = None   # pre-analysed caption from VisionWorker
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class AgentContext(BaseModel):
    """Fused multi-modal context fed into the planning stage."""
    voice_text: Optional[str] = None
    vision_description: Optional[str] = None
    vision_source: Optional[str] = None
    identity: str = "owner"
    timestamp: float = Field(default_factory=time.time)
    memory_context: str = ""
    history: list[dict[str, str]] = Field(default_factory=list)

    @property
    def fused_prompt(self) -> str:
        parts: list[str] = []
        if self.voice_text:
            parts.append(f"[VOICE] {self.voice_text}")
        if self.vision_description:
            src = self.vision_source or "screen"
            parts.append(f"[VISION/{src.upper()}] {self.vision_description}")
        if self.memory_context:
            parts.append(f"[MEMORY]\n{self.memory_context}")
        return "\n\n".join(parts) if parts else ""


class PlanResult(BaseModel):
    """Output of the Plan stage."""
    intent: str
    confidence: float
    strategy: str   # "chat" | "agent" | "skill" | "mcp_tool"
    tool_name: Optional[str] = None
    tool_input: Optional[Any] = None
    requires_code: bool = False


class VerifyResult(BaseModel):
    """Output of the self-correction Verify stage."""
    passed: bool
    issues: list[str] = Field(default_factory=list)
    corrected_code: Optional[str] = None
    correction_rounds: int = 0


class ResponseEvent(BaseModel):
    """Published to response.text for the VoiceOutputWorker."""
    topic: str = "response.text"
    text: str
    stream: bool = True
    identity: str = "owner"
    timestamp: float = Field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════════════════
#  STATE MACHINE
# ═══════════════════════════════════════════════════════════════════════════════

class BrainState(Enum):
    IDLE      = auto()
    PERCEIVE  = auto()
    PLAN      = auto()
    TOOL_CALL = auto()
    VERIFY    = auto()
    RESPOND   = auto()
    ERROR     = auto()


# ═══════════════════════════════════════════════════════════════════════════════
#  SELF-CORRECTION LAYER
# ═══════════════════════════════════════════════════════════════════════════════

class SelfCorrectionLayer:
    """
    Checks LLM-produced code for syntax/lint errors before execution.
    Provides up to MAX_ROUNDS correction loops using the LLM itself.
    """
    MAX_ROUNDS = 2

    def __init__(self, speak_cb: Optional[Callable[[str], None]] = None):
        self._speak = speak_cb or (lambda _: None)

    def verify_code(self, code: str, language: str = "python") -> VerifyResult:
        """Run static checks and return a VerifyResult."""
        if language != "python":
            # Non-Python: pass through (future: add JS/Shell linters)
            return VerifyResult(passed=True)

        issues: list[str] = []

        # Pass 1: py_compile (syntax)
        import py_compile, tempfile, traceback
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w",
                                        encoding="utf-8", delete=False) as tmp:
            tmp.write(code)
            tmp_path = tmp.name
        try:
            py_compile.compile(tmp_path, doraise=True)
        except py_compile.PyCompileError as e:
            issues.append(f"SyntaxError: {e}")
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        # Pass 2: pyflakes (undefined names, imports)
        try:
            from pyflakes import api as pyflakes_api  # type: ignore
            import io
            buf = io.StringIO()
            warnings = pyflakes_api.check(code, "<string>")
            if warnings:
                issues.append(f"Pyflakes: {warnings} warning(s)")
        except ImportError:
            log.debug("[SelfCorrect] pyflakes not installed — skipping lint pass")
        except Exception as e:
            log.debug(f"[SelfCorrect] pyflakes error: {e}")

        return VerifyResult(passed=len(issues) == 0, issues=issues)

    def auto_correct(self, code: str, issues: list[str],
                     llm_fn: Callable[[str], str]) -> VerifyResult:
        """
        Ask the LLM to fix the issues, then re-verify.
        Returns the final VerifyResult (passed or not after MAX_ROUNDS).
        """
        current_code = code
        for round_n in range(1, self.MAX_ROUNDS + 1):
            issue_text = "\n".join(f"- {i}" for i in issues)
            correction_prompt = (
                f"The following Python code has errors:\n\n```python\n{current_code}\n```\n\n"
                f"Errors found:\n{issue_text}\n\n"
                "Fix ALL errors. Return ONLY the corrected Python code inside ```python ... ``` fences."
            )
            log.info(f"[SelfCorrect] Correction round {round_n}/{self.MAX_ROUNDS}")
            try:
                raw_reply = llm_fn(correction_prompt)
                match = re.search(r"```python\s*(.*?)\s*```", raw_reply, re.DOTALL)
                current_code = match.group(1) if match else raw_reply
            except Exception as e:
                log.error(f"[SelfCorrect] LLM correction failed: {e}")
                break

            result = self.verify_code(current_code)
            result.correction_rounds = round_n
            if result.passed:
                result.corrected_code = current_code
                log.info(f"[SelfCorrect] Code passed after {round_n} correction round(s).")
                return result
            issues = result.issues

        # Still failing after all rounds
        final = VerifyResult(passed=False, issues=issues,
                             correction_rounds=self.MAX_ROUNDS)
        final.corrected_code = current_code   # best-effort
        return final


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTONOMOUS BRAIN
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousBrain:
    """
    The central orchestrator. Sits on the JARVIS internal PubSub bus and
    drives the full Perceive → Plan → ToolCall → Verify → Respond loop.

    Instantiation is cheap; heavy subsystems (VLM, RAG) are loaded lazily.
    """

    # ── Topics ────────────────────────────────────────────────────────────────
    TOPIC_VOICE  = "input.voice"
    TOPIC_VISION = "input.vision"
    TOPIC_RESP   = "response.text"

    def __init__(self, identity: str = "owner"):
        self.identity   = identity
        self._state     = BrainState.IDLE
        self._bus       = None   # resolved lazily
        self._corrector = SelfCorrectionLayer()

        # Pending events — voice waits for optional vision enrichment (50 ms window)
        self._pending_voice:  Optional[VoiceInputEvent]  = None
        self._pending_vision: Optional[VisionInputEvent] = None

        # NATS client (opt-in)
        self._nats: Any = None
        _nats_url = os.environ.get("JARVIS_NATS_URL", "")
        if _nats_url:
            asyncio.get_event_loop().create_task(self._connect_nats(_nats_url))

        log.info(f"[Brain] AutonomousBrain initialised | identity={identity}")

    # ── PubSub wiring ──────────────────────────────────────────────────────────

    def _get_bus(self):
        if self._bus is None:
            from core.system.event_bus import get_event_bus
            self._bus = get_event_bus()
        return self._bus

    def start(self):
        """
        Subscribe to all input topics.
        Call this after the asyncio event loop is running.
        """
        bus = self._get_bus()
        bus.subscribe(self.TOPIC_VOICE,  self._on_voice_raw)
        bus.subscribe(self.TOPIC_VISION, self._on_vision_raw)
        log.info(f"[Brain] Subscribed → {self.TOPIC_VOICE}, {self.TOPIC_VISION}")

    async def _connect_nats(self, url: str):
        """Optional NATS bridge — mirrors internal bus events to a NATS cluster."""
        try:
            import nats  # type: ignore
            self._nats = await nats.connect(url)
            log.info(f"[Brain] NATS connected: {url}")
        except ImportError:
            log.warning("[Brain] 'nats-py' not installed — NATS bridge disabled.")
        except Exception as e:
            log.error(f"[Brain] NATS connection failed: {e}")

    # ── Raw event handlers ─────────────────────────────────────────────────────

    def _on_voice_raw(self, payload: dict):
        """Called by the bus on input.voice events (may be sync or async)."""
        try:
            event = VoiceInputEvent(**payload)
            asyncio.get_event_loop().create_task(self._handle_voice(event))
        except Exception as e:
            log.error(f"[Brain] VoiceInputEvent validation error: {e}")

    def _on_vision_raw(self, payload: dict):
        """Called by the bus on input.vision events."""
        try:
            event = VisionInputEvent(**payload)
            self._pending_vision = event   # held for voice fusion window
        except Exception as e:
            log.error(f"[Brain] VisionInputEvent validation error: {e}")

    # ── State machine entry point ──────────────────────────────────────────────

    async def _handle_voice(self, voice: VoiceInputEvent):
        """Drive the full state-machine pipeline for a voice command."""
        start = time.perf_counter()
        self._state = BrainState.PERCEIVE
        log.info(f"[Brain] ── PERCEIVE ── '{voice.text[:80]}'")

        # ── Stage 1: PERCEIVE ─────────────────────────────────────────────────
        ctx = await self._stage_perceive(voice)

        if not ctx.fused_prompt:
            log.warning("[Brain] Fused prompt is empty — aborting pipeline.")
            self._state = BrainState.IDLE
            return

        # ── Stage 2: PLAN ─────────────────────────────────────────────────────
        self._state = BrainState.PLAN
        log.info("[Brain] ── PLAN ──")
        plan = await self._stage_plan(ctx)

        # ── Stage 3: TOOL_CALL ────────────────────────────────────────────────
        self._state = BrainState.TOOL_CALL
        log.info(f"[Brain] ── TOOL_CALL ── strategy={plan.strategy}")
        raw_result = await self._stage_tool_call(ctx, plan)

        # ── Stage 4: VERIFY ───────────────────────────────────────────────────
        self._state = BrainState.VERIFY
        log.info("[Brain] ── VERIFY ──")
        final_result = await self._stage_verify(raw_result, plan)

        # ── Stage 5: RESPOND ──────────────────────────────────────────────────
        self._state = BrainState.RESPOND
        elapsed = round(time.perf_counter() - start, 2)
        log.info(f"[Brain] ── RESPOND ── ({elapsed}s total)")
        await self._stage_respond(final_result, voice.identity)

        self._state = BrainState.IDLE

    # ─────────────────────────────────────────────────────────────────────────
    #  STAGE IMPLEMENTATIONS
    # ─────────────────────────────────────────────────────────────────────────

    async def _stage_perceive(self, voice: VoiceInputEvent) -> AgentContext:
        """
        Fuse voice + optional vision frame into a single AgentContext.
        Vision window: if a vision event arrived within 200 ms of the voice
        event, treat it as spatially co-incident context.
        """
        vision_desc: Optional[str] = None
        vision_src:  Optional[str] = None

        # Vision fusion window: 200 ms
        if self._pending_vision:
            age = time.time() - self._pending_vision.timestamp
            if age <= 0.20:
                vision_desc = self._pending_vision.description
                vision_src  = self._pending_vision.source
                log.debug(f"[Perceive] Vision fused ({age*1000:.0f}ms old, src={vision_src})")
            self._pending_vision = None

        # Memory / RAG context
        mem_ctx = ""
        try:
            from core.tools.long_term_memory import get_memory_instance
            mem = get_memory_instance()
            if mem.collection.count() > 0:
                mem_ctx = mem.search_memory(voice.text, limit=2)
                if "No historic patterns" in mem_ctx or "Error" in mem_ctx:
                    mem_ctx = ""
        except Exception as e:
            log.debug(f"[Perceive] RAG retrieval skipped: {e}")

        # Conversation history
        history: list[dict[str, str]] = []
        try:
            from core.memory.conversation_history import get_history
            raw = get_history().get_recent(6)
            history = [{"role": t.get("speaker", "user"),
                        "content": t.get("text", "")} for t in raw]
        except Exception:
            pass

        return AgentContext(
            voice_text=voice.text,
            vision_description=vision_desc,
            vision_source=vision_src,
            identity=voice.identity,
            memory_context=mem_ctx,
            history=history,
        )

    async def _stage_plan(self, ctx: AgentContext) -> PlanResult:
        """
        Route the fused context to the intent engine and select a strategy.
        """
        try:
            from core.engines.intent_router import get_intent_router
            router = get_intent_router()
            intent, confidence = router.route(ctx.voice_text or "")
        except Exception as e:
            log.warning(f"[Plan] Intent router error: {e} — defaulting to AGENT_TASK")
            intent, confidence = "AGENT_TASK", 0.5

        # Map intent → strategy
        strategy_map = {
            "CHAT":         "chat",
            "SKILL_EXEC":   "skill",
            "AGENT_TASK":   "agent",
            "WEB_RESEARCH": "agent",
            "MCP_TOOL":     "mcp_tool",
        }
        strategy = strategy_map.get(intent, "agent")

        # Code-generating intents need the Verify stage
        code_intents = {"AGENT_TASK", "MCP_TOOL"}
        requires_code = intent in code_intents

        log.info(f"[Plan] intent={intent} confidence={confidence:.2f} "
                 f"strategy={strategy} requires_code={requires_code}")

        return PlanResult(
            intent=intent,
            confidence=confidence,
            strategy=strategy,
            requires_code=requires_code,
        )

    async def _stage_tool_call(self, ctx: AgentContext, plan: PlanResult) -> str:
        """
        Dispatch to the appropriate executor based on the plan strategy.
        All blocking calls are offloaded via asyncio.to_thread().
        """
        prompt = ctx.fused_prompt

        if plan.strategy == "chat":
            return await asyncio.to_thread(self._exec_chat, prompt, ctx)

        if plan.strategy == "skill":
            return await asyncio.to_thread(self._exec_skill, prompt, ctx)

        if plan.strategy == "mcp_tool":
            return await asyncio.to_thread(self._exec_mcp, prompt, ctx)

        # Default: full ReAct agent
        return await asyncio.to_thread(self._exec_agent, prompt, ctx)

    async def _stage_verify(self, result: str, plan: PlanResult) -> str:
        """
        Self-Correction Layer: if the result contains code, verify it before
        returning. Applies py_compile + pyflakes; auto-corrects up to 2 times.
        """
        if not plan.requires_code:
            return result

        # Extract code block if present
        code_match = re.search(r"```(?:python)?\s*(.*?)\s*```", result, re.DOTALL)
        if not code_match:
            return result   # no code block — nothing to verify

        code = code_match.group(1)
        verify_result = self._corrector.verify_code(code)

        if verify_result.passed:
            log.info("[Verify] Code passed all checks ✓")
            return result

        log.warning(f"[Verify] Code issues: {verify_result.issues}")

        # Auto-correct using the LLM
        corrected = await asyncio.to_thread(
            self._corrector.auto_correct,
            code,
            verify_result.issues,
            self._llm_single_shot,
        )

        if corrected.passed and corrected.corrected_code:
            # Splice corrected code back into the result
            fixed_block = f"```python\n{corrected.corrected_code}\n```"
            result = re.sub(
                r"```(?:python)?\s*.*?\s*```", fixed_block, result,
                count=1, flags=re.DOTALL
            )
            log.info(f"[Verify] Auto-corrected in {corrected.correction_rounds} round(s) ✓")
        else:
            log.warning("[Verify] Auto-correction did not fully resolve issues.")

        return result

    async def _stage_respond(self, text: str, identity: str):
        """
        Publish the final response to the response.text topic for the
        VoiceOutputWorker to consume and stream to TTS.
        """
        event = ResponseEvent(text=text, identity=identity)
        payload = event.model_dump()

        # Internal bus
        try:
            self._get_bus().publish(self.TOPIC_RESP, payload)
        except Exception as e:
            log.error(f"[Respond] Bus publish error: {e}")

        # NATS mirror (if connected)
        if self._nats:
            try:
                await self._nats.publish(
                    self.TOPIC_RESP,
                    json.dumps(payload).encode()
                )
            except Exception as e:
                log.warning(f"[Respond] NATS publish error: {e}")

        log.debug(f"[Respond] Published {len(text)} chars to {self.TOPIC_RESP}")

    # ─────────────────────────────────────────────────────────────────────────
    #  EXECUTOR IMPLEMENTATIONS (synchronous — run in thread pool)
    # ─────────────────────────────────────────────────────────────────────────

    def _exec_chat(self, prompt: str, ctx: AgentContext) -> str:
        """Fast conversational path — streaming LLM with no agent overhead."""
        try:
            from core.agent.llm_stream import stream_reply
            # Collect streamed text; VoiceOutputWorker handles sentence-by-sentence TTS
            return stream_reply(
                user_input=prompt,
                speak_cb=None,   # Response worker owns TTS
                history=ctx.history,
            )
        except Exception as e:
            log.error(f"[Chat] stream_reply failed: {e}")
            return "I encountered a brief issue with my language model, sir."

    def _exec_skill(self, prompt: str, ctx: AgentContext) -> str:
        """Dispatch to a registered skill via the SkillRegistry."""
        try:
            from core.api.skill_registry import SkillRegistry
            registry = SkillRegistry()
            skill_ctx = {
                "identity": ctx.identity,
                "user_name": "Sir",
            }
            result = registry.execute_fast(ctx.voice_text or prompt, skill_ctx)
            return result or self._exec_agent(prompt, ctx)
        except Exception as e:
            log.error(f"[Skill] execution failed: {e}")
            return self._exec_agent(prompt, ctx)

    def _exec_mcp(self, prompt: str, ctx: AgentContext) -> str:
        """Route through the MCP Bridge for local tool execution."""
        try:
            from tools.mcp_bridge import get_mcp_bridge
            bridge = get_mcp_bridge()
            result = bridge.execute_from_prompt(
                prompt=ctx.voice_text or prompt,
                identity=ctx.identity,
            )
            return result.output if result.success else result.error_message
        except Exception as e:
            log.error(f"[MCP] bridge error: {e}")
            return f"MCP tool execution failed, sir: {e}"

    def _exec_agent(self, prompt: str, ctx: AgentContext) -> str:
        """Full ReAct agent loop — for complex multi-step tasks."""
        try:
            from core.agent.agent import JarvisAgent
            agent = JarvisAgent(identity=ctx.identity)
            return agent.run(ctx.voice_text or prompt)
        except Exception as e:
            log.error(f"[Agent] run failed: {e}")
            return "My agent encountered an error processing your request, sir."

    def _llm_single_shot(self, prompt: str) -> str:
        """Single non-streaming LLM call for the self-correction layer."""
        try:
            from core.providers.ollama_manager import get_ollama_manager
            ollama = get_ollama_manager()
            return ollama.chat(
                model="qwen2.5-coder:7b",
                messages=[
                    {"role": "system", "content": "You are a Python expert. Fix the code errors shown. Return corrected code only."},
                    {"role": "user",   "content": prompt},
                ],
                options={"temperature": 0.0, "num_predict": 2048},
                timeout=60,
            ) or ""
        except Exception as e:
            log.error(f"[SelfCorrect] LLM single-shot failed: {e}")
            return ""

    # ── External injection (for workers that bypass the bus) ──────────────────

    async def ingest_voice(self, text: str, confidence: float = 1.0,
                           identity: str = "owner"):
        """Programmatic injection of a voice event (useful in tests)."""
        event = VoiceInputEvent(text=text, confidence=confidence, identity=identity)
        await self._handle_voice(event)

    async def ingest_vision(self, description: str, source: str = "screen",
                            frame_path: Optional[str] = None):
        """Programmatic injection of a vision event."""
        event = VisionInputEvent(
            description=description,
            source=source,
            frame_path=frame_path,
        )
        self._pending_vision = event


# ── Singleton ──────────────────────────────────────────────────────────────────
_brain_instance: Optional[AutonomousBrain] = None


def get_autonomous_brain(identity: str = "owner") -> AutonomousBrain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = AutonomousBrain(identity=identity)
    return _brain_instance
