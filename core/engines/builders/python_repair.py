from __future__ import annotations
import ast
import difflib
import re
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from .common import slugify, write_text, create_run_dir, extract_workspace_path

def build_python_project_repair(
    root: Path,
    prompt: str,
    attempt: int = 1,
    verification_feedback: list[str] | None = None,
):
    from core.system.tool_registry import ToolResult
    from core.agent.runtime_executor import RuntimeExecutor
    from core.agent.project_runtime import run_project_runtime_smoke
    project_dir = extract_workspace_path(prompt, root, allow_files=False, allow_dirs=True)
    if project_dir is None:
        return ToolResult(False, "I could not find a project folder to repair.")
    if not project_dir.exists():
        return ToolResult(False, f"Target project folder was not found: {project_dir}")

    python_files = _collect_python_files(project_dir)
    if not python_files:
        return ToolResult(False, f"I could not find any Python files inside {project_dir}.")

    executor = RuntimeExecutor(timeout=20)
    compile_before = executor.py_compile(python_files, cwd=project_dir)
    current_compile = compile_before
    repair_events: list[dict[str, Any]] = []
    runtime_events: list[dict[str, Any]] = []
    updated_files: list[str] = []

    for _ in range(min(len(python_files), 12)):
        if current_compile.success:
            break

        failing_path = _extract_compiler_target_path(current_compile.stderr or current_compile.stdout, project_dir)
        if failing_path is None or failing_path not in python_files:
            break

        repair_attempt = _attempt_verified_python_repair(failing_path, executor)
        repair_events.append(
            {
                "file": str(failing_path),
                "target_updated": repair_attempt["target_updated"],
                "fixes_applied": repair_attempt["fixes_applied"],
                "compile_before": repair_attempt["compile_before"].to_dict(),
                "compile_after": repair_attempt["compile_after"].to_dict(),
            }
        )

        if repair_attempt["target_updated"]:
            updated_files.append(str(failing_path))
            current_compile = executor.py_compile(python_files, cwd=project_dir)
            continue
        break

    runtime_smoke = run_project_runtime_smoke(project_dir, executor)
    if current_compile.success and runtime_smoke["attempted"] and not runtime_smoke["success"]:
        for _ in range(3):
            runtime_repair = _attempt_project_runtime_repair(project_dir, runtime_smoke, executor)
            runtime_events.append(runtime_repair)
            if not runtime_repair["target_updated"]:
                break

            updated_file = runtime_repair.get("file")
            if updated_file:
                updated_files.append(updated_file)

            current_compile = executor.py_compile(python_files, cwd=project_dir)
            if not current_compile.success:
                break

            runtime_smoke = run_project_runtime_smoke(project_dir, executor)
            if runtime_smoke["success"]:
                break

    report_dir = create_run_dir(root / "generated" / "project-repairs", slugify(project_dir.name))
    updated_files_block = "- " + "\n- ".join(updated_files) if updated_files else "No files were updated."
    repair_events_block = _format_project_repair_events(repair_events)
    runtime_events_block = _format_runtime_repair_events(runtime_events)
    runtime_smoke_block = _format_runtime_smoke(runtime_smoke)
    report_md = textwrap.dedent(
        f"""\
        # Python Project Repair Report

        ## Project

        {project_dir}

        ## Attempt

        {attempt}

        ## Python Files Scanned

        {len(python_files)}

        ## Initial Compile Result

        Return code: {compile_before.returncode}

        ```
        {compile_before.stderr or compile_before.stdout or 'No compiler output.'}
        ```

        ## Files Updated

        {updated_files_block}

        ## Repair Events

        {repair_events_block}

        ## Runtime Repair Events

        {runtime_events_block}

        ## Final Compile Result

        Return code: {current_compile.returncode}

        ```
        {current_compile.stderr or current_compile.stdout or 'No compiler output.'}
        ```

        ## Runtime Smoke

        {runtime_smoke_block}
        """
    )

    outputs = [
        str(project_dir),
        write_text(report_dir / "project-repair-report.md", report_md),
    ]

    if not current_compile.success:
        return ToolResult(
            success=False,
            summary=f"I could not fully repair the Python project at {project_dir.name}.",
            outputs=outputs,
            details={
                "attempt": attempt,
                "project_dir": str(project_dir),
                "python_files": [str(path) for path in python_files],
                "compile_before": compile_before.to_dict(),
                "compile_after": current_compile.to_dict(),
                "repair_events": repair_events,
                "runtime_events": runtime_events,
                "runtime_smoke": runtime_smoke,
            },
        )

    runtime_summary = ""
    if runtime_smoke["attempted"]:
        runtime_summary = " Runtime smoke passed." if runtime_smoke["success"] else " Runtime smoke still failed."

    return ToolResult(
        success=current_compile.success and (runtime_smoke["success"] or not runtime_smoke["attempted"]),
        summary=f"Repaired Python project {project_dir.name}.{runtime_summary}",
        outputs=outputs,
        details={
            "attempt": attempt,
            "project_dir": str(project_dir),
            "python_files": [str(path) for path in python_files],
            "compile_before": compile_before.to_dict(),
            "compile_after": current_compile.to_dict(),
            "repair_events": repair_events,
            "runtime_events": runtime_events,
            "runtime_smoke": runtime_smoke,
        },
    )

