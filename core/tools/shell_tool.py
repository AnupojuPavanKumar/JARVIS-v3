# core/tools/shell_tool.py  —  JARVIS SHELL TOOL
# ──────────────────────────────────────────────────────────────────────────────
# Executes PowerShell commands safely with:
#   1. Hard blocklist — system-destructive commands never execute
#   2. Owner-only gate for elevated operations
#   3. Per-call process + queue tracking — no orphaned reader threads
#   4. Background process registry so multiple concurrent shells work correctly
# ──────────────────────────────────────────────────────────────────────────────

import subprocess
import re
import threading
import queue
import time
import ctypes

# ── Blocklist ──────────────────────────────────────────────────────────────────
BLOCKED_PATTERNS = [
    r"format\s+[a-zA-Z]:",
    r"del\s+.*/[sf].*c:\\windows",
    r"rmdir\s+/s.*c:\\windows",
    r"rmdir\s+/s.*c:\\program",
    r"rd\s+/s.*c:\\windows",
    r"rd\s+/s.*c:\\program",
    r"Remove-Item.*-Recurse.*C:\\Windows",
    r"Remove-Item.*-Recurse.*C:\\Program",
    r"Remove-Item.*-Force.*C:\\Windows",
    r"del\s+/[sf].*c:\\program",
    r"Stop-Computer",
    r"Restart-Computer",
]

# Commands that trigger the UI Capability Approval Popup
HIGH_RISK_PATTERNS = [
    r"Remove-Item.*-Recurse",
    r"taskkill",
    r"Stop-Process",
    r"curl.*Invoke-WebRequest",
    r"wget",
    r"Invoke-RestMethod",
    r"Net.WebClient",
]

OWNER_ONLY_PATTERNS = [
    r"taskkill.*system",
]

def ask_permission(command: str) -> bool:
    """
    Request approval for a high-risk shell command.

    Structure fix 1: replaced blocking MessageBoxW with ApprovalService queue.
    - EventBus publishes to Qt HUD toast AND ntfy push simultaneously.
    - Hard timeout auto-denies (default 30s) so headless servers never hang.
    - CI mode auto-denies immediately.
    """
    import os
    if os.environ.get("JARVIS_CI") == "1":
        return False

    try:
        from core.system.approval_service import get_approval_service
        return get_approval_service().request_approval(
            command = command,
            context = "High-risk shell command flagged by ShellTool blocklist.",
        )
    except Exception as exc:
        import logging
        logging.warning(f"[ShellTool] ApprovalService unavailable ({exc}) — auto-denying.")
        return False  # Fail safe

# Maximum lines to keep per process output buffer
_QUEUE_MAXSIZE = 1000


class _ProcessContext:
    """
    Tracks a single background PowerShell process with its own output queue
    and reader thread. Isolates each shell invocation so they never share state.
    """
    def __init__(self, proc: subprocess.Popen):
        self.proc   = proc
        self.q      = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            for line in iter(self.proc.stdout.readline, ''):
                if not self.q.full():
                    self.q.put(line)
        except Exception:
            pass
        finally:
            try:
                self.proc.stdout.close()
            except Exception:
                pass

    def drain(self) -> str:
        """Drain all buffered lines and return as a single string."""
        lines = []
        while not self.q.empty():
            try:
                lines.append(self.q.get_nowait().rstrip('\r\n'))
            except queue.Empty:
                break
        return "\n".join(lines).strip()

    def status_text(self) -> str:
        """Return '[Process EXITED with code N]' or '[Process is RUNNING]'."""
        code = self.proc.poll()
        if code is not None:
            return f"[Process EXITED with code {code}]"
        return "[Process is RUNNING in background]"

    def terminate(self):
        """Best-effort terminate."""
        try:
            self.proc.terminate()
        except Exception:
            pass


class ShellTool:
    """Run Windows PowerShell commands with per-call process tracking."""

    def __init__(self):
        # Maps an integer call_id → _ProcessContext
        # Keeps the last N contexts so read_shell_output always reads the latest.
        self._contexts: dict[int, _ProcessContext] = {}
        self._latest_id: int = 0
        self._id_lock = threading.Lock()

    # ── Internal helpers ───────────────────────────────────────────────────────
    def _next_id(self) -> int:
        with self._id_lock:
            self._latest_id += 1
            # Evict old contexts beyond the last 10 to avoid unbounded growth
            old_ids = sorted(self._contexts.keys())[:-9] if len(self._contexts) > 9 else []
            for oid in old_ids:
                self._contexts[oid].terminate()
                del self._contexts[oid]
            return self._latest_id

    # ── Public API ─────────────────────────────────────────────────────────────
    def run(self, command: str, identity: str = "owner") -> str:
        # ── Hard blocklist ────────────────────────────────────────────────────
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return "[BLOCKED] That command is not permitted for system safety."

        # ── Owner-only gate ───────────────────────────────────────────────────
        if identity != "owner":
            for pattern in OWNER_ONLY_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    return "[DENIED] Owner clearance required for this command."

        # ── UI Capability Popup (High Risk) ───────────────────────────────────
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                # Trigger native UI popup
                if not ask_permission(command):
                    return "[DENIED] User explicitly denied this high-risk shell command via UI popup."
                break # Only ask once

        # ── Execute ───────────────────────────────────────────────────────────
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", command],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # merge stderr → stdout
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            call_id = self._next_id()
            ctx = _ProcessContext(proc)
            self._contexts[call_id] = ctx

            # Wait 2 s for initial output / crash
            time.sleep(2.0)

            output = ctx.drain()
            if len(output) > 4000:
                output = output[-4000:] + "\n... (truncated beginning)"

            status = ctx.status_text()
            return f"{status}\n{output}" if output else status

        except FileNotFoundError:
            return "PowerShell not found. Is it installed?"
        except Exception as e:
            return f"Shell execution error: {e}"

    def read_output(self, *args) -> str:
        """Read buffered output from the most recently launched shell process."""
        if not self._contexts:
            return "No active background shell process to read from."

        with self._id_lock:
            latest_id = self._latest_id

        ctx = self._contexts.get(latest_id)
        if ctx is None:
            return "No active background shell process to read from."

        output = ctx.drain()
        if len(output) > 4000:
            output = output[-4000:] + "\n... (truncated beginning)"

        status = ctx.status_text()
        return f"{status}\n{output}" if output else status
