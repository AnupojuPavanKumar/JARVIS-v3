from __future__ import annotations
import textwrap
from pathlib import Path
from .common import slugify, extract_topic, write_text, create_run_dir

def build_workflow_plan(
    root: Path,
    prompt: str,
    attempt: int = 1,
    verification_feedback: list[str] | None = None,
):
    from core.system.tool_registry import ToolResult
    title = extract_topic(prompt, "Workflow Plan")
    slug = slugify(title)
    project_dir = create_run_dir(root / "generated" / "workflows", slug)
    feedback = verification_feedback or []
    repair_block = ""
    if attempt > 1 and feedback:
        repair_block = "\n## Retry Notes\n\n- " + "\n- ".join(feedback[:3]) + "\n"

    plan_md = textwrap.dedent(
        f"""\
        # {title}

        ## Objective

        {prompt.strip()}

        ## Workflow Plan

        1. Clarify the expected output and deadline.
        2. Gather the files, links, and inputs the task needs.
        3. Execute the work in small checkpoints instead of one long run.
        4. Verify the output before marking the job complete.

        ## Automation Candidates

        - File generation and folder setup
        - Repetitive formatting steps
        - Research summaries and rough drafts
        - Progress tracking and review notes

        ## Verification Checklist

        - Does the output match the requested format?
        - Are all required files present?
        - Is there a human review step before final submission?
        {repair_block}
        """
    )

    outputs = [write_text(project_dir / "workflow-plan.md", plan_md)]
    return ToolResult(
        success=True,
        summary=f"Prepared an automation-ready workflow plan for {title}.",
        outputs=outputs,
        details={"project_dir": str(project_dir), "attempt": attempt},
    )
