import os
import subprocess
from core.system.platform import platform_shim as P

SKILL_NAME  = "Power & Session Control"
DESCRIPTION = "Manages system power states (shutdown, restart, lock, sleep, hibernate)."
TRIGGERS    = [
    "shut down", "shutdown", "power off", "turn off", "restart", "reboot",
    "lock", "lock screen", "sleep mode", "monitor sleep", "hibernate",
    "log off", "sign out", "show desktop", "minimize all", "empty recycle"
]

_SHUTDOWN_DELAY = 60  # seconds

def run(command: str, context: dict) -> str | None:
    cmd   = command.lower()
    words = cmd.split()

    if any(p in cmd for p in ("shut down", "shutdown", "power off", "turn off")):
        return _shutdown_request(context, cmd)
    if "restart" in words or "reboot" in words:
        return _restart_request(context, cmd)
    if any(p in cmd for p in ("lock", "lock screen", "lock the screen")):
        return _lock()
    if any(p in cmd for p in ("sleep mode", "monitor sleep", "screen sleep",
                               "turn off screen", "turn off monitor", "screen off", "display off")):
        return _sleep()
    if any(p in cmd for p in ("hibernate", "system hibernate")):
        return _hibernate_request(context, cmd)
    if any(p in cmd for p in ("log off", "sign out", "logoff")):
        return _logoff_request(context, cmd)
    if "shutdown abort" in cmd or "cancel shutdown" in cmd:
        return _abort_shutdown()
    if any(p in cmd for p in ("show desktop", "minimize all", "hide windows")):
        return _show_desktop()
    if "empty recycle" in cmd or "clear recycle" in cmd:
        return _empty_recycle()

    return None


def _shutdown_request(context, cmd: str):
    if context.get("identity") != "owner":
        return "Access denied. Owner clearance required, sir."

    if "confirm" not in cmd:
        return "Shutdown will begin in {_SHUTDOWN_DELAY} seconds. Say 'confirm shutdown' to proceed, or 'shutdown abort' to cancel."

    if P.is_windows():
        subprocess.Popen(["shutdown", "/s", "/t", str(_SHUTDOWN_DELAY)])
    else:
        subprocess.Popen(["shutdown", "-h", "1"])
    return f"Shutdown initiated in {_SHUTDOWN_DELAY} seconds, sir. Say 'shutdown abort' to cancel."


def _restart_request(context, cmd: str):
    if context.get("identity") != "owner":
        return "Access denied."

    if "confirm" not in cmd:
        return f"Restart will begin in {_SHUTDOWN_DELAY} seconds. Say 'confirm restart' to proceed, or 'shutdown abort' to cancel."

    if P.is_windows():
        subprocess.Popen(["shutdown", "/r", "/t", str(_SHUTDOWN_DELAY)])
    else:
        subprocess.Popen(["shutdown", "-r", "1"])
    return f"Restarting in {_SHUTDOWN_DELAY} seconds, sir. Say 'shutdown abort' to cancel."


def _lock():
    try:
        P.lock_workstation()
        return "Workstation locked, sir."
    except Exception as exc:
        return f"Lock failed, sir: {exc}"


def _sleep():
    try:
        P.turn_off_display()
        return "Monitor turned off, sir. Move the mouse to wake."
    except Exception:
        return "Could not turn off monitor, sir."


def _hibernate_request(context, cmd: str):
    if context.get("identity") != "owner":
        return "Access denied."

    if "confirm" not in cmd:
        return "System will hibernate. Say 'confirm hibernate' to proceed."

    if P.is_windows():
        subprocess.Popen(["shutdown", "/h"])
    else:
        subprocess.run(["systemctl", "hibernate"], check=False)
    return "Initiating hibernate, sir. State saved to disk."


def _logoff_request(context, cmd: str):
    if context.get("identity") != "owner":
        return "Access denied."

    if "confirm" not in cmd:
        return "You will be signed out. Say 'confirm log off' to proceed."

    if P.is_windows():
        subprocess.Popen(["shutdown", "/l"])
    else:
        # FIX: Safer logoff - use loginctl instead of pkill
        user = os.environ.get("USER")
        if user:
            subprocess.run(["loginctl", "terminate-user", user], check=False)
        else:
            return "Could not determine user for logoff."
    return "Signing out, sir."


def _abort_shutdown():
    try:
        if P.is_windows():
            subprocess.run(["shutdown", "/a"], capture_output=True)
        else:
            # On Linux, there's no standard abort - just note that it can't be aborted
            pass
        return "Shutdown aborted, sir."
    except Exception:
        return "Could not abort shutdown."


def _show_desktop():
    try:
        P.minimize_all_windows()
        return "Desktop shown, sir."
    except Exception:
        return "Show desktop failed."


def _empty_recycle():
    try:
        if P.is_windows():
            subprocess.run(
                ["powershell", "-Command", "Clear-RecycleBin -Confirm:$false"],
                capture_output=True
            )
        else:
            subprocess.run(["rm", "-rf", os.path.expanduser("~/.local/share/Trash/*")],
                           capture_output=True)
        return "Recycle bin emptied, sir."
    except Exception:
        return "Empty recycle bin failed."