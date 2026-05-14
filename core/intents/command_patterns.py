# core/intents/command_patterns.py — JARVIS Fast Intent Definitions
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("FastIntent")

OPEN_APP_TRIGGERS = [
    "open", "launch", "start", "run", "execute", "begin", "fire up", "boot up",
    "start up", "turn on", "load", "activate", "show", "display", "go to",
    "navigate to", "switch to", "bring up",
]
CLOSE_APP_TRIGGERS = [
    "close", "quit", "exit", "kill", "terminate", "shut down", "stop",
    "end", "shutdown", "close down", "shut",
]
WEB_SEARCH_TRIGGERS = [
    "search for", "search the web", "google ", "look up ", "find on web",
    "find online", "browse for", "web search", "search online",
    "bing ", "duckduckgo ", "wikipedia ", "what is", "who is",
    "when is", "where is", "how to", "how do",
]
FILE_OPEN_TRIGGERS = [
    "open file", "open document", "open pdf", "open folder", "open directory",
    "browse to", "navigate to file", "show file", "find file", "locate file",
    "read file", "view file", "access file",
]
VOLUME_CONTROL_TRIGGERS = [
    "volume up", "volume down", "volume mute", "volume unmute", "mute audio",
    "unmute audio", "increase volume", "decrease volume", "lower volume",
    "raise volume", "louder", "quieter", "set volume", "volume", "mute",
    "unmute", "max volume", "min volume",
]
MEDIA_CONTROL_TRIGGERS = [
    "play", "pause", "stop music", "next song", "previous song", "skip song",
    "play music", "pause music", "next track", "previous track", "resume music",
    "stop playback", "play track", "skip forward", "skip back",
]
SYSTEM_CONTROL_TRIGGERS = [
    "lock computer", "log off", "sign out", "restart computer", "reboot",
    "shutdown computer", "sleep", "hibernate", "restart", "reboot system",
    "shutdown", "sign out", "log out", "sign off",
]
WINDOW_CONTROL_TRIGGERS = [
    "minimize window", "maximize window", "restore window", "close window",
    "minimise window", "maximise window", "close tab", "new tab", "switch window",
    "next window", "previous window", "snap window",
]


@dataclass
class FastIntent:
    name: str
    confidence: float
    raw_command: str
    target: Optional[str] = None
    params: dict = field(default_factory=dict)

    def is_deterministic(self, threshold: float = 0.85) -> bool:
        return self.confidence >= threshold


def resolve_intent(command: str) -> FastIntent:
    lowered = command.lower().strip()

    # FILE_OPEN must be checked before OPEN_APP because "open file/report.pdf"
    # also contains the generic "open" app trigger.
    if _match_file_open(lowered, command):
        return _build_file_open(lowered, command)

    # OPEN_APP — highest priority, most common
    if _match_open_app(lowered, command):
        return _build_open_app(lowered, command)

    # CLOSE_APP
    if _match_close_app(lowered, command):
        return _build_close_app(lowered, command)

    # MEDIA_CONTROL
    if _match_media(lowered, command):
        return _build_media(lowered, command)

    # VOLUME_CONTROL
    if _match_volume(lowered, command):
        return _build_volume(lowered, command)

    # SYSTEM_CONTROL
    if _match_system(lowered, command):
        return _build_system(lowered, command)

    # WINDOW_CONTROL
    if _match_window(lowered, command):
        return _build_window(lowered, command)

    # WEB_SEARCH
    if _match_web_search(lowered, command):
        return _build_web_search(lowered, command)

    return FastIntent(name="UNKNOWN", confidence=0.0, raw_command=command)


def _match_open_app(lowered: str, original: str) -> bool:
    for t in OPEN_APP_TRIGGERS:
        if t in lowered:
            return True
    return False


def _build_open_app(lowered: str, original: str) -> FastIntent:
    target = None

    for t in OPEN_APP_TRIGGERS:
        idx = lowered.find(t)
        if idx != -1:
            after = lowered[idx + len(t):].strip().strip('."\'-')
            if after and len(after) >= 2:
                target = after
                break

    if not target:
        target = original.strip()

    known = {
        "vscode": "vscode",
        "visual studio code": "vscode",
        "code": "vscode",
        "chrome": "chrome",
        "google chrome": "chrome",
        "firefox": "firefox",
        "notepad": "notepad",
        "notepad++": "notepad++",
        "notepad plus plus": "notepad++",
        "calculator": "calculator",
        "calc": "calculator",
        "cmd": "cmd",
        "command prompt": "cmd",
        "powershell": "powershell",
        "ps": "powershell",
        "explorer": "explorer",
        "file explorer": "explorer",
        "edge": "edge",
        "microsoft edge": "edge",
        "spotify": "spotify",
        "discord": "discord",
        "slack": "slack",
        "teams": "teams",
        "microsoft teams": "teams",
        "zoom": "zoom",
        "zoom meeting": "zoom",
        "word": "word",
        "excel": "excel",
        "powerpoint": "powerpoint",
        "outlook": "outlook",
        "onenote": "onenote",
        "sublime": "sublime",
        "sublime text": "sublime",
        "pycharm": "pycharm",
        "webstorm": "webstorm",
        "intellij": "intellij",
        "jupyter": "jupyter",
        "jupyter notebook": "jupyter",
        "terminal": "terminal",
        "git bash": "gitbash",
        "obsidian": "obsidian",
        "postman": "postman",
        "docker": "docker",
        "virtualbox": "virtualbox",
        "task manager": "taskmgr",
        "regedit": "regedit",
        "device manager": "devmgmt",
        "control panel": "control",
        "snip": "snip",
        "snipping tool": "snip",
        "settings": "ms-settings",
        "photos": "photos",
        "camera": "microsoft.windows.camera:",
    }

    if target in known:
        target = known[target]

    return FastIntent(
        name="OPEN_APP",
        confidence=0.95,
        raw_command=original,
        target=target,
        params={"triggers": OPEN_APP_TRIGGERS}
    )


