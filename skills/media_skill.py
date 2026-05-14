import os
import subprocess
import re
from core.system.platform import platform_shim as P

SKILL_NAME = "Media & Display Control"
DESCRIPTION = "Controls volume, playback, and screen brightness."
TRIGGERS = [
    "volume up", "volume down", "max volume", "full volume", "unmute", "mute", "set volume",
    "brightness up", "brightness down", "max brightness", "dim screen", "set brightness",
    "next song", "next track", "previous song", "previous track", "pause music",
    "pause the music", "stop music", "play", "play music", "play song",
    "resume", "resume music", "resume playback"
]

def run(command: str, context: dict) -> str | None:
    cmd   = command.lower()
    words = cmd.split()

    # ── volume ────────────────────────────────────────────────
    if "volume up"   in cmd: return _volume_up()
    if "volume down" in cmd: return _volume_down()
    if "max volume"  in cmd or "full volume" in cmd: return _volume_max()
    if "unmute"      in cmd or "mute" in cmd: return _mute()
    if "set volume"  in cmd or ("volume" in cmd and any(c.isdigit() for c in cmd)):
        return _volume_set(cmd)

    # ── brightness ───────────────────────────────────────────
    if "brightness up"   in cmd: return _brightness(+20)
    if "brightness down" in cmd: return _brightness(-20)
    if "max brightness"  in cmd: return _brightness(100)
    if "dim screen"      in cmd: return _brightness(-30)
    _bm = re.search(r'brightness.*?(\d+)', cmd)
    if _bm:
        _bval = max(10, min(100, int(_bm.group(1))))
        return _brightness_abs(_bval)

    # ── media control ────────────────────────────────────────
    if "next song"     in cmd or "next track"     in cmd: return _media("next")
    if "previous song" in cmd or "previous track" in cmd: return _media("prev")
    if "pause music"   in cmd or "pause the music" in cmd: return _media("pause")
    if "stop music"    in cmd: return _media("stop")
    if words and words[0] == "play" or any(p in cmd for p in ("play music", "play song", "resume music", "resume playback")):
        return _media("play")
    if len(words) == 1 and words[0] == "resume": return _media("play")

    return None


def _volume_up():
    for _ in range(5): P.send_media_key("vol_up")
    return "Volume increased, sir."

def _volume_down():
    for _ in range(5): P.send_media_key("vol_down")
    return "Volume decreased, sir."

def _volume_max():
    for _ in range(50): P.send_media_key("vol_up")
    return "Volume at maximum, sir."

def _mute():
    P.send_media_key("mute")
    return "Audio toggled, sir."

def _volume_set(cmd):
    m = re.search(r'(\d+)', cmd)
    if m:
        tgt = int(m.group(1))
        for _ in range(50): P.send_media_key("vol_up")
        for _ in range(50 - int(tgt / 2)): P.send_media_key("vol_down")
        return f"Volume set to approximately {tgt}%, sir."
    return "Please specify a volume level, sir."

def _brightness(val):
    try:
        if P.is_windows():
            if val in (100, -30):
                new_val = 100 if val == 100 else 30
            else:
                r = subprocess.run(
                    ['powershell', '-Command',
                     '(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness'],
                    capture_output=True, text=True, timeout=5)
                cur = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 70
                new_val = max(10, min(100, cur + val))
            subprocess.run(
                ['powershell', '-Command',
                 f'(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{new_val})'],
                capture_output=True, timeout=5)
            return f"Brightness set to {new_val}%, sir."
        else:
            # Linux: use xrandr or brightnessctl
            subprocess.run(["brightnessctl", "set", f"{max(10, 70+val)}%"], capture_output=True)
            return "Brightness adjusted, sir."
    except Exception:
        return "Brightness control not available on this display, sir."

def _brightness_abs(target: int) -> str:
    try:
        if P.is_windows():
            subprocess.run(
                ['powershell', '-Command',
                 f'(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{target})'],
                capture_output=True, timeout=5)
        else:
            subprocess.run(["brightnessctl", "set", f"{target}%"], capture_output=True)
        return f"Brightness set to {target}%, sir."
    except Exception:
        return "Brightness control not available on this display, sir."

def _media(action):
    KEY_MAP = {"play": "play_pause", "pause": "play_pause",
               "next": "next", "prev": "prev", "stop": "play_pause"}
    P.send_media_key(KEY_MAP.get(action, "play_pause"))
    return {"play": "Playing, sir.", "pause": "Paused, sir.",
            "next": "Next track, sir.", "prev": "Previous track, sir.",
            "stop": "Stopped, sir."}.get(action, "Done, sir.")
