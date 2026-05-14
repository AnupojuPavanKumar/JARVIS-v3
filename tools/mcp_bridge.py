# tools/mcp_bridge.py — JARVIS MODEL CONTEXT PROTOCOL BRIDGE
# ──────────────────────────────────────────────────────────────────────────────
# Connects the LLM reasoning loop to local system tools via MCP-style dispatch.
#
# Available tool categories:
#   filesystem  — read, write, list, search files
#   terminal    — execute shell commands (sandboxed)
#   browser     — open URLs, take screenshots, extract page content
#   system      — get hardware stats, kill processes (sandboxed)
#
# Safety Sandbox:
#   Destructive commands (delete, format, kill, rm -rf, etc.) require a
#   confidence score >= DESTRUCTIVE_CONFIDENCE_THRESHOLD (default 0.92).
#   Commands targeting protected paths are ALWAYS blocked regardless of score.
#   All executions are logged with their confidence score and identity.
#
# MCP Protocol:
#   Tools are described as JSON schemas (tool_schemas list).
#   The LLM sends a ToolCall request; this bridge validates and dispatches it.
#   Results are returned as ToolResult objects.
#
# RTX 4050 Note:
#   This bridge does NOT load any models — it is zero-VRAM.
#   The scoring for sandbox confidence uses a small heuristic classifier,
#   not an LLM, to avoid VRAM overhead during tool execution.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, validator

from core.system.execution_governance import get_governance, ActionProposal
from core.evaluation.metrics import get_metrics
from core.system.observability import get_observability
from core.testing.failure_injector import get_failure_injector

log = logging.getLogger("MCPBridge")

# ── Safety configuration ───────────────────────────────────────────────────────
DESTRUCTIVE_CONFIDENCE_THRESHOLD = 0.92   # minimum to allow destructive ops
COMMAND_TIMEOUT_S                = 30     # max seconds per shell command
BROWSER_TIMEOUT_S                = 15     # max seconds per browser action

# Paths that can never be touched, regardless of confidence
PROTECTED_PATHS: set[str] = {
    "c:/windows",
    "c:\\windows",
    "c:/program files",
    "c:\\program files",
    "c:/system32",
    "c:\\system32",
}

# Shell patterns that classify as destructive
_DESTRUCTIVE_PATTERNS = re.compile(
    r"\b(rm\s+-rf|del\s+/[sq]|format\s+[a-z]:?|rmdir\s+/[sq]|"
    r"shutdown|reboot|taskkill|kill\s+-9|dd\s+if=|mkfs|fdisk|"
    r"DROP\s+DATABASE|TRUNCATE\s+TABLE|DELETE\s+FROM\b)\b",
    re.IGNORECASE,
)

# Read-only FS patterns (safe)
_READONLY_PATTERNS = re.compile(
    r"\b(cat|less|head|tail|grep|find|ls|dir|type|more|echo|ping|"
    r"ipconfig|ifconfig|whoami|hostname|python\s+--version|pip\s+list)\b",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ToolCall(BaseModel):
    """An LLM-generated tool invocation request."""
    tool:       str
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    identity:   str   = "owner"
    request_id: str   = Field(default_factory=lambda: f"req_{int(time.time()*1000)}")


class ToolResult(BaseModel):
    """Result returned to the LLM after tool execution."""
    request_id:    str
    tool:          str
    success:       bool
    output:        str = ""
    error_message: str = ""
    blocked:       bool = False
    block_reason:  str = ""
    duration_ms:   int = 0
    timestamp:     float = Field(default_factory=time.time)


class ToolSchema(BaseModel):
    """MCP-style tool description exposed to the LLM for function calling."""
    name:        str
    description: str
    parameters:  dict[str, Any]



# ═══════════════════════════════════════════════════════════════════════════════
#  TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class _FilesystemTool:
    """Safe file system operations."""

    def read(self, path: str, encoding: str = "utf-8") -> str:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] File not found: {path}"
        if not p.is_file():
            return f"[ERROR] Path is not a file: {path}"
        try:
            content = p.read_text(encoding=encoding, errors="replace")
            # Cap output to avoid context overflow
            if len(content) > 8000:
                content = content[:8000] + f"\n... [truncated — {len(content)} chars total]"
            return content
        except Exception as e:
            return f"[ERROR] Read failed: {e}"

    def write(self, path: str, content: str, encoding: str = "utf-8") -> str:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding=encoding)
            return f"[OK] Written {len(content)} chars to {path}"
        except Exception as e:
            return f"[ERROR] Write failed: {e}"



    def list(self, path: str, pattern: str = "*") -> str:
        try:
            p = Path(path)
            if not p.exists():
                return f"[ERROR] Path not found: {path}"
            entries = sorted(p.glob(pattern))
            lines   = []
            for e in entries[:200]:  # cap at 200 entries
                kind = "DIR " if e.is_dir() else "FILE"
                size = f" ({e.stat().st_size} B)" if e.is_file() else ""
                lines.append(f"  [{kind}] {e.name}{size}")
            return f"Directory: {path}\n" + "\n".join(lines)
        except Exception as e:
            return f"[ERROR] List failed: {e}"



    def delete(self, path: str) -> str:
        """Deletion is permitted only if sandbox approved (checked before dispatch)."""
        try:
            import shutil
            p = Path(path)
            if not p.exists():
                return f"[ERROR] Path not found: {path}"
            if p.is_dir():
                shutil.rmtree(p)
                return f"[OK] Deleted directory: {path}"
            p.unlink()
            return f"[OK] Deleted file: {path}"
        except Exception as e:
            return f"[ERROR] Delete failed: {e}"