def _match_close_app(lowered: str, original: str) -> bool:
    return any(t in lowered for t in CLOSE_APP_TRIGGERS)


def _build_close_app(lowered: str, original: str) -> FastIntent:
    target = None
    for t in CLOSE_APP_TRIGGERS:
        idx = lowered.find(t)
        if idx != -1:
            after = lowered[idx + len(t):].strip().strip('."\'-')
            if after and len(after) >= 2:
                target = after
                break

    if not target:
        target = original.strip()

    return FastIntent(
        name="CLOSE_APP",
        confidence=0.90,
        raw_command=original,
        target=target,
    )


def _match_media(lowered: str, original: str) -> bool:
    return any(t in lowered for t in MEDIA_CONTROL_TRIGGERS)


def _build_media(lowered: str, original: str) -> FastIntent:
    action = "play"
    for t in ["play", "resume", "start"]:
        if t in lowered:
            action = "play"
            break
    for t in ["pause", "stop music", "stop playback"]:
        if t in lowered:
            action = "pause"
            break
    for t in ["next", "skip forward"]:
        if t in lowered:
            action = "next"
            break
    for t in ["previous", "skip back", "prev"]:
        if t in lowered:
            action = "previous"
            break

    return FastIntent(
        name="MEDIA_CONTROL",
        confidence=0.95,
        raw_command=original,
        target=action,
    )


def _match_volume(lowered: str, original: str) -> bool:
    return any(t in lowered for t in VOLUME_CONTROL_TRIGGERS)


def _build_volume(lowered: str, original: str) -> FastIntent:
    action = "set"
    if any(t in lowered for t in ["up", "louder", "raise", "increase", "max"]):
        action = "up"
    elif any(t in lowered for t in ["down", "quieter", "lower", "decrease", "min"]):
        action = "down"
    elif "mute" in lowered:
        if "un" in lowered:
            action = "unmute"
        else:
            action = "mute"

    return FastIntent(
        name="VOLUME_CONTROL",
        confidence=0.95,
        raw_command=original,
        target=action,
    )


def _match_system(lowered: str, original: str) -> bool:
    return any(t in lowered for t in SYSTEM_CONTROL_TRIGGERS)


def _build_system(lowered: str, original: str) -> FastIntent:
    action = "unknown"
    if "lock" in lowered:
        action = "lock"
    elif "sleep" in lowered or "hibernate" in lowered:
        action = "sleep"
    elif "restart" in lowered or "reboot" in lowered:
        action = "restart"
    elif "shutdown" in lowered or "shut down" in lowered:
        action = "shutdown"
    elif "log off" in lowered or "sign out" in lowered or "log out" in lowered:
        action = "logoff"

    return FastIntent(
        name="SYSTEM_CONTROL",
        confidence=0.95,
        raw_command=original,
        target=action,
    )


def _match_window(lowered: str, original: str) -> bool:
    return any(t in lowered for t in WINDOW_CONTROL_TRIGGERS)


def _build_window(lowered: str, original: str) -> FastIntent:
    action = "unknown"
    if "minimi" in lowered:
        action = "minimize"
    elif "maximi" in lowered or "restore" in lowered:
        action = "maximize"
    elif "close window" in lowered:
        action = "close"
    elif "new tab" in lowered:
        action = "new_tab"
    elif "switch window" in lowered or "next window" in lowered:
        action = "switch"

    return FastIntent(
        name="WINDOW_CONTROL",
        confidence=0.85,
        raw_command=original,
        target=action,
    )


def _match_web_search(lowered: str, original: str) -> bool:
    for t in WEB_SEARCH_TRIGGERS:
        if t in lowered:
            idx = lowered.find(t)
            after = lowered[idx + len(t):].strip()
            if after:
                return True
    return False


def _build_web_search(lowered: str, original: str) -> FastIntent:
    query = original
    for t in WEB_SEARCH_TRIGGERS:
        idx = lowered.find(t)
        if idx != -1:
            query = original[idx + len(t):].strip()
            if query:
                break

    return FastIntent(
        name="WEB_SEARCH",
        confidence=0.90,
        raw_command=original,
        target=query,
    )


def _match_file_open(lowered: str, original: str) -> bool:
    if any(t in lowered for t in FILE_OPEN_TRIGGERS):
        return True
    # Detect file paths by extension
    FILE_EXTENSIONS = (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".md", ".csv", ".json", ".xml", ".html", ".css", ".js",
        ".py", ".java", ".cpp", ".c", ".h", ".rb", ".go", ".rs",
        ".zip", ".rar", ".7z", ".tar", ".gz",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico",
        ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".wav",
        ".exe", ".msi", ".bat", ".sh",
    )
    return any(ext in lowered for ext in FILE_EXTENSIONS)


def _build_file_open(lowered: str, original: str) -> FastIntent:
    path = original
    m = re.search(r'["\']([^"\']+)["\']', original)
    if m:
        path = m.group(1)

    return FastIntent(
        name="FILE_OPEN",
        confidence=0.85,
        raw_command=original,
        target=path,
    )
