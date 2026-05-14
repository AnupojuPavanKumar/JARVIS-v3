from __future__ import annotations
import re
from pathlib import Path
from datetime import datetime

def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "task"

def extract_topic(prompt: str, fallback: str) -> str:
    lowered = prompt.lower()
    for marker in (" for ", " about ", " on "):
        if marker in lowered:
            idx = lowered.index(marker) + len(marker)
            topic = prompt[idx:].strip(" .!?")
            if topic:
                return topic.title()
    return fallback

def write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return str(path)

def create_run_dir(base_root: Path, slug: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return base_root / slug / stamp

def resolve_workspace_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()

def extract_workspace_path(prompt: str, root: Path, *, allow_files: bool = True, allow_dirs: bool = True) -> Path | None:
    from contextlib import suppress
    lowered = prompt.lower()
    if any(marker in lowered for marker in ("this project", "current project", "this repo", "current repo", "this workspace", "current workspace")):
        return root

    candidates: list[str] = []
    candidates.extend(re.findall(r'["\']([^"\']+)["\']', prompt))
    candidates.extend(re.findall(r'([A-Za-z]:\\[^\s]+|\.?[\\/][^\s]+|[\w\-.\\/]+)', prompt))

    for raw_candidate in candidates:
        if raw_candidate.lower() in {"repair", "fix", "debug", "patch", "project", "repo", "workspace"}:
            continue
        with suppress(Exception):
            resolved = resolve_workspace_path(root, raw_candidate)
            if root not in resolved.parents and resolved != root:
                continue
            if allow_files and resolved.is_file():
                return resolved
            if allow_dirs and resolved.is_dir():
                return resolved
    return None
