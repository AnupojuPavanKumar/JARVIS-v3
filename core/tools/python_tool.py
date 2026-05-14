# core/tools/python_tool.py  —  JARVIS PYTHON EXECUTION TOOL
# ──────────────────────────────────────────────────────────────────────────────
# Executes Python code with a two-tier safety model:
#   Tier 1 (always): Dangerous-import blocklist (prevents bypassing FileTool)
#   Tier 2a (Docker available): Isolated container (512MB RAM, no network, --rm)
#   Tier 2b (Docker unavailable): Isolated subprocess with process-group kill
# ──────────────────────────────────────────────────────────────────────────────

import subprocess
import os
import re
import signal
import sys

EXEC_FILE   = "memory/agent_exec.py"
MAX_TIMEOUT = 45    # seconds
MAX_OUTPUT  = 2500  # chars

# ── Dangerous patterns blocked BEFORE execution ───────────────────────────────
_BLOCKED_CODE_PATTERNS = [
    r"shutil\s*\.\s*rmtree",
    r"os\s*\.\s*remove\s*\(",
    r"os\s*\.\s*unlink\s*\(",
    r"os\s*\.\s*rmdir\s*\(",
    r"pathlib.*\.unlink\s*\(",
    r"subprocess.*shell\s*=\s*True",
    r"__import__\s*\(\s*['\"]os",
    r"ctypes",
    r"winreg",
    r"sys\.exit\s*\(",
    r"eval\s*\(",
    r"exec\s*\(",
    r"getattr\s*\(",
    r"setattr\s*\(",
    r"globals\s*\(",
    r"locals\s*\(",
    r"base64\s*\.\s*b64decode",
    r"marshal",
    r"pickle",
    r"socket",
    r"requests", # Block networking in Tier 1 if not explicitly allowed
]


class PythonTool:
    """Execute Python code snippets in a Docker sandbox. Host execution is disabled for safety."""

    def run(self, code: str) -> str:
        # ── Tier 1: Safety pre-scan (always runs) ──
        for pattern in _BLOCKED_CODE_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return (
                    f"[BLOCKED] Dangerous pattern detected ({pattern!r}). "
                    f"Use write_file / delete_file tools for filesystem operations."
                )

        # ── Tier 2: Docker sandbox (MANDATORY) ──────────────
        try:
            from core.system.docker_sandbox import get_sandbox
            sb = get_sandbox()
            if sb.is_available():
                result = sb.run_python(code, timeout=MAX_TIMEOUT)
                if len(result) > MAX_OUTPUT:
                    result = result[:MAX_OUTPUT] + "\n... (output truncated)"
                return result
            else:
                return (
                    "[SECURITY ERROR] Docker is not available. "
                    "Autonomous code execution is disabled for safety. "
                    "Please install and start Docker Desktop to use this tool."
                )
        except Exception as e:
            return f"[SANDBOX ERROR] Failed to initialize Docker: {e}"
