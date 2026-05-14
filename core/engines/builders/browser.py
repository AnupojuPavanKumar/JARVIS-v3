from __future__ import annotations
import textwrap
from pathlib import Path
from urllib.parse import urlparse
from .common import slugify, extract_topic, write_text, create_run_dir

def build_browser_research(
    root: Path,
    prompt: str,
    attempt: int = 1,
    verification_feedback: list[str] | None = None,
):
    from core.system.tool_registry import ToolResult
    from core.api.browser_automation import BrowserAutomation
    url = BrowserAutomation.extract_first_url(prompt)
    if url:
        title = urlparse(url).netloc or "Browser Research"
    else:
        title = extract_topic(prompt, "Browser Research")
        if title == "Browser Research":
            cleaned = prompt
            for prefix in ("research ", "analyze ", "summarize ", "inspect ", "browse "):
                if cleaned.lower().startswith(prefix):
                    cleaned = cleaned[len(prefix):]
                    break
            title = cleaned.strip(" .!?").title() or "Browser Research"
    slug = slugify(title)
    project_dir = create_run_dir(root / "generated" / "browser", slug)
    browser = BrowserAutomation(timeout=20)
    feedback = verification_feedback or []

    if url:
        snapshot = browser.capture_page(url)
        body = textwrap.dedent(
            f"""\
            # Browser Research: {title}

            ## Source

            - URL: {snapshot.final_url}
            - Engine: {snapshot.engine}
            - Title: {snapshot.title}

            ## Snapshot

            {snapshot.text_excerpt or "No page text was captured."}

            ## Links

            """
        )
        for link in snapshot.links[:6]:
            body += f"- [{link['text'] or link['href']}]({link['href']})\n"
    else:
        research = browser.wikipedia_research(title)
        body = textwrap.dedent(
            f"""\
            # Browser Research: {title}

            ## Source

            Engine: {research["engine"]}

            ## Topic Summary

            """
        )
        for page in research["pages"]:
            body += textwrap.dedent(
                f"""\
                ### {page['title']}

                {page['summary']}

                Source: {page['url']}

                """
            )

    if attempt > 1 and feedback:
        body += "\n## Retry Notes\n\n- " + "\n- ".join(feedback[:3]) + "\n"

    checklist = textwrap.dedent(
        """\
        # Browser Research Checklist

        1. Review the captured summary.
        2. Open the cited sources if you need deeper detail.
        3. Convert the notes into your final deliverable.
        """
    )

    outputs = [
        write_text(project_dir / "browser-research.md", body),
        write_text(project_dir / "research-checklist.md", checklist),
    ]

    return ToolResult(
        success=True,
        summary=f"Prepared browser research notes for {title}.",
        outputs=outputs,
        details={"project_dir": str(project_dir), "attempt": attempt},
    )

def build_browser_workflow(
    root: Path,
    prompt: str,
    attempt: int = 1,
    verification_feedback: list[str] | None = None,
):
    from core.system.tool_registry import ToolResult
    from core.api.browser_automation import BrowserAutomation
    browser = BrowserAutomation(timeout=20)
    url, actions = browser.parse_workflow_instructions(prompt)
    if not url:
        return ToolResult(False, "I could not find a URL to run that browser workflow.")

    title = urlparse(url).netloc or "browser-workflow"
    slug = slugify(title)
    project_dir = create_run_dir(root / "generated" / "browser-workflows", slug)
    feedback = verification_feedback or []

    trace = browser.run_workflow(url, actions)
    steps_md = []
    for index, step in enumerate(trace.steps, start=1):
        steps_md.append(f"## Step {index}: {step.get('action', 'action').title()}")
        steps_md.append(f"Target: {step.get('target', '')}")
        if step.get("value"):
            steps_md.append(f"Value: {step.get('value', '')}")
        if step.get("error"):
            steps_md.append(f"Error: {step['error']}")
        snapshot = step.get("snapshot")
        if snapshot:
            steps_md.append(f"Title: {snapshot.get('title', '')}")
            steps_md.append(f"URL: {snapshot.get('final_url', '')}")
            steps_md.append("")
            steps_md.append(snapshot.get("text_excerpt", "") or "No page text captured.")
        steps_md.append("")

    if attempt > 1 and feedback:
        steps_md.append("## Retry Notes")
        steps_md.extend([f"- {item}" for item in feedback[:3]])
        steps_md.append("")

    trace_md = "\n".join(
        [
            f"# Browser Workflow: {title}",
            "",
            f"Start URL: {url}",
            f"Engine: {trace.engine}",
            "",
            *steps_md,
        ]
    )
    checklist_md = textwrap.dedent(
        """\
        # Browser Workflow Checklist

        1. Review each step snapshot.
        2. Confirm the workflow reached the page you expected.
        3. Refine the prompt with clearer follow/click instructions if needed.
        """
    )

    outputs = [
        write_text(project_dir / "browser-workflow.md", trace_md),
        write_text(project_dir / "workflow-checklist.md", checklist_md),
    ]
    return ToolResult(
        success=True,
        summary=f"Ran a browser workflow trace for {title}.",
        outputs=outputs,
        details={
            "project_dir": str(project_dir),
            "attempt": attempt,
            "engine": trace.engine,
            "actions": [action.to_dict() for action in actions],
        },
    )
