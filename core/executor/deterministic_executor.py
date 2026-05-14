# core/executor/deterministic_executor.py — JARVIS Deterministic Executor (v3)
"""
Plugin-style deterministic execution layer.
  - Plugin executors: app, media, volume, system, window
  - ExecutionQueue for thread-safe background execution
  - Safety validation before every action
  - Pre-execution validation
  - Structured Action objects
  - Zero LLM involvement
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
from typing import Optional

from core.executor.action import Action, ActionState, ActionType
from core.executor.execution_queue import get_execution_queue
from core.executor.execution_safety import get_safety_validator
from core.executor.app_executor import get_app_executor
from core.executor.media_executor import MediaExecutor
from core.executor.volume_executor import get_volume_executor
from core.executor.system_executor import SystemExecutor
from core.executor.window_executor import WindowExecutor

log = logging.getLogger("DeterministicExecutor")

MAX_EXEC_TIME_SEC = 5.0

# ── Plugin registry ────────────────────────────────────────────────────────────

class ExecutorRegistry:
    """Registry of plugin executors by action type."""

    def __init__(self):
        self._plugins: dict[str, object] = {}

    def register(self, name: str, plugin: object):
        self._plugins[name] = plugin

    def get(self, name: str) -> Optional[object]:
        return self._plugins.get(name)

    def initialize(self):
        self.register("app", get_app_executor())
        self.register("media", MediaExecutor())
        self.register("volume", get_volume_executor())
        self.register("system", SystemExecutor())
        self.register("window", WindowExecutor())

    def execute(self, action: Action) -> tuple[bool, str]:
        """Dispatch an action to the appropriate plugin executor."""
        plugin_map = {
            ActionType.OPEN_APP:        ("app", "open"),
            ActionType.CLOSE_APP:       ("app", "close"),
            ActionType.MEDIA_CONTROL:   ("media", "control"),
            ActionType.VOLUME_CONTROL:   ("volume", "set_volume"),
            ActionType.SYSTEM_CONTROL:   ("system", "control"),
            ActionType.WINDOW_CONTROL:   ("window", "control"),
        }

        entry = plugin_map.get(action.action_type)
        if entry is None:
            return False, f"No executor for {action.action_type.name}"

        plugin_name, method_name = entry
        plugin = self.get(plugin_name)
        if plugin is None:
            return False, f"Plugin '{plugin_name}' not loaded"

        method = getattr(plugin, method_name, None)
        if method is None:
            return False, f"Plugin '{plugin_name}' has no method '{method_name}'"

        try:
            # For APP executor, pass the Action object
            if plugin_name == "app":
                return method(action)
            # For others, pass target string
            return method(action.target or "")
        except Exception as e:
            log.error(f"[ExecutorRegistry] {plugin_name}.{method_name} error: {e}")
            return False, f"Execution failed: {e}"


_executor_registry: Optional[ExecutorRegistry] = None


def _get_registry() -> ExecutorRegistry:
    global _executor_registry
    if _executor_registry is None:
        _executor_registry = ExecutorRegistry()
        _executor_registry.initialize()
    return _executor_registry


class DeterministicExecutor:
    """
    Central deterministic execution engine.
    Single instance, thread-safe.

    Supports two execution modes:
      1. Direct (blocking) — for quick validation tests
      2. Queued (async) — via ExecutionQueue, always preferred
    """

    _instance: Optional["DeterministicExecutor"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._registry = _get_registry()
            cls._instance._queue = None
            cls._instance._safety = get_safety_validator()
        return cls._instance

    # ── Main execution ─────────────────────────────────────────────────────────

    def execute_action(self, action: Action) -> tuple[bool, str]:
        """
        Execute a single Action deterministically.
        Returns (success, message).
        """
        # Pre-execution validation
        if action.state == ActionState.VALIDATED:
            pass  # already validated

        # Pre-validation if coming from queue
        if action.state == ActionState.PENDING:
            if not action.validate():
                return False, action.error or "Validation failed"

        action.start()

        try:
            # WEB_SEARCH — handled inline
            if action.action_type == ActionType.WEB_SEARCH:
                success, msg = self._web_search(action)
                if success:
                    action.complete(msg)
                else:
                    action._fail(msg)
                return success, msg

            # FILE_OPEN — handled inline
            if action.action_type == ActionType.FILE_OPEN:
                success, msg = self._file_open(action)
                if success:
                    action.complete(msg)
                else:
                    action._fail(msg)
                return success, msg

            # All other intents → plugin executor
            success, msg = self._registry.execute(action)
            if success:
                action.complete(msg)
            else:
                action._fail(msg)
            return success, msg

        except Exception as e:
            log.error(f"[DeterministicExecutor] Unhandled error: {e}")
            action._fail(str(e), "Unhandled exception in executor")
            return False, f"Execution error: {e}"

    # ── Queue-backed execution ────────────────────────────────────────────────

    def enqueue(self, action: Action) -> "ExecutionFuture":
        """
        Enqueue an action for background execution.
        Returns an ExecutionFuture for tracking.
        """
        if self._queue is None:
            self._queue = get_execution_queue()
            self._queue.start()

        action_dict = {
            "action_id": action.action_id,
            "action_type": action.action_type.name,
            "target": action.target,
            "raw_command": action.raw_command,
            "confidence": action.confidence,
            "source": action.source,
            "priority": action.priority,
            "params": action.params,
        }

        return self._queue.enqueue(
            action_dict,
            timeout=MAX_EXEC_TIME_SEC,
            priority=action.priority,
        )

    def enqueue_and_forget(self, action: Action):
        """Fire-and-forget enqueue."""
        if self._queue is None:
            self._queue = get_execution_queue()
            self._queue.start()
        self._queue.enqueue_and_forget({
            "action_id": action.action_id,
            "action_type": action.action_type.name,
            "target": action.target,
            "raw_command": action.raw_command,
            "confidence": action.confidence,
            "priority": action.priority,
        })

    # ── Inline handlers ───────────────────────────────────────────────────────

    def _web_search(self, action: Action) -> tuple[bool, str]:
        query = (action.target or "").strip()
        if not query:
            return False, "No search query specified."
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.bing.com/search?q={encoded}"
            os.startfile(url)
            return True, f"Searching for '{query}', sir."
        except Exception as e:
            return False, f"Web search failed: {e}"

    def _file_open(self, action: Action) -> tuple[bool, str]:
        path = (action.target or "").strip()
        if not path:
            return False, "No file path specified."
        path = os.path.abspath(path)
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        try:
            os.startfile(path)
            return True, f"Opening {os.path.basename(path)}, sir."
        except Exception as e:
            return False, f"Failed to open file: {e}"

    # ── Backward compat: execute_fast() ──────────────────────────────────────

    def execute_fast(
        self,
        intent_name: str,
        target: str,
        raw_command: str,
        identity: str = "owner",
        confidence: float = 0.95,
    ) -> str:
        """
        Backward-compatible entry point (used by FastRouter).
        Wraps intent name + target into an Action and executes directly.
        For fire-and-forget use enqueue() instead.
        """
        try:
            action_type = ActionType[intent_name]
        except KeyError:
            return f"Unknown intent: {intent_name}"

        action = Action(
            action_type=action_type,
            target=target,
            raw_command=raw_command,
            confidence=confidence,
            source="fast_router",
        )

        success, msg = self.execute_action(action)
        return msg

    # ── Queue stats ───────────────────────────────────────────────────────────

    @property
    def queue_stats(self) -> dict:
        if self._queue:
            return self._queue.stats
        return {}


def get_executor() -> DeterministicExecutor:
    return DeterministicExecutor()


def execute_fast(intent_name: str, target: str, raw: str, identity: str = "owner") -> str:
    """Convenience wrapper."""
    return get_executor().execute_fast(intent_name, target, raw, identity)