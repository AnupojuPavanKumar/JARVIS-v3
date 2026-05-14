from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowStep:
    tool: str
    description: str
    params: dict[str, Any]
    verify_tool: str | None = None
    max_retries: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "description": self.description,
            "params": self.params,
            "verify_tool": self.verify_tool,
            "max_retries": self.max_retries,
        }


@dataclass
class WorkflowPlan:
    goal: str
    title: str
    category: str
    steps: list[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "title": self.title,
            "category": self.category,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class WorkflowRun:
    plan: WorkflowPlan
    success: bool
    summary: str
    outputs: list[str] = field(default_factory=list)
    step_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "success": self.success,
            "summary": self.summary,
            "outputs": self.outputs,
            "step_results": self.step_results,
        }


class WorkflowEngine:
    def __init__(self, registry):
        self.registry = registry

    def run(self, plan: WorkflowPlan) -> WorkflowRun:
        outputs: list[str] = []
        step_results: list[dict[str, Any]] = []

        for step in plan.steps:
            attempt_records = []
            result = None
            verification_feedback: list[str] = []

            for attempt in range(1, max(step.max_retries, 1) + 1):
                params = dict(step.params)
                params["attempt"] = attempt
                if verification_feedback:
                    params["verification_feedback"] = verification_feedback

                result = self.registry.execute(step.tool, **params)

                if result.success and step.verify_tool:
                    verification_result = self.registry.execute(
                        step.verify_tool,
                        outputs=result.outputs,
                    )
                    result.verification = verification_result.verification
                    if not verification_result.success:
                        verification_feedback = verification_result.verification.get("issues", [])
                        result.success = False
                        result.summary = verification_result.summary

                attempt_records.append(
                    {
                        "attempt": attempt,
                        "tool": step.tool,
                        "description": step.description,
                        "success": result.success,
                        "summary": result.summary,
                        "outputs": result.outputs,
                        "verification": result.verification,
                    }
                )

                if result.success:
                    break

            if result is None:
                result = self.registry.execute(step.tool, **step.params)

            step_record = {
                "tool": step.tool,
                "description": step.description,
                "success": result.success,
                "summary": result.summary,
                "outputs": result.outputs,
                "attempts": attempt_records,
            }
            step_results.append(step_record)
            outputs.extend(result.outputs)

            if not result.success:
                return WorkflowRun(
                    plan=plan,
                    success=False,
                    summary=result.summary,
                    outputs=outputs,
                    step_results=step_results,
                )

        summary = step_results[-1]["summary"] if step_results else "Workflow completed."
        return WorkflowRun(
            plan=plan,
            success=True,
            summary=summary,
            outputs=outputs,
            step_results=step_results,
        )
