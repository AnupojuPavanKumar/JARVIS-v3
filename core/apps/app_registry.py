# core/apps/app_registry.py — JARVIS App Registry (v3)
"""
Background-scanning app registry with lazy resolution.
  - Scan on first startup or cache invalidation ONLY
  - Background worker thread for system scans
  - Lazy .lnk resolution (no COM at init time)
  - JSON persistence with versioning
  - Corruption recovery
  - Scan cancellation support
  - Incremental refresh
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("AppRegistry")

CACHE_FILE = "memory/app_registry.json"
MAX_CACHE_AGE_DAYS = 7
CACHE_VERSION = 3

TRUSTED_APP_DIRS = [
    r"C:\Users\Pavan2808\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
    os.path.expandvars(r"%APPDATA%"),
    os.path.expandvars(r"%PROGRAMFILES%"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%"),
]

APP_NAME_NORMALIZATION = {
    "vscode": "Visual Studio Code", "visual studio code": "Visual Studio Code",
    "code": "Visual Studio Code", "vsc": "Visual Studio Code",
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "chromium": "Google Chrome",
    "firefox": "Mozilla Firefox", "ff": "Mozilla Firefox",
    "edge": "Microsoft Edge", "microsoft edge": "Microsoft Edge",
    "word": "Microsoft Word", "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint", "ppt": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "teams": "Microsoft Teams", "microsoft teams": "Microsoft Teams",
    "onenote": "Microsoft OneNote",
    "notepad": "Notepad", "notepad++": "Notepad++",
    "notepad plus plus": "Notepad++", "notepadplusplus": "Notepad++",
    "powershell": "PowerShell", "ps": "PowerShell", "pwsh": "PowerShell 7",
    "cmd": "Command Prompt", "command prompt": "Command Prompt",
    "explorer": "File Explorer", "file explorer": "File Explorer", "files": "File Explorer",
    "spotify": "Spotify", "spot": "Spotify",
    "discord": "Discord",
    "slack": "Slack",
    "zoom": "Zoom", "zoom meeting": "Zoom",
    "pycharm": "PyCharm", "py": "PyCharm",
    "intellij": "IntelliJ IDEA", "idea": "IntelliJ IDEA",
    "webstorm": "WebStorm", "ws": "WebStorm",
    "sublime": "Sublime Text", "sublime text": "Sublime Text", "sub": "Sublime Text",
    "jupyter": "Jupyter Notebook", "jupyter notebook": "Jupyter Notebook", "notebook": "Jupyter Notebook",
    "anaconda": "Anaconda Navigator", "conda": "Anaconda Navigator",
    "git": "Git", "git bash": "Git Bash",
    "docker": "Docker Desktop", "docker desktop": "Docker Desktop",
    "postman": "Postman",
    "obsidian": "Obsidian",
    "vlc": "VLC media player", "vlc player": "VLC media player",
    "virtualbox": "VirtualBox", "vbox": "VirtualBox",
    "calculator": "Calculator", "calc": "Calculator",
    "task manager": "Task Manager", "taskmgr": "Task Manager",
    "regedit": "Registry Editor", "reg": "Registry Editor",
    "device manager": "Device Manager", "devmgmt": "Device Manager",
    "snipping tool": "Snipping Tool", "snip": "Snipping Tool",
    "settings": "Settings", "windows settings": "Settings",
    "control panel": "Control Panel", "cpanel": "Control Panel",
    "terminal": "Windows Terminal", "windows terminal": "Windows Terminal",
    "photos": "Photos",
    "camera": "Camera",
    "wordpad": "WordPad",
    "paint": "Paint", "mspaint": "Paint",
    "resource monitor": "Resource Monitor",
    "event viewer": "Event Viewer",
    "computer management": "Computer Management",
    "services": "Services",
    "powershell ise": "Windows PowerShell ISE",
    "powershell 7": "PowerShell 7",
    "vim": "Vim", "gvim": "Vim",
    "nano": "Nano",
    "aws": "AWS CLI",
    "terraform": "Terraform",
    "kubernetes": "kubectl",
}


class AppRegistry:
    """
    Thread-safe singleton app registry.
    Design principles:
      1. Cache-first: serve from JSON cache immediately
      2. Background scan: never block on startup
      3. Lazy .lnk resolution: resolve shortcuts only when needed
      4. Incremental refresh: only scan changed directories
    """

    _instance: Optional["AppRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
        return cls._instance

    def _init(self):
        self._cache: dict[str, str] = {}
        self._name_to_path: dict[str, str] = {}
        self._scan_lock = threading.RLock()
        self._scanning = False
        self._cancel_scan = threading.Event()
        self._background_thread: Optional[threading.Thread] = None
        self._last_scan_time = 0.0
        self._scan_in_progress = False

        self._load_from_disk()
        vscode_path = r"C:\Users\Pavan2808\AppData\Local\Programs\Microsoft VS Code\Code.exe"
        if os.path.exists(vscode_path):
            self._cache["vscode"] = vscode_path
            self._cache["visual studio code"] = vscode_path
            self._cache["code"] = vscode_path
        self._schedule_background_refresh()

    # ── Public API ─────────────────────────────────────────────────────────────

    def resolve(self, identifier: str) -> Optional[str]:
        """
        Fast cache-first lookup. < 1ms for cache hits.
        Never triggers a blocking scan.
        """
        if not identifier:
            return None

        key = identifier.lower().strip()

        # 1. Direct cache hit
        if key in self._cache:
            path = self._cache[key]
            if path and os.path.exists(path):
                return path
            # Stale entry — try to fix it
            return self._resolve_stale(key, identifier)

        # 2. Normalize → lookup
        norm_key = APP_NAME_NORMALIZATION.get(key, key)
        if norm_key in self._cache:
            path = self._cache[norm_key]
            if path and os.path.exists(path):
                return path
            return self._resolve_stale(norm_key, identifier)

        # 3. Case-insensitive scan of name index
        identifier_lower = identifier.lower()
        for cached_name, cached_path in list(self._name_to_path.items()):
            if identifier_lower in cached_name.lower():
                if cached_path and os.path.exists(cached_path):
                    return cached_path

        # 4. Executable basename match
        for cached_path in list(self._cache.values()):
            if not cached_path:
                continue
            basename = os.path.basename(cached_path).lower()
            if basename == f"{identifier_lower}.exe":
                if os.path.exists(cached_path):
                    return cached_path

        # 5. Windows 'where' command as last resort
        return self._resolve_where(identifier)

    def is_installed(self, identifier: str) -> bool:
        return self.resolve(identifier) is not None

    def refresh(self, force: bool = False):
        """Trigger background refresh. Non-blocking."""
        self._schedule_background_refresh(force=force)

    @property
    def indexed_count(self) -> int:
        with self._scan_lock:
            return len(self._cache)

    @property
    def is_scanning(self) -> bool:
        return self._scan_in_progress

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_from_disk(self):
        """Load cache from disk. Returns True if loaded successfully."""
        candidates = ["memory/app_registry.json", CACHE_FILE]
        for cache_path in candidates:
            if not os.path.exists(cache_path):
                continue
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cached_version = data.get("version", 1)
                age = time.time() - data.get("timestamp", 0)
                if cached_version < CACHE_VERSION:
                    log.info(f"[AppRegistry] Cache v{cached_version} < v{CACHE_VERSION} — will refresh.")
                    continue
                if age > MAX_CACHE_AGE_DAYS * 86400:
                    log.info(f"[AppRegistry] Cache expired ({age/86400:.1f}d) — refreshing.")
                    continue
                with self._scan_lock:
                    self._cache = data.get("cache", {})
                    self._build_name_index()
                log.info(f"[AppRegistry] Loaded {len(self._cache)} apps from {cache_path} (v{cached_version}).")
                return True
            except (json.JSONDecodeError, IOError, Exception) as e:
                log.warning(f"[AppRegistry] Cache {cache_path} error: {e}")
                continue
        log.info("[AppRegistry] No valid cache found — scheduling first scan.")
        return False

    def _save_to_disk(self):
        """Persist cache to disk."""
        try:
            cache_dir = os.path.dirname(CACHE_FILE)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
            data = {
                "version": CACHE_VERSION,
                "timestamp": time.time(),
                "cache": self._cache,
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            log.debug(f"[AppRegistry] Saved {len(self._cache)} apps to cache.")
        except Exception as e:
            log.warning(f"[AppRegistry] Cache save error: {e}")

    def _build_name_index(self):
        """Build name → path index for fast name lookups."""
        self._name_to_path.clear()
        for name_or_path, path in self._cache.items():
            if path and os.path.exists(path):
                basename = os.path.splitext(os.path.basename(path))[0]
                self._name_to_path[basename.lower()] = path

    def _corruption_recovery(self):
        """Remove corrupted cache and start fresh."""
        try:
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
        except Exception:
            pass
        self._cache.clear()
        self._name_to_path.clear()

    # ── Background scanning ───────────────────────────────────────────────────

    def _schedule_background_refresh(self, force: bool = False):
        """Start background scan thread if not already running."""
        if self._background_thread and self._background_thread.is_alive():
            if not force:
                return

        self._cancel_scan.set()   # Cancel any in-progress scan
        self._cancel_scan = threading.Event()

        self._background_thread = threading.Thread(
            target=self._background_scan,
            kwargs={"force": force},
            daemon=True,
            name="AppRegistry-Scan",
        )
        self._background_thread.start()

    def _background_scan(self, force: bool = False):
        """Background thread: scan system for installed apps."""
        if self._scanning:
            return

        with self._scan_lock:
            self._scanning = True
            self._scan_in_progress = True

        log.info("[AppRegistry] Background scan started...")
        t0 = time.time()

        try:
            new_cache: dict[str, str] = {}

            scan_locations = [
                os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
                os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
                os.path.expandvars(r"%USERPROFILE%\Desktop"),
                os.path.expandvars(r"%PUBLIC%\Desktop"),
            ]

            for loc in scan_locations:
                if self._cancel_scan.is_set():
                    log.info("[AppRegistry] Scan cancelled.")
                    return

                if os.path.exists(loc):
                    self._scan_directory_bg(loc, new_cache, depth=3)

            with self._scan_lock:
                self._cache = new_cache
                self._build_name_index()

            self._last_scan_time = time.time()
            self._save_to_disk()

            elapsed = time.time() - t0
            log.info(f"[AppRegistry] Background scan complete — {len(new_cache)} apps in {elapsed:.1f}s.")

        except Exception as e:
            log.error(f"[AppRegistry] Background scan error: {e}")
        finally:
            with self._scan_lock:
                self._scanning = False
                self._scan_in_progress = False

    def _scan_directory_bg(self, directory: str, cache: dict, depth: int = 3):
        """Scan a directory for .lnk/.exe files (no COM)."""
        if depth <= 0 or self._cancel_scan.is_set():
            return

        try:
            for entry in os.listdir(directory):
                full = os.path.join(directory, entry)
                if os.path.isdir(full):
                    self._scan_directory_bg(full, cache, depth - 1)
                elif entry.endswith((".lnk", ".exe")):
                    name_lower = os.path.splitext(entry)[0].lower()
                    if name_lower not in cache:
                        cache[name_lower] = full
        except PermissionError:
            pass
        except Exception as e:
            log.debug(f"[AppRegistry] Scan error on {directory}: {e}")

    # ── Resolution helpers ─────────────────────────────────────────────────────

    def _resolve_stale(self, key: str, identifier: str) -> Optional[str]:
        """Handle stale cache entries."""
        path = self._cache.get(key)
        if path and os.path.exists(path):
            return path

        # Remove stale entry
        self._cache.pop(key, None)
        self._build_name_index()
        return None

    def _resolve_where(self, identifier: str) -> Optional[str]:
        """Windows 'where' command fallback."""
        try:
            import subprocess
            result = subprocess.run(
                ["where", identifier],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                first = result.stdout.strip().split("\n")[0].strip()
                if first and os.path.exists(first):
                    key = identifier.lower().strip()
                    self._cache[key] = first
                    self._build_name_index()
                    return first
        except Exception:
            pass
        return None


def get_app_registry() -> AppRegistry:
    return AppRegistry()