from __future__ import annotations


class GhostDebugger:
    """Heuristic diagnostics kept for legacy tests and agent auto-diagnosis."""

    def diagnose(self, traceback_text: str) -> str:
        lowered = traceback_text.lower()
        if "modulenotfounderror" in lowered:
            return "Missing import or deleted compatibility module."
        if "syntaxerror" in lowered:
            return "Syntax error detected; run py_compile on the target file."
        return "No specific diagnosis available."

    def _heuristic_analyze(self, context: str) -> dict:
        lowered = context.lower()
        issues = []
        patch = {}
        if "px" in lowered:
            issues.append("fixed pixel sizing")
            patch["sizing"] = "Prefer responsive max-width/minmax/clamp patterns."
        if "overflow: hidden" in lowered:
            issues.append("overflow clipping")
            patch["overflow"] = "Avoid hiding overflowing content unless intentional."
        if "!important" in lowered:
            issues.append("overuse of !important")
            patch["specificity"] = "Reduce selector conflicts instead of forcing styles."
        return {
            "detected_issues": ", ".join(issues) if issues else "No obvious issues detected.",
            "visual_patch": patch,
        }
