"""
core/system/approval_service.py — Non-Blocking Capability Approval Queue
=========================================================================
Structure fix 1: replaces the modal MessageBoxW with a proper approval queue.

PROBLEM WITH MessageBoxW:
  1. **Click Fatigue** — Complex tasks generate 5+ sequential popups. Users
     stop reading and click "Yes" reflexively, defeating the safety model.
  2. **Remote failure** — The popup appears on the host's monitor, not the
     remote client's. The agent hangs indefinitely waiting for a click that
     will never happen on a headless server.
  3. **Blocks the agent thread** — The calling thread is frozen until the
     modal dialog is dismissed. No timeout possible.

SOLUTION — Approval Queue with Timeout Auto-Deny:
  Approval requests are submitted to a queue. Three resolution paths exist:

  1. **UI Subscriber (local)**: The Qt HUD subscribes to approval events via
     the EventBus and shows a non-blocking toast/notification. The user's
     response (approve/deny) is fed back through an Event.

  2. **Ntfy Push (remote)**: A push notification is sent to the user's phone
     via ntfy. The user taps Approve/Deny on their phone. The callback polls
     for the response.

  3. **Timeout Auto-Deny** (safety net): If no response arrives within
     APPROVAL_TIMEOUT_S seconds, the request is automatically DENIED.
     This prevents agents from hanging indefinitely on headless servers.

BATCHING:
  Multiple consecutive approvals for the same base command pattern are
  batched into a single "Approve all N similar commands?" prompt.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

log = logging.getLogger("ApprovalService")

# How long (seconds) to wait for a response before auto-denying.
import os
APPROVAL_TIMEOUT_S: float = float(os.environ.get("JARVIS_APPROVAL_TIMEOUT", "30"))

# How many similar commands are batched before asking once.
BATCH_THRESHOLD: int = 3


@dataclass
class ApprovalRequest:
    """A single pending approval."""
    request_id: str
    command:    str
    context:    str = ""      # Extra info shown to the user
    created_at: float = field(default_factory=time.time)

    # Resolution
    _event:    threading.Event = field(default_factory=threading.Event)
    _approved: bool = False

    def approve(self):
        self._approved = True
        self._event.set()

    def deny(self):
        self._approved = False
        self._event.set()

    def wait(self, timeout: float = APPROVAL_TIMEOUT_S) -> bool:
        """Block until resolved or timeout. Returns True if approved."""
        resolved = self._event.wait(timeout=timeout)
        if not resolved:
            log.warning(
                f"[Approval] Request '{self.request_id[:8]}' timed out after "
                f"{timeout:.0f}s — auto-DENIED."
            )
        return self._approved


class ApprovalService:
    """
    Non-blocking capability approval gateway.

    All approval requests go through here. The service:
      - Publishes to EventBus (UI toast + ntfy push simultaneously)
      - Waits for a response with a hard timeout
      - Falls back to auto-deny on timeout/remote failure
    """

    def __init__(self):
        self._pending: Dict[str, ApprovalRequest] = {}
        self._lock       = threading.Lock()
        self._batch_buf: list[str] = []   # Recent commands for batching
        self._batch_lock = threading.Lock()

    # ── Core API ─────────────────────────────────────────────────────────────

    def request_approval(
        self,
        command:  str,
        context:  str = "",
        timeout:  float = APPROVAL_TIMEOUT_S,
    ) -> bool:
        """
        Request user approval for a command. Blocks the calling thread
        up to `timeout` seconds, then auto-denies.

        Returns True if approved, False if denied or timed out.
        """
        req = ApprovalRequest(
            request_id = str(uuid.uuid4()),
            command    = command,
            context    = context,
        )

        with self._lock:
            self._pending[req.request_id] = req

        # Publish via EventBus (UI + ntfy simultaneously)
        self._publish_request(req)

        try:
            approved = req.wait(timeout=timeout)
        finally:
            with self._lock:
                self._pending.pop(req.request_id, None)

        status = "APPROVED" if approved else "DENIED"
        log.info(f"[Approval] {status}: {command[:80]}")
        return approved

    def respond(self, request_id: str, approved: bool):
        """
        Called by the UI or ntfy handler to resolve a pending request.
        Thread-safe.
        """
        with self._lock:
            req = self._pending.get(request_id)
        if req is None:
            log.warning(f"[Approval] respond() for unknown request '{request_id[:8]}'")
            return
        if approved:
            req.approve()
        else:
            req.deny()

    # ── Batching ─────────────────────────────────────────────────────────────

    def request_batch_approval(self, commands: list[str], timeout: float = APPROVAL_TIMEOUT_S) -> bool:
        """
        Ask for approval for a batch of similar commands in a single prompt.
        Returns True if the batch is approved, False otherwise.
        """
        summary = f"Approve {len(commands)} shell commands?\n" + "\n".join(
            f"  {i+1}. {c[:80]}" for i, c in enumerate(commands[:5])
        )
        if len(commands) > 5:
            summary += f"\n  ... and {len(commands) - 5} more."
        return self.request_approval(summary, context="Batch approval", timeout=timeout)

    # ── EventBus integration ──────────────────────────────────────────────────

    def _publish_request(self, req: ApprovalRequest):
        """Publish the approval request to EventBus for UI and ntfy routing."""
        try:
            from core.system.event_bus import get_event_bus
            from core.system.events import EventApprovalRequest
            get_event_bus().publish(EventApprovalRequest(
                request_id = req.request_id,
                command    = req.command,
                context    = req.context,
                timeout_s  = APPROVAL_TIMEOUT_S,
            ))
            log.info(
                f"[Approval] Request published: '{req.command[:60]}' "
                f"(id={req.request_id[:8]}, timeout={APPROVAL_TIMEOUT_S:.0f}s)"
            )
        except Exception as exc:
            log.error(f"[Approval] Failed to publish request: {exc}")
            # Fallback: if EventBus publish fails, use platform dialog
            self._fallback_dialog(req)

    def _fallback_dialog(self, req: ApprovalRequest):
        """
        Last-resort fallback when EventBus is unavailable.
        Uses platform-appropriate dialog, never MessageBoxW directly.
        """
        from core.system.platform import is_windows
        approved = False
        try:
            if is_windows():
                import ctypes
                text  = f"JARVIS is requesting permission:\n\n{req.command}\n\nAllow? (auto-denies in {APPROVAL_TIMEOUT_S:.0f}s)"
                title = "Security Capability Request"
                # Run in a thread so we can enforce the timeout ourselves
                result_holder = [False]
                def _show():
                    r = ctypes.windll.user32.MessageBoxW(0, text, title, 4 | 0x30 | 0x40000)
                    result_holder[0] = (r == 6)  # IDYES = 6
                t = threading.Thread(target=_show, daemon=True)
                t.start()
                t.join(timeout=APPROVAL_TIMEOUT_S)
                approved = result_holder[0]
            else:
                # Non-Windows: log only — auto-deny
                log.warning(f"[Approval] Non-interactive fallback — auto-denying: {req.command[:60]}")
        except Exception as exc:
            log.error(f"[Approval] Fallback dialog error: {exc}")

        if approved:
            req.approve()
        else:
            req.deny()


# ── Module singleton ─────────────────────────────────────────────────────────

_instance: Optional[ApprovalService] = None
_init_lock = threading.Lock()


def get_approval_service() -> ApprovalService:
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                _instance = ApprovalService()
    return _instance
