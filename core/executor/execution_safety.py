# core/executor/execution_safety.py
"""
Enhanced execution safety with trust levels, configurable trust policies,
per-executable metadata, audit logging, and execution permission escalation.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

log = logging.getLogger("Safety")

DANGEROUS_PATTERNS = [
    r"\.\./", r"\.\.\\", r";.*rm\s", r";\s*del\s", r";\s*format\s",
    r"\|.*rm\s", r"\bredirection", r"\$\([^)]+\)", r"`[^`]+`",
    r">\s*/dev/", r"</dev/", r"2>&1.*(rm|del|format)",
]
BLOCKED_EXECUTABLES = {
    "cmd.exe", "cmd.com", "command.com", "powershell.exe", "powershell",
    "pwsh.exe", "bash.exe", "sh.exe", "zsh.exe", "fish.exe",
    "python.exe", "python", "perl.exe", "ruby.exe", "php.exe",
    "cscript.exe", "wscript.exe", "mshta.exe", "msiexec.exe",
    "rundll32.exe", "regsvr32.exe", "certutil.exe", "bitsadmin.exe",
    "cmstp.exe", "ftp.exe", "tftp.exe", "nc.exe", "netcat.exe",
    "ncat.exe", "socat.exe", "mettle.exe", "empire.exe",
    "msfvenom.exe", "payload.exe", "backdoor.exe", "rootkit.exe",
}
DANGEROUS_PATH_PREFIXES = [
    r"c:\windows\system32\cmd", r"c:\windows\system32\cscript",
    r"c:\windows\system32\wscript", r"c:\windows\system32\mshta",
    r"c:\windows\system32\powershell", r"c:\windows\system32\regsvr32",
    r"c:\windows\system32\rundll32", r"c:\windows\system32\certutil",
    r"c:\windows\system32\bitsadmin", r"c:\windows\system32\cmstp",
]
BLOCKED_SHELL_PATTERNS = [
    r"del\s+c:\\windows", r"rm\s+-rf\s+/", r"format\s+[a-z]:",
    r"shutdown", r"sysprep", r"bcdedit", r"wbadmin",
    r"takeown\s+/r", r"icacls\s+.*/grant", r"net\s+user\s+.*\/add",
    r"net\s+localgroup\s+.*\/add",
    r"reg\s+(delete|add)\s+hklm",
    r"powershell.*-enc", r"powershell.*-encodedcommand",
    r"certutil.*-decode", r"certutil.*-encode",
]
TRUSTED_DIRECTORY_PREFIXES: list[str] = []


class TrustLevel(IntEnum):
    TRUST_UNVERIFIED = 0
    TRUST_SCRIPT = 1
    TRUST_USER = 2
    TRUST_ADMIN = 3
    TRUST_SYSTEM = 4


@dataclass(frozen=True)
class TrustPolicy:
    """A named trust policy with rules."""
    name: str
    min_trust: TrustLevel = TrustLevel.TRUST_USER
    allow_elevated: bool = False
    allow_network: bool = False
    allow_shell: bool = False
    allow_registry: bool = False
    blocked_executables: frozenset[str] = field(default_factory=frozenset)


@dataclass
class ExecutableTrustMetadata:
    """Per-executable trust metadata."""
    path: str
    trust_level: TrustLevel
    verified: bool = False
    developer: str = ""
    signature: str = ""
    first_seen: float = 0.0
    execution_count: int = 0
    last_executed: float = 0.0
    is_whitelisted: bool = False
    is_developer_mode: bool = False


@dataclass
class SafetyConfig:
    """Configuration for the safety validator."""
    enable_trust_levels: bool = True
    enable_audit_log: bool = True
    developer_mode: bool = False
    allow_unknown: bool = False
    max_audit_entries: int = 10000


class SafetyValidator:
    """
    Enhanced safety validator with trust levels, audit logging, and configurable policies.
    """

    def __init__(self, config: SafetyConfig | None = None):
        self.config = config or SafetyConfig()
        self._blocked_cache: OrderedDict[str, bool] = OrderedDict()
        self._blocked_lock = threading.Lock()
        self._trust_cache: dict[str, ExecutableTrustMetadata] = {}
        self._trust_lock = threading.RLock()
        self._audit_log: list[dict] = []
        self._audit_lock = threading.RLock()
        self._policies: dict[str, TrustPolicy] = {}
        self._active_policy = "default"
        self._compile_patterns()

    def _compile_patterns(self):
        self._dangerous_patterns = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]
        self._blocked_executables_lower = {e.lower() for e in BLOCKED_EXECUTABLES}
        self._dangerous_prefixes = [p.lower() for p in DANGEROUS_PATH_PREFIXES]
        self._blocked_shell_patterns = [re.compile(p, re.IGNORECASE) for p in BLOCKED_SHELL_PATTERNS]
        global TRUSTED_DIRECTORY_PREFIXES
        if not TRUSTED_DIRECTORY_PREFIXES:
            TRUSTED_DIRECTORY_PREFIXES = [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
                os.path.expandvars(r"%APPDATA%"),
                os.path.expandvars(r"%PROGRAMFILES%"),
                os.path.expandvars(r"%PROGRAMFILES(X86)%"),
                os.path.expandvars(r"%USERPROFILE%\Desktop"),
                r"C:\Users\Pavan2808\AppData\Local\Programs\Microsoft VS Code",
            ]

    def register_policy(self, policy: TrustPolicy):
        """Register a named trust policy."""
        with self._trust_lock:
            self._policies[policy.name] = policy

    def set_active_policy(self, name: str):
        """Switch the active trust policy."""
        with self._trust_lock:
            if name in self._policies or name == "default":
                self._active_policy = name

    def get_trust_level(self, path: str) -> TrustLevel:
        """Determine trust level for a path."""
        if not self.config.enable_trust_levels:
            return TrustLevel.TRUST_USER
        with self._trust_lock:
            if path in self._trust_cache:
                return self._trust_cache[path].trust_level
        path_lower = path.lower()
        for prefix in self._dangerous_prefixes:
            if path_lower.startswith(prefix):
                return TrustLevel.TRUST_SYSTEM
        for tdir in TRUSTED_DIRECTORY_PREFIXES:
            if path_lower.startswith(tdir.lower()):
                return TrustLevel.TRUST_USER
        return TrustLevel.TRUST_UNVERIFIED

    def set_executable_trust(self, path: str, level: TrustLevel, metadata: dict | None = None):
        """Set explicit trust metadata for an executable."""
        with self._trust_lock:
            import time as timemod
            existing = self._trust_cache.get(path)
            self._trust_cache[path] = ExecutableTrustMetadata(
                path=path,
                trust_level=level,
                verified=True,
                developer=metadata.get("developer", "") if metadata else "",
                signature=metadata.get("signature", "") if metadata else "",
                first_seen=existing.first_seen if existing else timemod.time(),
                execution_count=existing.execution_count if existing else 0,
                last_executed=existing.last_executed if existing else 0,
                is_whitelisted=metadata.get("is_whitelisted", False) if metadata else False,
                is_developer_mode=metadata.get("is_developer_mode", False) if metadata else False,
            )

    def record_execution(self, path: str):
        """Record that an executable was executed (for audit)."""
        import time as timemod
        with self._trust_lock:
            if path in self._trust_cache:
                meta = self._trust_cache[path]
                new_meta = ExecutableTrustMetadata(
                    path=path, trust_level=meta.trust_level, verified=meta.verified,
                    developer=meta.developer, signature=meta.signature,
                    first_seen=meta.first_seen,
                    execution_count=meta.execution_count + 1,
                    last_executed=timemod.time(),
                    is_whitelisted=meta.is_whitelisted, is_developer_mode=meta.is_developer_mode,
                )
                self._trust_cache[path] = new_meta

    def audit_log_action(self, action: str, path: str, result: str, details: str = ""):
        """Log an action to the audit log."""
        if not self.config.enable_audit_log:
            return
        import time as timemod
        with self._audit_lock:
            entry = {
                "timestamp": timemod.time(),
                "action": action, "path": path, "result": result, "details": details,
                "trust_level": self.get_trust_level(path).name if path else "N/A",
            }
            self._audit_log.append(entry)
            if len(self._audit_log) > self.config.max_audit_entries:
                self._audit_log = self._audit_log[-self.config.max_audit_entries:]

    def get_audit_log(self, limit: int = 100) -> list[dict]:
        with self._audit_lock:
            return list(reversed(self._audit_log))[:limit]

    def validate_path(self, path: str) -> bool:
        if not path:
            return False
        path_lower = path.lower()
        with self._blocked_lock:
            if path_lower in self._blocked_cache:
                self._blocked_cache.move_to_end(path_lower)
                return self._blocked_cache[path_lower]
            for prefix in self._dangerous_prefixes:
                if path_lower.startswith(prefix):
                    self._blocked_cache[path_lower] = False
                    if len(self._blocked_cache) > 500:
                        self._blocked_cache.popitem(last=False)
                    return False
            exe_name = os.path.basename(path_lower)
            if exe_name in self._blocked_executables_lower:
                self._blocked_cache[path_lower] = False
                if len(self._blocked_cache) > 500:
                    self._blocked_cache.popitem(last=False)
                return False
            if os.path.exists(path):
                self._blocked_cache[path_lower] = True
                if len(self._blocked_cache) > 500:
                    self._blocked_cache.popitem(last=False)
                return True
            trust = self.get_trust_level(path)
            if trust >= TrustLevel.TRUST_USER:
                self._blocked_cache[path_lower] = True
                if len(self._blocked_cache) > 500:
                    self._blocked_cache.popitem(last=False)
                return True
            for tdir in TRUSTED_DIRECTORY_PREFIXES:
                if path_lower.startswith(tdir.lower()):
                    self._blocked_cache[path_lower] = True
                    if len(self._blocked_cache) > 500:
                        self._blocked_cache.popitem(last=False)
                    return True
            self._blocked_cache[path_lower] = False
            if len(self._blocked_cache) > 500:
                self._blocked_cache.popitem(last=False)
            return False

    def validate_shell_command(self, command: str) -> bool:
        if not command:
            return False
        cmd_lower = command.lower()
        for pattern in self._blocked_shell_patterns:
            if pattern.search(cmd_lower):
                self.audit_log_action("shell_blocked", command, "blocked", "dangerous pattern")
                return False
        if self.config.developer_mode:
            return True
        blocked = ["del c:\\windows", "rm -rf /", "format c:"]
        if cmd_lower in blocked:
            return False
        return True

    def check_permission(self, path: str, operation: str) -> tuple[bool, str]:
        """Check if an operation is permitted on a path based on active policy."""
        trust = self.get_trust_level(path)
        with self._trust_lock:
            policy = self._policies.get(self._active_policy) or TrustPolicy(name="default")
        if trust < policy.min_trust:
            return False, f"Insufficient trust: {trust.name} < {policy.min_trust.name}"
        if operation == "elevate" and not policy.allow_elevated:
            return False, "Elevated operations not allowed by policy"
        if operation == "network" and not policy.allow_network:
            return False, "Network operations not allowed by policy"
        if operation == "shell" and not policy.allow_shell:
            return False, "Shell operations not allowed by policy"
        return True, "OK"

    def clear_cache(self):
        with self._blocked_lock:
            self._blocked_cache.clear()


_safety_validator: SafetyValidator | None = None


def get_safety_validator() -> SafetyValidator:
    global _safety_validator
    if _safety_validator is None:
        _safety_validator = SafetyValidator()
    return _safety_validator
