from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanStep:
    tool: str
    prompt: str
    verify_tool: str | None = None

    def to_dict(self) -> dict:
        return {"tool": self.tool, "prompt": self.prompt, "verify_tool": self.verify_tool}


@dataclass
class TaskPlan:
    objective: str
    category: str
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "category": self.category,
            "steps": [step.to_dict() for step in self.steps],
        }


class TaskOrchestrator:
    def __init__(self, identity: str = "owner"):
        self.identity = identity

    def is_status_query(self, text: str) -> bool:
        lowered = text.lower()
        return "status" in lowered or "recent autonomous" in lowered or "jobs" in lowered

    def create_plan(self, objective: str) -> TaskPlan:
        lowered = objective.lower()
        if "browse" in lowered and "http" in lowered and ("follow" in lowered or "click" in lowered):
            return TaskPlan(objective, "browser_workflow", [PlanStep("browser_workflow_builder", objective, "browser_workflow_verifier")])
        if "research" in lowered or "http" in lowered or "browse" in lowered:
            return TaskPlan(objective, "browser_research", [PlanStep("browser_research_builder", objective, "browser_research_verifier")])
        if "repair current project" in lowered or "repair project" in lowered:
            return TaskPlan(objective, "python_project_repair", [PlanStep("python_project_repair_builder", objective, "python_project_verifier")])
        if "repair" in lowered and ".py" in lowered:
            return TaskPlan(objective, "python_repair", [PlanStep("python_repair_builder", objective, "python_repair_verifier")])
        if "python" in lowered or "script" in lowered or "automation tool" in lowered:
            return TaskPlan(objective, "python_tool", [PlanStep("python_tool_builder", objective, "python_tool_verifier")])
        if "workflow" in lowered or "automation" in lowered:
            return TaskPlan(objective, "workflow", [PlanStep("workflow_plan_builder", objective, "workflow_plan_verifier")])
        if "college" in lowered or "report" in lowered or "assignment" in lowered:
            return TaskPlan(objective, "college", [PlanStep("college_work_builder", objective, "college_work_verifier")])
        return TaskPlan(objective, "website", [PlanStep("website_builder", objective, "website_verifier")])