def build_python_repair(
    root: Path,
    prompt: str,
    attempt: int = 1,
    verification_feedback: list[str] | None = None,
):
    from core.system.tool_registry import ToolResult
    from core.agent.runtime_executor import RuntimeExecutor
    target_path = _extract_python_path(prompt)
    if target_path is None:
        return ToolResult(False, "I could not find a Python file path to repair.")

    resolved = target_path.resolve()
    workspace_root = root.resolve()
    if workspace_root not in resolved.parents and resolved != workspace_root:
        return ToolResult(False, "I can only repair Python files inside the current workspace.")
    if not resolved.exists():
        return ToolResult(False, f"Target Python file was not found: {resolved}")

    executor = RuntimeExecutor(timeout=20)
    repair_attempt = _attempt_verified_python_repair(resolved, executor)
    compile_before = repair_attempt["compile_before"]
    compile_after = repair_attempt["compile_after"]
    fixes_applied = repair_attempt["fixes_applied"]
    target_updated = repair_attempt["target_updated"]

    report_dir = create_run_dir(root / "generated" / "python-repairs", slugify(resolved.stem))
    fixes_text = "- " + "\n- ".join(fixes_applied) if fixes_applied else "No automatic fixes were applied."
    report_md = textwrap.dedent(
        f"""\
        # Python Repair Report

        ## Target

        {resolved}

        ## Attempt

        {attempt}

        ## Initial Compile Result

        Return code: {compile_before.returncode}

        ```
        {compile_before.stderr or compile_before.stdout or 'No compiler output.'}
        ```

        ## Fixes Applied

        {fixes_text}

        ## Target File Status

        {"Updated in place after the repaired version compiled successfully." if target_updated else "Original file preserved because no verified repair was available."}

        ## Final Compile Result

        Return code: {compile_after.returncode}

        ```
        {compile_after.stderr or compile_after.stdout or 'No compiler output.'}
        ```
        """
    )

    outputs = [
        str(resolved),
        write_text(report_dir / "repair-report.md", report_md),
    ]

    if not compile_after.success:
        return ToolResult(
            success=False,
            summary=f"I could not fully repair {resolved.name}.",
            outputs=outputs,
            details={
                "attempt": attempt,
                "compile_before": compile_before.to_dict(),
                "compile_after": compile_after.to_dict(),
                "fixes_applied": fixes_applied,
            },
        )

    return ToolResult(
        success=True,
        summary=f"Repaired Python file {resolved.name}.",
        outputs=outputs,
        details={
            "attempt": attempt,
            "compile_before": compile_before.to_dict(),
            "compile_after": compile_after.to_dict(),
            "fixes_applied": fixes_applied,
        },
    )

