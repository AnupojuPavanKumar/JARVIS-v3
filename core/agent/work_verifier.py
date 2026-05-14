from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VerificationResult:
    success: bool = True
    summary: str = "Verification passed."
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "summary": self.summary,
            "issues": list(self.issues),
        }


def _verify_named(name: str, outputs: list[str]) -> VerificationResult:
    if not outputs:
        return VerificationResult(False, f"{name} produced no outputs.", ["missing outputs"])
    return VerificationResult(True, f"{name} outputs look present.")


def verify_browser_workflow_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Browser workflow", outputs)


def verify_browser_research_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Browser research", outputs)


def verify_college_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("College work", outputs)


def verify_python_project_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Python project repair", outputs)


def verify_python_repair_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Python repair", outputs)


def verify_python_tool_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Python tool", outputs)


def verify_website_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Website", outputs)


def verify_workflow_outputs(outputs: list[str]) -> VerificationResult:
    return _verify_named("Workflow", outputs)
