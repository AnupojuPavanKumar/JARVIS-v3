# core/router/fast_router.py — JARVIS Fast Command Router (v3)
"""
Two-layer routing with tokenized scoring, LRU cache, command decomposition, and queue.

Layer 1 (< 50ms): TriggerScorer + LRU cache + command decomposition
Layer 2:           IntentRouter + JarvisAgent (LLM fallback)

Confidence thresholds:
  >= 0.85 → deterministic execution (no LLM)
  <  0.85 → AI reasoning fallback
"""
from __future__ import annotations

import logging
import time
from typing import Optional, Tuple

from core.intents.command_patterns import FastIntent, resolve_intent
from core.intents.trigger_scoring import get_trigger_scorer, TriggerScorer
from core.intents.lru_cache import cache_lookup, cache_store, get_lru_cache
from core.intents.command_decomposer import get_decomposer, CommandDecomposer
from core.executor.deterministic_executor import get_executor
from core.executor.action import Action, ActionType
from core.executor.execution_queue import get_execution_queue
from core.intents.context_resolver import get_context_resolver, Entity, EntityType
from core.intents.command_patterns import OPEN_APP_TRIGGERS
from core.companion.phrase_rotation import get_rotator

log = logging.getLogger("FastRouter")

DETERMINISTIC_THRESHOLD = 0.85

# Commands that ALWAYS go to AI (planning/coding/research)
AI_ONLY_TRIGGERS = {
    "build", "create a", "make a", "generate a", "write a", "develop a",
    "script that", "program that", "code that", "automate", "deploy",
    "analyze", "analyse", "summarize", "summarise", "research",
    "fix bug", "debug", "refactor", "implement", "scaffold",
    "explain this", "why is", "how does", "tell me about",
}