def _collect_python_files(project_dir: Path) -> list[Path]:
    excluded_parts = {"venv", "venv311", ".venv", "__pycache__", "generated", "site-packages"}
    files: list[Path] = []
    for path in sorted(project_dir.rglob("*.py")):
        relative_parts = set(path.relative_to(project_dir).parts)
        if relative_parts & excluded_parts:
            continue
        files.append(path)
    return files


def _extract_compiler_target_path(compiler_output: str, project_dir: Path) -> Path | None:
    from contextlib import suppress
    match = re.search(r'File "([^"]+)"', compiler_output)
    if not match:
        return None
    with suppress(Exception):
        candidate = Path(match.group(1)).resolve()
        if project_dir == candidate or project_dir in candidate.parents:
            return candidate
    return None


def _attempt_verified_python_repair(target_path: Path, executor: Any) -> dict[str, Any]:
    original_content = target_path.read_text(encoding="utf-8", errors="replace")
    compile_before = executor.py_compile([target_path], cwd=target_path.parent)
    compile_after = compile_before
    target_updated = False
    fixes_applied: list[str] = []

    if not compile_before.success:
        repaired_content, fixes_applied = _repair_python_source(
            original_content,
            compile_before.stderr or compile_before.stdout,
            executor=executor,
            filename=target_path.name,
        )
        if repaired_content != original_content:
            with TemporaryDirectory(prefix="jarvis-repair-") as temp_dir:
                candidate_path = Path(temp_dir) / target_path.name
                candidate_path.write_text(repaired_content, encoding="utf-8")
                compile_after = executor.py_compile([candidate_path], cwd=temp_dir)

            if compile_after.success:
                target_path.write_text(repaired_content, encoding="utf-8")
                target_updated = True
                compile_after = executor.py_compile([target_path], cwd=target_path.parent)

    return {
        "compile_before": compile_before,
        "compile_after": compile_after,
        "fixes_applied": fixes_applied,
        "target_updated": target_updated,
    }


