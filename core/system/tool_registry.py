from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import logging

from core.agent.work_verifier import (
    VerificationResult,
    verify_browser_workflow_outputs,
    verify_browser_research_outputs,
    verify_college_outputs,
    verify_python_project_outputs,
    verify_python_repair_outputs,
    verify_python_tool_outputs,
    verify_website_outputs,
    verify_workflow_outputs,
)

from .logger import get_logger

# Import Modularized Builders
from core.engines.builders.website import build_website as _build_website
from core.engines.builders.college import build_college_work as _build_college_work
from core.engines.builders.workflow import build_workflow_plan as _build_workflow_plan
from core.engines.builders.browser import build_browser_research as _build_browser_research, build_browser_workflow as _build_browser_workflow
from core.engines.builders.python_tool import build_python_tool as _build_python_tool
from core.engines.builders.python_repair import build_python_project_repair as _build_python_project_repair, build_python_repair as _build_python_repair

logger = get_logger("ToolRegistry")

@dataclass
class ToolResult:
    success: bool
    summary: str
    outputs: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable[..., ToolResult]] = {}

    def register(self, name: str, func: Callable[..., ToolResult]) -> None:
        self._tools[name] = func

    def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            logger.warning(f"Tool '{name}' not found in registry.")
            return ToolResult(False, f"Tool '{name}' is not registered.")
        try:
            logger.info(f"Executing tool: {name} with params: {kwargs}")
            return tool(**kwargs)
        except Exception as exc:
            logger.error(f"Tool '{name}' failed: {exc}", exc_info=True)
            return ToolResult(
                False,
                f"Tool '{name}' failed: {exc}",
                details={"exception": repr(exc)},
            )

# ══════════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY BUILDER
# ══════════════════════════════════════════════════════════════════════════════════

def build_default_registry(workspace_root: str | Path = ".") -> ToolRegistry:
    root = Path(workspace_root).resolve()
    registry = ToolRegistry()

    # Modularized Builders (Imported)
    registry.register("website_builder", lambda **kwargs: _build_website(root, **kwargs))
    registry.register("college_work_builder", lambda **kwargs: _build_college_work(root, **kwargs))
    registry.register("browser_research_builder", lambda **kwargs: _build_browser_research(root, **kwargs))
    registry.register("browser_workflow_builder", lambda **kwargs: _build_browser_workflow(root, **kwargs))
    registry.register("python_tool_builder", lambda **kwargs: _build_python_tool(root, **kwargs))
    registry.register("python_project_repair_builder", lambda **kwargs: _build_python_project_repair(root, **kwargs))
    registry.register("python_repair_builder", lambda **kwargs: _build_python_repair(root, **kwargs))
    registry.register("workflow_plan_builder", lambda **kwargs: _build_workflow_plan(root, **kwargs))

    # Verifiers (Internal helper with Agent verifiers)
    registry.register("browser_workflow_verifier", lambda **kwargs: _verify_outputs(verify_browser_workflow_outputs, **kwargs))
    registry.register("browser_research_verifier", lambda **kwargs: _verify_outputs(verify_browser_research_outputs, **kwargs))
    registry.register("python_project_verifier", lambda **kwargs: _verify_outputs(verify_python_project_outputs, **kwargs))
    registry.register("python_repair_verifier", lambda **kwargs: _verify_outputs(verify_python_repair_outputs, **kwargs))
    registry.register("python_tool_verifier", lambda **kwargs: _verify_outputs(verify_python_tool_outputs, **kwargs))
    registry.register("website_verifier", lambda **kwargs: _verify_outputs(verify_website_outputs, **kwargs))
    registry.register("college_work_verifier", lambda **kwargs: _verify_outputs(verify_college_outputs, **kwargs))
    registry.register("workflow_plan_verifier", lambda **kwargs: _verify_outputs(verify_workflow_outputs, **kwargs))

    # New Autonomous Core Tools
    registry.register("read_file", lambda **kwargs: _tool_read_file(root, **kwargs))
    registry.register("write_file", lambda **kwargs: _tool_write_file(root, **kwargs))
    registry.register("list_dir", lambda **kwargs: _tool_list_dir(root, **kwargs))

    # Secretary Tool (Phase 5)
    from skills.secretary_skill import run as secretary_run
    registry.register("secretary_tool", lambda **kwargs: secretary_run(kwargs.get("prompt", ""), {}))

    return registry

# ══════════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════════

def _verify_outputs(verify_func, outputs: list[str], **_kwargs) -> ToolResult:
    verification = verify_func(outputs)
    return ToolResult(
        success=verification.success,
        summary=verification.summary,
        outputs=list(outputs),
        verification=verification.to_dict(),
    )

def _tool_read_file(root: Path, path: str, **kwargs) -> ToolResult:
    try:
        resolved = (root / path).resolve()
        if root not in resolved.parents and resolved != root:
            return ToolResult(False, "Security Error: Access denied to path outside workspace.")
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return ToolResult(True, f"Read file {path}", outputs=[content])
    except Exception as e:
        return ToolResult(False, f"Read failed: {e}")

def _tool_write_file(root: Path, path: str, content: str, **kwargs) -> ToolResult:
    try:
        resolved = (root / path).resolve()
        if root not in resolved.parents and resolved != root:
            return ToolResult(False, "Security Error: Access denied to path outside workspace.")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return ToolResult(True, f"Wrote to {path}", outputs=[str(resolved)])
    except Exception as e:
        return ToolResult(False, f"Write failed: {e}")

def _tool_list_dir(root: Path, path: str, **kwargs) -> ToolResult:
    try:
        resolved = (root / path).resolve()
        if root not in resolved.parents and resolved != root:
            return ToolResult(False, "Security Error: Access denied to path outside workspace.")
        files = [str(p.relative_to(root)) for p in resolved.iterdir()]
        return ToolResult(True, f"Listed {path}", outputs=["\n".join(files)])
    except Exception as e:
        return ToolResult(False, f"List failed: {e}")