class FastRouter:
    """
    Two-layer routing engine.

    Layer 1: TriggerScorer (tokenized) → LRU cache check → confidence → execute/decompose
    Layer 2: Return None → jarvis_brain routes to IntentRouter + JarvisAgent
    """

    _instance: Optional["FastRouter"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._scorer = get_trigger_scorer()
            cls._instance._cache = get_lru_cache()
            cls._instance._decomposer = get_decomposer()
            cls._instance._executor = get_executor()
            cls._instance._rotator = get_rotator()
        return cls._instance

    def route(self, command: str) -> Tuple[FastIntent, bool]:
        """
        Main entry point. Returns (FastIntent, is_deterministic).
        """
        t0 = time.perf_counter()
        cmd_key = command.lower().strip()

        # ── Context resolution (pronouns, references, "it/that/again") ─────────
        resolver = get_context_resolver()
        resolved, entity_type = resolver.resolve_reference(command)

        # ── Workspace context enrichment ─────────────────────────────────────────
        # Add current app context to resolver for "fix this" / "explain this" commands
        ctx_keywords = ["fix this", "explain this", "what is this", "debug this",
                        "check this", "read this", "summarize this"]
        if any(k in cmd_key for k in ctx_keywords):
            try:
                from core.context.workspace import get_workspace_observer
                ws = get_workspace_observer()
                cur_app = ws.current_app
                cur_title = ws.current_window_title
                if cur_app:
                    from core.intents.context_resolver import Entity, EntityType
                    resolver.record_entity(Entity(
                        type=EntityType.APP,
                        name=cur_app,
                        identifier=cur_app,
                        metadata={"title": cur_title},
                    ))
                    log.debug(f"[FastRouter] Workspace context: {cur_app} — '{cur_title}'")
            except Exception:
                pass

        if resolved:
            log.debug(f"[FastRouter] Context resolved: '{resolved}' ({entity_type.name})")
            resolver.set_last_command(command)
            if entity_type == EntityType.APP:
                # "open it again" → "open {app_name}"
                if not any(t in cmd_key for t in OPEN_APP_TRIGGERS):
                    cmd_key = "open " + resolved
                else:
                    # Already has open trigger — just update target
                    cmd_key = command.lower().replace(
                        next((t for t in OPEN_APP_TRIGGERS if t in command.lower()), "open "),
                        "open "
                    ) + " " + resolved
                    cmd_key = "open " + resolved  # simplified
            elif entity_type == EntityType.WINDOW:
                # "close that" → close the focused window
                pass  # resolver already has the window info
            elif entity_type == EntityType.MEDIA:
                # "resume the music" → media play
                cmd_key = "play " + resolved

        # ── Memory lookup shortcuts ─────────────────────────────────────────────
        # "what were we doing" → layered memory L1 narrative
        what_signals = ["what were we doing", "what was i working on",
                        "what was i doing", "what are we doing",
                        "tell me what we did", "session summary", "what happened"]
        if any(s in cmd_key for s in what_signals):
            try:
                from core.companion.layered_memory import get_layered_memory
                lm = get_layered_memory()
                narrative = lm.what_were_we_doing()
                if narrative and narrative != "No recent work tracked.":
                    intent = FastIntent(
                        name="CACHED",
                        confidence=1.0,
                        raw_command=command,
                        params={"cached_result": narrative, "_memory_narrative": True},
                    )
                    return intent, True
            except Exception:
                pass

        # ── Session continuation shortcut ─────────────────────────────────────
        continue_signals = ["continue", "keep going", "same as before", "same thing",
                            "carry on", "go on", "still", "not done", "resume",
                            "restore workspace", "start coding session", "back to work"]
        if any(s in cmd_key for s in continue_signals):
            try:
                from core.companion.session_memory import get_session_continuity
                sc = get_session_continuity()
                if sc.should_offer_continuation():
                    text = sc.get_continuation_text()
                    if text:
                        intent = FastIntent(
                            name="CACHED",
                            confidence=1.0,
                            raw_command=command,
                            params={"cached_result": text, "_continuation": True},
                        )
                        return intent, True
            except Exception:
                pass

        # ── LRU Cache check ────────────────────────────────────────────────────
        cached = cache_lookup(cmd_key)
        if cached:
            intent = FastIntent(
                name="CACHED",
                confidence=1.0,
                raw_command=command,
                params={"cached_result": cached},
            )
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[FastRouter] Cache HIT for '{command[:40]}' in {elapsed:.2f}ms")
            return intent, True  # cached = deterministic

        # ── AI-only guard ─────────────────────────────────────────────────────
        if self._is_ai_only(cmd_key):
            intent = FastIntent(
                name="AGENT_TASK",
                confidence=1.0,
                raw_command=command,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            log.debug(f"[FastRouter] AI-only → routed to agent in {elapsed:.2f}ms")
            return intent, False

        # ── Command decomposition ──────────────────────────────────────────────
        if self._decomposer.should_decompose(command):
            decomp = self._decomposer.decompose(command)
            if decomp.is_compound:
                # Multi-action command: enqueue deterministic parts, queue AI parts
                self._handle_compound(decomp, command)
                # Return a composite response
                intent = FastIntent(
                    name="COMPOSITE",
                    confidence=0.95,
                    raw_command=command,
                    params={"decomposition": decomp},
                )
                elapsed = (time.perf_counter() - t0) * 1000
                log.debug(f"[FastRouter] Compound → {len(decomp.actions)} actions in {elapsed:.2f}ms")
                return intent, True

        # ── Tokenized intent scoring ─────────────────────────────────────────
        scored = self._scorer.best_intent(command)

        if scored:
            intent = FastIntent(
                name=scored.intent_name,
                confidence=scored.confidence,
                raw_command=command,
                target=scored.target,
                params={"matched_tokens": scored.matched_tokens},
            )
            keyword_intent = resolve_intent(command)
            if keyword_intent.confidence > intent.confidence:
                intent = keyword_intent
        else:
            # Fall back to keyword router
            intent = resolve_intent(command)

        is_det = intent.is_deterministic(DETERMINISTIC_THRESHOLD)
        elapsed = (time.perf_counter() - t0) * 1000
        log.debug(
            f"[FastRouter] '{command[:40]}' → {intent.name} "
            f"(conf={intent.confidence:.2f}, det={is_det}) in {elapsed:.1f}ms"
        )

        return intent, is_det

    def route_for_brain(self, command: str) -> Optional[str]:
        """
        Called from jarvis_brain._process_inner().
        Returns:
          - str response if deterministic execution succeeded
          - None if command should be handled by AI reasoning
        """
        t0 = time.perf_counter()

        try:
            intent, is_det = self.route(command)

            # Cache hit (including session continuation)
            if intent.name == "CACHED":
                msg = intent.params.get("cached_result", "")
                elapsed = (time.perf_counter() - t0) * 1000
                log.info(f"[FastRouter] Cache HIT → '{msg}' in {elapsed:.1f}ms")
                return msg

            # Composite (multi-action)
            if intent.name == "COMPOSITE":
                return f"Handling compound command, sir."

            if not is_det:
                return None  # → AI fallback

            # ── Execute deterministically (non-blocking acknowledgment) ─────────
            result = self._execute_fast(intent)

            elapsed = (time.perf_counter() - t0) * 1000
            log.info(f"[FastRouter] Fast-path → '{result}' in {elapsed:.1f}ms")
            return result

        except Exception as e:
            log.error(f"[FastRouter] Error: {e}")
            return None  # Fall back to AI

    def _execute_fast(self, intent: FastIntent) -> Optional[str]:
        """Non-blocking deterministic execution with immediate acknowledgment.

        Returns INSTANTLY (<50ms) with a natural acknowledgment while the
        actual action runs in the background on the execution queue.
        """
        try:
            action_type = ActionType[intent.name]
        except KeyError:
            log.warning(f"[FastRouter] Unknown intent type: {intent.name}")
            return None

        action = Action(
            action_type=action_type,
            target=intent.target or "",
            raw_command=intent.raw_command,
            confidence=intent.confidence,
            source="fast_router",
        )

        if not action.validate():
            log.warning(f"[FastRouter] Action validation failed: {action.error}")
            return None

        intent_name = intent.name
        target     = intent.target or ""
        target_cap = target.capitalize() if target else intent_name.replace("_", " ").title()

        acknowledgments = {
            "OPEN_APP":       f"On it — launching {target_cap}.",
            "CLOSE_APP":      f"Closing {target_cap}.",
            "MEDIA_CONTROL":  f"{target_cap.title()}, sir.",
            "VOLUME_CONTROL": f"Adjusting volume.",
            "SYSTEM_CONTROL": f"Executing {target}.",
            "WINDOW_CONTROL": f"{target_cap}ing window.",
            "WEB_SEARCH":     f"Searching for {target}.",
            "FILE_OPEN":      f"Opening {target}.",
            "CACHED":         None,
            "COMPOSITE":      "Handling compound command, sir.",
        }

        ack = acknowledgments.get(intent_name)
        if not ack:
            ack = self._rotator.get("completion")
        else:
            ack = self._rotator.vary_response(ack, "confirmation")

        queue = get_execution_queue()
        queue.start()
        queue.enqueue({
            "action_id": action.action_id,
            "action_type": action_type.name,
            "target": intent.target or "",
            "raw_command": intent.raw_command,
            "confidence": intent.confidence,
            "priority": action.priority,
        })

        # ── Record entity for conversational continuity ───────────────────
        resolver = get_context_resolver()
        target_str = intent.target or ""
        if target_str:
            if intent_name == "OPEN_APP":
                resolver.record_entity(Entity(
                    type=EntityType.APP,
                    name=target_str,
                    identifier=target_str,
                ))
            elif intent_name == "MEDIA_CONTROL":
                resolver.record_entity(Entity(
                    type=EntityType.MEDIA,
                    name=target_str,
                    identifier=target_str,
                ))

        cache_store(intent.raw_command, ack, intent.confidence)
        return ack

    def _execute_det(self, intent: FastIntent) -> Optional[str]:
        """Blocking deterministic execution (legacy path used by _handle_compound)."""
        try:
            action_type = ActionType[intent.name]
        except KeyError:
            log.warning(f"[FastRouter] Unknown intent type: {intent.name}")
            return None

        action = Action(
            action_type=action_type,
            target=intent.target or "",
            raw_command=intent.raw_command,
            confidence=intent.confidence,
            source="fast_router",
        )

        if not action.validate():
            log.warning(f"[FastRouter] Action validation failed: {action.error}")
            return None

        queue = get_execution_queue()
        queue.start()
        future = queue.enqueue({
            "action_id": action.action_id,
            "action_type": action_type.name,
            "target": intent.target or "",
            "raw_command": intent.raw_command,
            "confidence": intent.confidence,
            "priority": action.priority,
        })

        if future.wait(timeout=5.0):
            result_data = future.result
            cache_store(intent.raw_command, result_data.get("message", ""), intent.confidence)
            return result_data.get("message", "")
        else:
            log.warning(f"[FastRouter] Execution timeout for {intent.name}")
            return f"Executing {intent.target or intent.name}, sir."

    def _handle_compound(self, decomp, original_command: str):
        """Execute compound command actions in order."""
        queue = get_execution_queue()
        queue.start()

        for i, sub_action in enumerate(decomp.actions):
            cmd = sub_action.command
            try:
                intent, is_det = self.route(cmd)
                if is_det:
                    self._execute_det(intent)
                else:
                    # AI sub-action — handled separately by the AI layer
                    log.debug(f"[FastRouter] Compound AI sub-action: '{cmd}'")
            except Exception as e:
                log.error(f"[FastRouter] Compound sub-action error: {e}")

    def _is_ai_only(self, cmd_lower: str) -> bool:
        """Commands requiring multi-step planning/coding/research go to AI."""
        return any(t in cmd_lower for t in AI_ONLY_TRIGGERS)

    @property
    def cache_stats(self) -> dict:
        return self._cache.stats

    def prune_cache(self):
        """Prune expired cache entries."""
        return self._cache.prune_expired()


def get_fast_router() -> FastRouter:
    return FastRouter()
