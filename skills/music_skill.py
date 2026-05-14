# skills/music_skill.py — JARVIS MUSIC CONTROL (Cross-Platform)
# ─────────────────────────────────────────────────────────────────────────────
# Controls music playback using VLC, system default player, or media keys.
# Refactored to use platform_shim for all media key events — no more
# direct ctypes.windll calls that crash on Linux/Mac.
# ─────────────────────────────────────────────────────────────────────────────

import os
import subprocess
import glob
from core.system.platform import platform_shim as P

SKILL_NAME  = "music"
TRIGGERS    = [
    "play music", "play song", "play some music", "start music",
    "pause music", "stop music", "resume music",
    "next song", "next track", "skip song",
    "previous song", "previous track",
    "play ", "shuffle music", "shuffle songs"
]
DESCRIPTION = "Controls local music playback via VLC or the system default player"

# Common music folder locations (cross-platform)
_MUSIC_DIRS = [
    os.path.join(os.path.expanduser("~"), "Music"),
    os.path.join(os.path.expanduser("~"), "Desktop", "Music"),
    # Public music — Windows only, skipped silently on Linux/Mac
    r"C:\Users\Public\Music" if P.is_windows() else "/usr/share/sounds",
]
_AUDIO_EXTS = (".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma")


def _find_music_files() -> list[str]:
    """Find all audio files in music directories."""
    files = []
    for d in _MUSIC_DIRS:
        if os.path.isdir(d):
            for ext in _AUDIO_EXTS:
                files.extend(glob.glob(os.path.join(d, "**", f"*{ext}"), recursive=True))
    return files


def _find_song(query: str) -> str | None:
    """Find the closest matching song file to a query."""
    query_lower = query.lower()
    files = _find_music_files()
    for f in files:
        if query_lower in os.path.basename(f).lower():
            return f
    return files[0] if files else None   # fallback: first song found


def _vlc_play(filepath: str) -> bool:
    """Open a file in VLC if installed — cross-platform paths."""
    vlc_candidates = []
    if P.is_windows():
        vlc_candidates = [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ]
    elif P.is_mac():
        vlc_candidates = ["/Applications/VLC.app/Contents/MacOS/VLC"]
    else:
        vlc_candidates = ["vlc"]   # Expect it to be on PATH on Linux

    for vlc in vlc_candidates:
        try:
            if P.is_linux():
                # On Linux check if vlc is in PATH
                if subprocess.run(["which", "vlc"], capture_output=True).returncode == 0:
                    subprocess.Popen(["vlc", filepath], close_fds=True)
                    return True
            elif os.path.exists(vlc):
                subprocess.Popen([vlc, filepath], close_fds=True)
                return True
        except Exception:
            continue
    return False


def _default_play(filepath: str) -> bool:
    """Open a file in the system default player (cross-platform)."""
    try:
        if P.is_windows():
            os.startfile(filepath)
        elif P.is_mac():
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])
        return True
    except Exception:
        return False


def run(command: str, context: dict) -> str:
    cmd = command.lower().strip()

    # ── Stop / Pause ─────────────────────────────────────────────────────────
    if any(w in cmd for w in ("stop music", "pause music", "pause song")):
        P.send_media_key("play_pause")
        return "Music paused, sir."

    # ── Resume ───────────────────────────────────────────────────────────────
    if any(w in cmd for w in ("resume music", "continue music", "unpause")):
        P.send_media_key("play_pause")
        return "Music resumed, sir."

    # ── Next track ───────────────────────────────────────────────────────────
    if any(w in cmd for w in ("next song", "next track", "skip song", "skip track")):
        P.send_media_key("next")
        return "Skipping to next track, sir."

    # ── Previous track ───────────────────────────────────────────────────────
    if any(w in cmd for w in ("previous song", "previous track", "last song")):
        P.send_media_key("prev")
        return "Going to previous track, sir."

    # ── Play specific song ────────────────────────────────────────────────────
    if "play " in cmd:
        after_play = cmd.split("play ", 1)[-1].strip()
        if after_play and after_play not in ("music", "song", "some music", "a song"):
            song = _find_song(after_play)
            if song:
                if not _vlc_play(song):
                    _default_play(song)
                return f"Playing {os.path.basename(song)}, sir."
            return f"I couldn't find '{after_play}' in your Music folder, sir."

    # ── Generic play music ────────────────────────────────────────────────────
    song = _find_song("")
    if song:
        if not _vlc_play(song):
            _default_play(song)
        return f"Playing music from your library, sir. Starting with {os.path.basename(song)}."

    # ── Open Spotify as last resort ───────────────────────────────────────────
    spotify_candidates = []
    if P.is_windows():
        spotify_candidates = [
            os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
        ]
    elif P.is_mac():
        spotify_candidates = ["/Applications/Spotify.app/Contents/MacOS/Spotify"]
    else:
        spotify_candidates = ["spotify"]   # Linux: check PATH

    for sp in spotify_candidates:
        try:
            if P.is_linux():
                if subprocess.run(["which", "spotify"], capture_output=True).returncode == 0:
                    subprocess.Popen(["spotify"])
                    return "Opening Spotify for you, sir."
            elif os.path.exists(sp):
                subprocess.Popen([sp], close_fds=True)
                return "Opening Spotify for you, sir."
        except Exception:
            continue

    return ("No music files found in your Music folder, sir. "
            "Add .mp3 files to ~/Music and I can play them directly.")