def _attempt_project_runtime_repair(
    project_dir: Path,
    runtime_smoke: dict[str, Any],
    executor: Any,
) -> dict[str, Any]:
    from core.agent.project_runtime import run_project_runtime_smoke
    runtime_result = runtime_smoke.get("result", {})
    error_output = runtime_result.get("stderr") or runtime_result.get("stdout") or ""
    target_path = _extract_compiler_target_path(error_output, project_dir)
    if target_path is None or not target_path.exists():
        target_path = Path(runtime_smoke.get("entrypoint", "")) if runtime_smoke.get("entrypoint") else None
    if target_path is None or not target_path.exists():
        return {
            "target_updated": False,
            "reason": "Could not identify the file responsible for the runtime failure.",
            "error_output": error_output,
        }

    source = target_path.read_text(encoding="utf-8", errors="replace")
    updated_source = source
    fixes_applied: list[str] = []

    name_error = re.search(r"NameError: name '([^']+)' is not defined", error_output)
    if name_error:
        missing_name = name_error.group(1)
        import_stmt = _suggest_import_for_name(missing_name)
        if import_stmt:
            updated_source = _ensure_import_statement(updated_source, import_stmt)
            if updated_source != source:
                fixes_applied.append(f"Added missing import for '{missing_name}'.")

    import_error = re.search(r"ImportError: cannot import name '([^']+)' from '([^']+)'", error_output)
    if import_error and updated_source == source:
        missing_symbol = import_error.group(1)
        module_name = import_error.group(2)
        candidate = _find_closest_module_symbol(project_dir, module_name, missing_symbol)
        if candidate:
            replaced_source = re.sub(
                rf"\bfrom\s+{re.escape(module_name)}\s+import\s+{re.escape(missing_symbol)}\b",
                f"from {module_name} import {candidate}",
                updated_source,
            )
            if replaced_source != source:
                updated_source = re.sub(rf"\b{re.escape(missing_symbol)}\b", candidate, replaced_source)
                fixes_applied.append(
                    f"Adjusted import and symbol references from '{missing_symbol}' to '{candidate}' for module '{module_name}'."
                )

    attribute_error = re.search(r"AttributeError: module '([^']+)' has no attribute '([^']+)'", error_output)
    if attribute_error and updated_source == source:
        module_name = attribute_error.group(1)
        missing_attr = attribute_error.group(2)
        candidate = _find_closest_module_symbol(project_dir, module_name, missing_attr)
        if candidate:
            updated_source = updated_source.replace(f".{missing_attr}", f".{candidate}")
            if updated_source != source:
                fixes_applied.append(
                    f"Adjusted attribute access from '{missing_attr}' to '{candidate}' for module '{module_name}'."
                )

    if updated_source == source:
        return {
            "file": str(target_path),
            "target_updated": False,
            "reason": "No safe runtime fix was available for the current error.",
            "error_output": error_output,
        }

    with TemporaryDirectory(prefix="jarvis-runtime-repair-") as temp_dir:
        candidate_path = Path(temp_dir) / target_path.name
        candidate_path.write_text(updated_source, encoding="utf-8")
        compile_result = executor.py_compile([candidate_path], cwd=temp_dir)

    if not compile_result.success:
        return {
            "file": str(target_path),
            "target_updated": False,
            "reason": "The candidate runtime fix did not compile cleanly.",
            "fixes_applied": fixes_applied,
            "compile_after": compile_result.to_dict(),
            "error_output": error_output,
        }

    original_source = target_path.read_text(encoding="utf-8", errors="replace")
    target_path.write_text(updated_source, encoding="utf-8")
    rerun = run_project_runtime_smoke(project_dir, executor)
    if rerun["attempted"] and not rerun["success"]:
        new_error_output = rerun.get("result", {}).get("stderr") or rerun.get("result", {}).get("stdout") or ""
        if new_error_output.strip() == error_output.strip():
            target_path.write_text(original_source, encoding="utf-8")
            return {
                "file": str(target_path),
                "target_updated": False,
                "reason": "The runtime issue persisted after applying the candidate fix.",
                "fixes_applied": fixes_applied,
                "runtime_after": rerun,
                "error_output": error_output,
            }

        return {
            "file": str(target_path),
            "target_updated": True,
            "reason": "The candidate fix advanced runtime execution, but another runtime issue remains.",
            "fixes_applied": fixes_applied,
            "runtime_after": rerun,
            "error_output": error_output,
        }

    return {
        "file": str(target_path),
        "target_updated": True,
        "fixes_applied": fixes_applied,
        "runtime_after": rerun,
        "error_output": error_output,
    }


def _suggest_import_for_name(name: str) -> str | None:
    import_map = {
        "Path": "from pathlib import Path",
        "json": "import json",
        "re": "import re",
        "os": "import os",
        "sys": "import sys",
        "argparse": "import argparse",
        "datetime": "from datetime import datetime",
        "timedelta": "from datetime import timedelta",
        "dataclass": "from dataclasses import dataclass",
        "field": "from dataclasses import field",
        "Any": "from typing import Any",
        "Optional": "from typing import Optional",
        "Flask": "from flask import Flask",
        "Blueprint": "from flask import Blueprint",
        "request": "from flask import request",
        "jsonify": "from flask import jsonify",
        "redirect": "from flask import redirect",
        "url_for": "from flask import url_for",
        "render_template": "from flask import render_template",
        "FastAPI": "from fastapi import FastAPI",
        "APIRouter": "from fastapi import APIRouter",
        "Depends": "from fastapi import Depends",
        "HTTPException": "from fastapi import HTTPException",
        "Request": "from fastapi import Request",
        "BaseModel": "from pydantic import BaseModel",
        "HttpResponse": "from django.http import HttpResponse",
        "JsonResponse": "from django.http import JsonResponse",
        "render": "from django.shortcuts import render",
        "path": "from django.urls import path",
    }
    return import_map.get(name)


