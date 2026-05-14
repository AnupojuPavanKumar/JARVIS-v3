import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

log = logging.getLogger("ExecutionGovernance")

# Sandbox Profiles
class SandboxProfile(BaseModel):
    name: str
    allowed_tools: set[str]
    max_retries: int
    timeout_s: int
    allow_destructive: bool

PROFILES = {
    "strict": SandboxProfile(
        name="strict",
        allowed_tools={"filesystem_read", "filesystem_list", "browser_read", "system_stats"},
        max_retries=1,
        timeout_s=15,
        allow_destructive=False
    ),
    "developer": SandboxProfile(
        name="developer",
        allowed_tools={"filesystem_read", "filesystem_write", "filesystem_append", "filesystem_list", "filesystem_search", "terminal_run", "browser_read", "system_stats", "system_processes"},
        max_retries=3,
        timeout_s=60,
        allow_destructive=False
    ),
    "admin": SandboxProfile(
        name="admin",
        allowed_tools={"filesystem_read", "filesystem_write", "filesystem_append", "filesystem_list", "filesystem_search", "filesystem_delete", "terminal_run", "browser_read", "system_stats", "system_processes"},
        max_retries=5,
        timeout_s=120,
        allow_destructive=True
    )
}

# Command Allowlists & Denylists
ALLOWED_COMMANDS = re.compile(r"^(ls|dir|cat|type|echo|ping|whoami|python|pip|git status|git log)\b", re.IGNORECASE)
DENIED_COMMANDS = re.compile(
    r"\b(rm\s+-rf|del\s+/[sq]|format\s+[a-z]:?|rmdir\s+/[sq]|"
    r"shutdown|reboot|taskkill|kill\s+-9|dd\s+if=|mkfs|fdisk|"
    r"DROP\s+DATABASE|TRUNCATE\s+TABLE|DELETE\s+FROM\b)\b",
    re.IGNORECASE,
)

PROTECTED_PATHS = {
    "c:/windows", "c:\\windows",
    "c:/program files", "c:\\program files",
    "c:/system32", "c:\\system32",
    "/etc", "/bin", "/sbin", "/usr/bin"
}

class ActionProposal(BaseModel):
    tool: str
    parameters: Dict[str, Any]
    confidence: float
    identity: str
    profile: str = "developer"
    
class ValidationResult(BaseModel):
    allowed: bool
    reason: str
    profile_applied: SandboxProfile

class ExecutionGovernanceLayer:
    """
    Implements Phase 2: Execution Governance.
    Stages: Proposal -> Validation -> Execution -> Observation -> Recovery
    """
    def __init__(self):
        self.execution_budget = {"daily_commands": 1000, "used": 0}
        self._recovery_snapshots = {}

    def validate_proposal(self, proposal: ActionProposal) -> ValidationResult:
        """STAGE 2: VALIDATION STAGE"""
        profile = PROFILES.get(proposal.profile, PROFILES["strict"])
        
        # 1. Budget Check
        if self.execution_budget["used"] >= self.execution_budget["daily_commands"]:
            return ValidationResult(allowed=False, reason="Execution budget exceeded.", profile_applied=profile)
            
        # 2. Tool Allowlist Check
        if proposal.tool not in profile.allowed_tools:
            return ValidationResult(allowed=False, reason=f"Tool {proposal.tool} not allowed in profile {profile.name}", profile_applied=profile)
            
        param_str = str(proposal.parameters).lower()

        # 3. Path Legitimacy Check
        for protected in PROTECTED_PATHS:
            if protected in param_str:
                return ValidationResult(allowed=False, reason=f"Protected path target: {protected}", profile_applied=profile)

        # 4. Command Safety Check (Terminal)
        if proposal.tool == "terminal_run":
            cmd = str(proposal.parameters.get("command", ""))
            if DENIED_COMMANDS.search(cmd):
                if not profile.allow_destructive:
                    return ValidationResult(allowed=False, reason="Destructive command blocked by profile.", profile_applied=profile)
                if proposal.confidence < 0.95:
                    return ValidationResult(allowed=False, reason="Destructive command requires confidence >= 0.95", profile_applied=profile)

        # 5. Dependency / Syntax checks could be added here
        
        return ValidationResult(allowed=True, reason="", profile_applied=profile)

    def create_recovery_snapshot(self, proposal: ActionProposal) -> Optional[str]:
        """STAGE 5 PREP: Create snapshot before critical operation"""
        if proposal.tool in ["filesystem_write", "filesystem_delete"]:
            path = proposal.parameters.get("path")
            if path and os.path.exists(path) and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    snapshot_id = f"snap_{int(time.time()*1000)}"
                    self._recovery_snapshots[snapshot_id] = {"path": path, "content": content}
                    log.info(f"[Governance] Created snapshot {snapshot_id} for {path}")
                    return snapshot_id
                except Exception as e:
                    log.warning(f"[Governance] Failed to create snapshot for {path}: {e}")
        return None

    def rollback_snapshot(self, snapshot_id: str) -> bool:
        """STAGE 5: RECOVERY STAGE"""
        if snapshot_id in self._recovery_snapshots:
            snap = self._recovery_snapshots[snapshot_id]
            try:
                with open(snap["path"], "w", encoding="utf-8") as f:
                    f.write(snap["content"])
                log.info(f"[Governance] Rolled back {snap['path']} via {snapshot_id}")
                del self._recovery_snapshots[snapshot_id]
                return True
            except Exception as e:
                log.error(f"[Governance] Rollback failed: {e}")
        return False
        
    def observe_execution(self, tool: str, success: bool, output: str, duration_ms: int):
        """STAGE 4: OBSERVATION STAGE"""
        self.execution_budget["used"] += 1
        # In a full system, this would emit telemetry events to the metrics collector.
        log.info(f"[Governance] Observation: {tool} success={success} duration={duration_ms}ms")

# Singleton
_governance_instance: Optional[ExecutionGovernanceLayer] = None

def get_governance() -> ExecutionGovernanceLayer:
    global _governance_instance
    if _governance_instance is None:
        _governance_instance = ExecutionGovernanceLayer()
    return _governance_instance
