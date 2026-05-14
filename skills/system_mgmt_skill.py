import os
import datetime
import subprocess
from core.system.platform import platform_shim as P

SKILL_NAME  = "System Management"
DESCRIPTION = "Handles screenshots, clipboard, and window management."
TRIGGERS    = ["screenshot", "capture screen", "maximize", "minimize",
               "copy to clipboard", "clear clipboard"]

def run(command: str, context: dict) -> str | None:
    cmd = command.lower()

    if any(p in cmd for p in ("screenshot", "take a screenshot", "capture screen")):
        return _screenshot()
    if "maximize" in cmd:
        return _win_maximize()
    if "minimize" in cmd:
        return _win_minimize()
    if "copy" in cmd and "clipboard" in cmd:
        text = cmd.replace("copy", "").replace("to clipboard", "").strip()
        return _clipboard(text)
    if "clear clipboard" in cmd:
        return _clipboard("")

    return None


def _screenshot():
    try:
        os.makedirs("memory", exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.abspath(f"memory/screenshot_{ts}.png")

        if P.is_windows():
            # PowerShell GDI capture — reliable on Windows without extra deps
            subprocess.Popen(
                ["powershell", "-Command",
                 f"[Reflection.Assembly]::LoadWithPartialName('System.Drawing');"
                 f"$b=New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,"
                 f"[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height);"
                 f"$g=[System.Drawing.Graphics]::FromImage($b);"
                 f"$g.CopyFromScreen(0,0,0,0,$b.Size);"
                 f"$b.Save('{path}')"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif P.is_mac():
            subprocess.run(["screencapture", path], check=False)
        else:
            # Linux: try scrot, then gnome-screenshot
            if subprocess.run(["which", "scrot"], capture_output=True).returncode == 0:
                subprocess.run(["scrot", path], check=False)
            else:
                subprocess.run(["gnome-screenshot", "-f", path], check=False)

        return "Screenshot saved to memory folder, sir."
    except Exception as exc:
        return f"Screenshot failed: {exc}"


def _win_maximize():
    try:
        if P.is_windows():
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x26, 0, 0, 0)  # Up arrow down
            ctypes.windll.user32.keybd_event(0x26, 0, 2, 0)  # Up arrow up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
        else:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,maximized_vert,maximized_horz"],
                           check=False)
        return "Window maximized, sir."
    except Exception as exc:
        return f"Maximize failed: {exc}"


def _win_minimize():
    try:
        if P.is_windows():
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x28, 0, 0, 0)  # Down arrow down
            ctypes.windll.user32.keybd_event(0x28, 0, 2, 0)  # Down arrow up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
        else:
            subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b", "add,hidden"], check=False)
        return "Window minimized, sir."
    except Exception as exc:
        return f"Minimize failed: {exc}"


def _clipboard(text):
    try:
        if P.is_windows():
            subprocess.run(
                ["powershell", "-Command", "$input | Set-Clipboard"],
                input=text, text=True, capture_output=True
            )
        elif P.is_mac():
            subprocess.run(["pbcopy"], input=text.encode(), check=False)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode(), check=False)
        return "Copied to clipboard, sir." if text else "Clipboard cleared, sir."
    except Exception:
        return "Clipboard operation failed, sir."