def _ensure_import_statement(source: str, import_statement: str) -> str:
    if import_statement in source:
        return source

    lines = source.splitlines()
    insert_at = 0
    if lines and lines[0].startswith('"""'):
        for index in range(1, len(lines)):
            if lines[index].startswith('"""'):
                insert_at = index + 1
                break
    while insert_at < len(lines) and (lines[insert_at].startswith("from __future__ import") or not lines[insert_at].strip()):
        insert_at += 1
    lines.insert(insert_at, import_statement)
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def _find_closest_module_symbol(project_dir: Path, module_name: str, symbol_name: str) -> str | None:
    module_path = _find_module_file(project_dir, module_name)
    if module_path is None:
        return None
    symbols = _collect_module_symbols(module_path)
    matches = difflib.get_close_matches(symbol_name, symbols, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _find_module_file(project_dir: Path, module_name: str) -> Path | None:
    module_parts = module_name.split(".")
    candidate = project_dir.joinpath(*module_parts)
    direct_file = candidate.with_suffix(".py")
    if direct_file.exists():
        return direct_file
    package_init = candidate / "__init__.py"
    if package_init.exists():
        return package_init
    for path in _collect_python_files(project_dir):
        if path.stem == module_parts[-1]:
            return path
    return None


def _collect_module_symbols(module_path: Path) -> list[str]:
    from contextlib import suppress
    with suppress(SyntaxError, OSError):
        tree = ast.parse(module_path.read_text(encoding="utf-8", errors="replace"))
        symbols: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.append(target.id)
        return symbols
    return []


def _format_project_repair_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No repair events were recorded."
    blocks = []
    for event in events:
        fixes = event.get("fixes_applied") or ["No automatic fixes were applied."]
        blocks.append(
            "\n".join(
                [
                    f"- File: {event.get('file', 'unknown')}",
                    f"  Updated: {event.get('target_updated', False)}",
                    f"  Fixes: {'; '.join(fixes)}",
                ]
            )
        )
    return "\n".join(blocks)


def _format_runtime_smoke(runtime_smoke: dict[str, Any]) -> str:
    if not runtime_smoke.get("attempted"):
        reason = runtime_smoke.get("reason", "Runtime smoke was skipped.")
        return reason
    result = runtime_smoke.get("result", {})
    return textwrap.dedent(
        f"""\
        - Entrypoint: {runtime_smoke.get('entrypoint', 'unknown')}
        - Mode: {runtime_smoke.get('mode', '--help')}
        - Success: {runtime_smoke.get('success', False)}
        - Output: {(result.get('stdout') or result.get('stderr') or 'No runtime output.')}
        """
    ).strip()


def _format_runtime_repair_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No runtime repair events were recorded."
    blocks = []
    for event in events:
        if event.get("target_updated"):
            blocks.append(
                "\n".join(
                    [
                        f"- File: {event.get('file', 'unknown')}",
                        f"  Updated: True",
                        f"  Fixes: {'; '.join(event.get('fixes_applied', [])) or 'No details provided.'}",
                    ]
                )
            )
        else:
            blocks.append(
                "\n".join(
                    [
                        f"- File: {event.get('file', 'unknown')}",
                        f"  Updated: False",
                        f"  Reason: {event.get('reason', 'No details provided.')}",
                    ]
                )
            )
    return "\n".join(blocks)


def _extract_python_path(prompt: str) -> Path | None:
    quoted_match = re.search(r'["\']([^"\']+\.py)["\']', prompt)
    if quoted_match:
        return Path(quoted_match.group(1))

    path_match = re.search(r'([A-Za-z]:\\[^\s]+\.py|\.?[\\/][^\s]+\.py|[\w\-.\\/]+\.py)', prompt)
    if path_match:
        return Path(path_match.group(1))
    return None


def _repair_python_source(
    source: str,
    compiler_output: str,
    executor: Any | None = None,
    filename: str = "candidate.py",
    max_passes: int = 4,
) -> tuple[str, list[str]]:
    current_source = source
    fixes: list[str] = []
    current_output = compiler_output

    for _ in range(max_passes):
        updated_source, new_fixes = _apply_python_fix_pass(current_source, current_output)
        if updated_source == current_source or not new_fixes:
            break

        current_source = updated_source
        fixes.extend(new_fixes)
        if executor is None:
            break

        with TemporaryDirectory(prefix="jarvis-repair-pass-") as temp_dir:
            candidate_path = Path(temp_dir) / filename
            candidate_path.write_text(current_source, encoding="utf-8")
            compile_result = executor.py_compile([candidate_path], cwd=temp_dir)
        if compile_result.success:
            return current_source, fixes
        current_output = compile_result.stderr or compile_result.stdout

    return current_source, fixes


def _apply_python_fix_pass(source: str, compiler_output: str) -> tuple[str, list[str]]:
    lines = source.splitlines()
    fixes: list[str] = []
    changed = False

    line_numbers = [int(match) for match in re.findall(r"line (\d+)", compiler_output)]
    target_index = line_numbers[-1] - 1 if line_numbers else None
    previous_index = target_index - 1 if target_index is not None else None

    def append_colon(index: int, reason: str) -> None:
        nonlocal changed
        stripped = lines[index].rstrip()
        if stripped and not stripped.endswith(":"):
            lines[index] = stripped + ":"
            fixes.append(reason)
            changed = True

    control_keywords = ("def ", "if ", "elif ", "else", "for ", "while ", "class ", "try", "except", "finally", "with ", "match ", "case ")

    if target_index is not None and 0 <= target_index < len(lines):
        stripped = lines[target_index].lstrip()
        if any(stripped.startswith(keyword) for keyword in control_keywords):
            append_colon(target_index, f"Added a missing colon on line {target_index + 1}.")

    if previous_index is not None and 0 <= previous_index < len(lines):
        previous = lines[previous_index].lstrip()
        if any(previous.startswith(keyword) for keyword in control_keywords):
            lowered_output = compiler_output.lower()
            if "expected ':'" in lowered_output or "expected an indented block" in lowered_output:
                append_colon(previous_index, f"Added a missing colon on line {previous_index + 1}.")

    if "TabError" in compiler_output or "inconsistent use of tabs" in compiler_output:
        replaced = [line.replace("\t", "    ") for line in lines]
        if replaced != lines:
            lines = replaced
            fixes.append("Replaced tabs with spaces.")
            changed = True

    if "expected an indented block" in compiler_output and target_index is not None:
        block_line_match = re.search(r"expected an indented block after .* on line (\d+)", compiler_output)
        block_index = int(block_line_match.group(1)) - 1 if block_line_match else target_index
        for index in range(max(block_index + 1, 0), len(lines)):
            if lines[index].strip():
                if not lines[index].startswith((" ", "\t")):
                    lines[index] = "    " + lines[index]
                    fixes.append(f"Indented line {index + 1} to satisfy the required block.")
                    changed = True
                break

    never_closed_match = re.search(r"['\"]?([\(\[\{])['\"]?\s+was never closed", compiler_output)
    if never_closed_match and target_index is not None and 0 <= target_index < len(lines):
        closing_for = {"(": ")", "[": "]", "{": "}"}
        opener = never_closed_match.group(1)
        closer = closing_for.get(opener)
        if closer and not lines[target_index].rstrip().endswith(closer):
            lines[target_index] = lines[target_index].rstrip() + closer
            fixes.append(f"Added a missing closing '{closer}' on line {target_index + 1}.")
            changed = True

    if "unterminated string literal" in compiler_output and target_index is not None and 0 <= target_index < len(lines):
        line = lines[target_index]
        quote_char = '"' if line.count('"') % 2 else "'" if line.count("'") % 2 else None
        if quote_char:
            lines[target_index] = line + quote_char
            fixes.append(f"Closed an unterminated string literal on line {target_index + 1}.")
            changed = True

    updated = "\n".join(lines) + ("\n" if source.endswith("\n") else "")
    return (updated if changed else source), fixes