class _TerminalTool:
    """Sandboxed shell command executor."""

    def run(self, command: str, cwd: Optional[str] = None,
            timeout: int = COMMAND_TIMEOUT_S) -> str:
        """
        Execute a shell command. Returns combined stdout + stderr.
        Blocked commands never reach this method (sandbox pre-filters them).
        """
        try:
            effective_cwd = cwd or os.path.expanduser("~")
            # Use PowerShell on Windows for consistent behaviour
            shell_prefix = ["powershell", "-NoProfile", "-Command"] \
                if os.name == "nt" else ["/bin/bash", "-c"]

            result = subprocess.run(
                shell_prefix + ([command] if os.name == "nt" else [command]),
                capture_output=True,
                text=True,
                cwd=effective_cwd,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            output_parts = []
            if result.stdout.strip():
                output_parts.append(result.stdout.strip())
            if result.stderr.strip():
                output_parts.append(f"[STDERR]\n{result.stderr.strip()}")

            exit_code_line = f"\n[Exit code: {result.returncode}]"
            full_output    = "\n".join(output_parts) + exit_code_line

            # Cap output length
            if len(full_output) > 6000:
                full_output = full_output[:6000] + "\n... [output truncated]"
            return full_output

        except subprocess.TimeoutExpired:
            return f"[TIMEOUT] Command exceeded {timeout}s limit."
        except Exception as e:
            return f"[ERROR] Terminal execution failed: {e}"


class _BrowserTool:
    """Browser interaction using Playwright (if installed) or requests fallback."""

    def open_and_read(self, url: str) -> str:
        """Fetch page content as plain text."""
        # Playwright preferred (JS rendering)
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page    = browser.new_page()
                page.goto(url, timeout=BROWSER_TIMEOUT_S * 1000)
                text    = page.inner_text("body")
                browser.close()
            text = text.strip()
            if len(text) > 5000:
                text = text[:5000] + "\n... [truncated]"
            return text
        except ImportError:
            pass
        # Requests + BS4 fallback (static pages only)
        try:
            import requests
            from bs4 import BeautifulSoup
            r    = requests.get(url, timeout=BROWSER_TIMEOUT_S,
                                headers={"User-Agent": "JARVIS/3.0"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text(separator=" ", strip=True)[:5000]
            return text
        except Exception as e:
            return f"[ERROR] Browser fetch failed: {e}"




# ═══════════════════════════════════════════════════════════════════════════════
#  MCP BRIDGE
# ═══════════════════════════════════════════════════════════════════════════════

# Tool schemas exposed to the LLM for function calling
TOOL_SCHEMAS: list[ToolSchema] = [
    ToolSchema(
        name="filesystem_read",
        description="Read the contents of a local file.",
        parameters={"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
        }, "required": ["path"]},
    ),
    ToolSchema(
        name="filesystem_write",
        description="Write content to a local file (creates directories as needed).",
        parameters={"type": "object", "properties": {
            "path":    {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
    ),
    ToolSchema(
        name="filesystem_list",
        description="List files in a directory.",
        parameters={"type": "object", "properties": {
            "path":    {"type": "string"},
            "pattern": {"type": "string", "default": "*"},
        }, "required": ["path"]},
    ),
    ToolSchema(
        name="filesystem_delete",
        description="Delete a file or directory. DESTRUCTIVE — requires high confidence.",
        parameters={"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]},
    ),
    ToolSchema(
        name="terminal_run",
        description="Execute a shell command and return stdout/stderr.",
        parameters={"type": "object", "properties": {
            "command": {"type": "string"},
            "cwd":     {"type": "string", "description": "Working directory (optional)"},
            "timeout": {"type": "integer", "default": 30},
        }, "required": ["command"]},
    ),
    ToolSchema(
        name="browser_read",
        description="Fetch and extract text content from a URL.",
        parameters={"type": "object", "properties": {
            "url": {"type": "string"},
        }, "required": ["url"]},
    ),
]


class MCPBridge:
    """
    Model Context Protocol Bridge.
    Maps LLM tool calls to local system actions through the ExecutionGovernanceLayer.
    """

    def __init__(self):
        self._governance = get_governance()
        self._fs       = _FilesystemTool()
        self._terminal = _TerminalTool()
        self._browser  = _BrowserTool()
        self._log_path = os.path.join("memory", "mcp_audit.jsonl")
        os.makedirs("memory", exist_ok=True)
        log.info("[MCPBridge] Initialised with Governance Layer.")

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_tool_schemas(self) -> list[dict]:
        """Return tool schemas as plain dicts for LLM function-calling API."""
        return [s.model_dump() for s in TOOL_SCHEMAS]

    def execute(self, call: ToolCall) -> ToolResult:
        """
        Main dispatch entry point.
        1. Validate via ExecutionGovernanceLayer.
        2. Snapshot if necessary.
        3. Route to tool implementation.
        4. Log & Observe result.
        """
        start_ms = int(time.time() * 1000)

        # STAGE 1: PROPOSAL
        proposal = ActionProposal(
            tool=call.tool,
            parameters=call.parameters,
            confidence=call.confidence,
            identity=call.identity,
            profile="admin" if call.identity == "owner" else "developer"
        )

        # STAGE 2: VALIDATION
        val_result = self._governance.validate_proposal(proposal)
        if not val_result.allowed:
            # Track invalid shell commands if blocked by safety profile
            if call.tool == "terminal_run":
                get_metrics().record_invalid_shell_command()
                
            result = ToolResult(
                request_id=call.request_id,
                tool=call.tool,
                success=False,
                blocked=True,
                block_reason=val_result.reason,
                duration_ms=0,
            )
            self._audit(call, result)
            return result

        # STAGE 5 PREP: SNAPSHOT
        snapshot_id = self._governance.create_recovery_snapshot(proposal)

        # STAGE 3: EXECUTION
        output      = ""
        error_msg   = ""
        success     = True
        try:
            # CHAOS INJECTION: Validator Rejection
            if get_failure_injector().should_inject("execution", "validator_rejection"):
                raise Exception("[CHAOS] Simulated validator rejection post-approval.")
            
            # CHAOS INJECTION: Subprocess Crash
            if get_failure_injector().should_inject("execution", "subprocess_crash"):
                raise Exception("[CHAOS] Simulated subprocess crash during tool execution.")
                
            # CHAOS INJECTION: Filesystem Corrupted Write
            if call.tool == "filesystem_write" and get_failure_injector().should_inject("filesystem", "corrupted_write"):
                raise Exception("[CHAOS] Simulated filesystem corrupted write.")
                
            output = self._dispatch(call)
        except Exception as e:
            log.error(f"[MCPBridge] Tool execution error ({call.tool}): {e}")
            error_msg = str(e)
            success   = False
            
            # STAGE 5: RECOVERY
            if snapshot_id:
                rollback_success = self._governance.rollback_snapshot(snapshot_id)
                if rollback_success:
                    error_msg += " [Automated Rollback Successful]"
                else:
                    error_msg += " [Automated Rollback FAILED]"

        duration_ms = int(time.time() * 1000) - start_ms
        
        # STAGE 4: OBSERVATION
        self._governance.observe_execution(call.tool, success, output, duration_ms)
        
        get_observability().log_tool_execution(
            tool_name=call.tool,
            success=success,
            rationale=f"Executed tool '{call.tool}' per agent reasoning.",
            duration_ms=duration_ms
        )
        if not success:
            get_observability().log_failure(
                component="MCPBridge",
                operation=call.tool,
                error=error_msg,
                rationale="Tool execution failed, potentially due to bad syntax or missing permissions."
            )
        
        result = ToolResult(
            request_id=call.request_id,
            tool=call.tool,
            success=success,
            output=output,
            error_message=error_msg,
            duration_ms=duration_ms,
        )
        self._audit(call, result)
        return result

    def execute_from_prompt(self, prompt: str,
                            identity: str = "owner",
                            confidence: float = 0.85) -> ToolResult:
        """
        Parse a natural-language prompt into a ToolCall and execute it.
        Used by AutonomousBrain._exec_mcp() for direct prompt → tool dispatch.
        """
        call = self._parse_prompt_to_tool_call(prompt, identity, confidence)
        if call is None:
            return ToolResult(
                request_id=f"req_{int(time.time()*1000)}",
                tool="unknown",
                success=False,
                error_message="Could not parse prompt into a tool call.",
            )
        return self.execute(call)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _dispatch(self, call: ToolCall) -> str:
        p = call.parameters
        t = call.tool

        # Filesystem
        if t == "filesystem_read":
            return self._fs.read(p["path"], p.get("encoding", "utf-8"))
        if t == "filesystem_write":
            return self._fs.write(p["path"], p["content"], p.get("encoding", "utf-8"))
        if t == "filesystem_list":
            return self._fs.list(p["path"], p.get("pattern", "*"))
        if t == "filesystem_delete":
            return self._fs.delete(p["path"])

        # Terminal
        if t == "terminal_run":
            return self._terminal.run(
                p["command"],
                cwd=p.get("cwd"),
                timeout=p.get("timeout", COMMAND_TIMEOUT_S),
            )

        # Browser
        if t == "browser_read":
            return self._browser.open_and_read(p["url"])

        # Unknown Tool (Hallucinated)
        get_metrics().record_hallucinated_tool_call()
        return f"[ERROR] Unknown tool: {t}"

    def _parse_prompt_to_tool_call(self, prompt: str, identity: str,
                                   confidence: float) -> Optional[ToolCall]:
        """
        Heuristic prompt → ToolCall parser.
        Covers common patterns without needing an LLM pass.
        For complex prompts, callers should pre-parse via LLM function calling.
        """
        p = prompt.lower().strip()

        # File read
        m = re.search(r"(?:read|show|open|cat)\s+['\"]?([^\s'\"]+\.[a-z]{1,5})['\"]?", p)
        if m:
            return ToolCall(tool="filesystem_read", identity=identity,
                            confidence=confidence,
                            parameters={"path": m.group(1)})

        # File list
        m = re.search(r"(?:list|ls|dir)\s+['\"]?([^\s'\"]+)['\"]?", p)
        if m:
            return ToolCall(tool="filesystem_list", identity=identity,
                            confidence=confidence,
                            parameters={"path": m.group(1)})

        # Terminal command
        m = re.search(r"(?:run|execute|shell|cmd|terminal)\s+['\"]?(.+?)['\"]?$", prompt, re.I)
        if m:
            return ToolCall(tool="terminal_run", identity=identity,
                            confidence=confidence,
                            parameters={"command": m.group(1)})

        # Browser URL
        m = re.search(r"https?://\S+", prompt)
        if m:
            return ToolCall(tool="browser_read", identity=identity,
                            confidence=confidence,
                            parameters={"url": m.group(0)})

        # System stats
        if any(kw in p for kw in ("cpu", "ram", "memory", "vram", "disk", "stats", "usage")):
            return ToolCall(tool="system_stats", identity=identity,
                            confidence=confidence, parameters={})

        return None

    def _audit(self, call: ToolCall, result: ToolResult):
        """Append an audit entry to the MCP log (JSONL, non-blocking)."""
        try:
            entry = {
                "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%S"),
                "tool":       call.tool,
                "identity":   call.identity,
                "confidence": call.confidence,
                "blocked":    result.blocked,
                "block_reason": result.block_reason,
                "success":    result.success,
                "duration_ms": result.duration_ms,
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.debug(f"[MCPBridge] Audit log error: {e}")


# ── Singleton ──────────────────────────────────────────────────────────────────
_bridge_instance: Optional[MCPBridge] = None


def get_mcp_bridge() -> MCPBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = MCPBridge()
    return _bridge_instance
