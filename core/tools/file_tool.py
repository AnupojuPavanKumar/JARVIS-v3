# core/tools/file_tool.py  —  JARVIS FILE TOOL
# Safe file read / write / append / list / delete operations

import os
import re
import shutil
from pathlib import Path

# ── Protected system paths (never touch these) ───────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _project_path(relative_path: str) -> str:
    return _norm(_PROJECT_ROOT / relative_path)


PROTECTED_PREFIXES = [
    _norm("c:\\windows"),
    _norm("c:\\program files"),
    _norm("c:\\program files (x86)"),
    _norm("c:\\programdata\\microsoft"),
    _norm("c:\\users\\default"),
]

PROTECTED_FILES = [
    # JARVIS Internal Security (prevent agent tampering)
    _project_path("jarvis_auth.db"),
    _project_path("vibe_shield_logs.db"),
    _project_path("memory/api_token.txt"),
    _project_path("memory/auth_config.json"),
    _project_path("memory/jarvis_config.json"),
    _project_path("logs/security.log"),
]

MAX_READ_CHARS  = 4000   # Max chars returned from a single read
MAX_LIST_ITEMS  = 80     # Max directory entries shown


class FileTool:

    # ── Safety ────────────────────────────────────────────────────────────────
    def _is_safe(self, path: str) -> bool:
        """Return True if path is outside all protected directories."""
        candidates = [_norm(path)]
        raw_path = Path(path)
        if not raw_path.is_absolute():
            candidates.append(_norm(_PROJECT_ROOT / raw_path))

        for norm in candidates:
            for prefix in PROTECTED_PREFIXES:
                if norm == prefix or norm.startswith(prefix + os.sep):
                    return False
            if norm in PROTECTED_FILES:
                return False

        return True

    # ── Read ──────────────────────────────────────────────────────────────────
    def read(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) > MAX_READ_CHARS:
                return content[:MAX_READ_CHARS] + f"\n... (file truncated at {MAX_READ_CHARS} chars)"
            return content if content else "(file is empty)"
        except FileNotFoundError:
            return f"File not found: {path}"
        except IsADirectoryError:
            return f"'{path}' is a directory, not a file. Use list_dir instead."
        except PermissionError:
            return f"Permission denied reading: {path}"
        except Exception as e:
            return f"Read error: {e}"

    # ── Write ─────────────────────────────────────────────────────────────────
    def write(self, path: str, content: str) -> str:
        if not self._is_safe(path):
            return f"[BLOCKED] Cannot write to protected path: {path}"
        try:
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            size = os.path.getsize(path)
            return f"File written successfully: {path} ({size} bytes)"
        except PermissionError:
            return f"Permission denied writing: {path}"
        except Exception as e:
            return f"Write error: {e}"

    # ── Append ────────────────────────────────────────────────────────────────
    def append(self, path: str, content: str) -> str:
        if not self._is_safe(path):
            return f"[BLOCKED] Cannot append to protected path: {path}"
        try:
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended to: {path}"
        except PermissionError:
            return f"Permission denied appending to: {path}"
        except Exception as e:
            return f"Append error: {e}"

    # ── List directory ────────────────────────────────────────────────────────
    def list_dir(self, path: str) -> str:
        try:
            if not os.path.isdir(path):
                return f"Not a directory: {path}"
            items = os.listdir(path)
            lines = []
            for item in items[:MAX_LIST_ITEMS]:
                full = os.path.join(path, item)
                if os.path.isdir(full):
                    lines.append(f"[DIR]  {item}")
                else:
                    try:
                        sz = os.path.getsize(full)
                        lines.append(f"[FILE] {item}  ({sz:,} bytes)")
                    except Exception:
                        lines.append(f"[FILE] {item}")
            if len(items) > MAX_LIST_ITEMS:
                lines.append(f"... and {len(items) - MAX_LIST_ITEMS} more items")
            return "\n".join(lines) if lines else "(directory is empty)"
        except PermissionError:
            return f"Permission denied listing: {path}"
        except Exception as e:
            return f"List directory error: {e}"

    # ── Delete ────────────────────────────────────────────────────────────────
    def delete(self, path: str, identity: str = "owner") -> str:
        if identity != "owner":
            return "[DENIED] Owner clearance required to delete files."
        if not self._is_safe(path):
            return f"[BLOCKED] Cannot delete protected system file: {path}"
        try:
            if not os.path.exists(path):
                return f"File not found: {path}"
            if os.path.isdir(path):
                return f"'{path}' is a directory. Use shell rmdir for directories."
            os.remove(path)
            return f"Deleted: {path}"
        except PermissionError:
            return f"Permission denied deleting: {path}"
        except Exception as e:
            return f"Delete error: {e}"

    # ── Replace In File ────────────────────────────────────────────────────────
    def replace_in_file(self, path: str, target: str, replacement: str) -> str:
        if not self._is_safe(path):
            return f"[BLOCKED] Cannot modify protected path: {path}"
        try:
            if not os.path.exists(path):
                return f"File not found: {path}"

            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # Create backup
            bak_path = path + ".bak"
            shutil.copy2(path, bak_path)

            # Strict match first
            if target in content:
                new_content = content.replace(target, replacement, 1)
            else:
                # Fuzzy match (whitespace tolerant)
                escaped = re.escape(target.strip())
                pattern_str = re.sub(r'\\?[ \t\r\n]+', r'\\s+', escaped)
                pattern = re.compile(pattern_str)
                matches = pattern.findall(content)
                
                if not matches:
                    return f"Target string not found in {path}. Check for typos."
                if len(matches) > 1:
                    return f"Target string is ambiguous ({len(matches)} matches found). Provide a larger unique block of code."
                
                new_content = pattern.sub(replacement, content, count=1)

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
                
            return f"Successfully replaced code block in {path}. Backup saved."
        except PermissionError:
            return f"Permission denied modifying: {path}"
        except Exception as e:
            return f"Replace error: {e}"

    # ── Undo Last Edit ─────────────────────────────────────────────────────────
    def undo_last_edit(self, path: str) -> str:
        if not self._is_safe(path):
            return f"[BLOCKED] Cannot modify protected path: {path}"
        bak_path = path + ".bak"
        try:
            if not os.path.exists(bak_path):
                return f"No backup (.bak) found for {path}."
            if not os.path.exists(path):
                return f"Original file {path} not found."
            
            shutil.copy2(bak_path, path)
            return f"Undid last edit. Restored {path} from backup."
        except PermissionError:
            return f"Permission denied restoring: {path}"
        except Exception as e:
            return f"Undo error: {e}"
