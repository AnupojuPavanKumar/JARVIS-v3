# core/screen_reader.py  —  JARVIS SCREEN READER (OCR + Vision)
# ──────────────────────────────────────────────────────────────────────────────
# Gives JARVIS eyes on the actual PC screen.
#
# Capabilities:
#   • read_screen()       — full OCR text extraction from any monitor
#   • read_region()       — OCR of a specific screen region (x,y,w,h)
#   • describe_screen()   — sends screenshot to Llava for visual description
#   • find_text(query)    — answers a question about visible on-screen text
#   • read_active_window()— captures just the focused window
#
# Dependencies already installed: pillow==12.x (PIL.ImageGrab)
# Optional: pytesseract (requires Tesseract-OCR installer on Windows)
#   pip install pytesseract
#   https://github.com/UB-Mannheim/tesseract/wiki
# ──────────────────────────────────────────────────────────────────────────────

import os
import time
import base64
import subprocess
import io
from typing import Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    import PIL.Image


# ──────────────────────────────────────────────────────────────────────────────
# SCREENSHOT CAPTURE
# ──────────────────────────────────────────────────────────────────────────────

def _capture_full() -> "PIL.Image.Image":
    """Capture the entire primary monitor. Tries PIL → mss → PowerShell fallback."""
    # Backend 1: PIL ImageGrab (default, works in GUI context)
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=False)
        if img and img.size[0] > 0:
            return img
    except Exception:
        pass

    # Backend 2: mss (faster, works in more contexts including subprocesses)
    try:
        import mss  # type: ignore
        from PIL import Image
        with mss.mss() as sct:
            monitor = sct.monitors[1]   # Primary monitor
            raw = sct.grab(monitor)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    except Exception:
        pass

    # Backend 3: PowerShell .NET screenshot (last resort, always works on Windows)
    try:
        import subprocess, io
        from PIL import Image
        ps_cmd = (
            "[Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null;"
            "$b = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,"
            "[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height);"
            "$g = [System.Drawing.Graphics]::FromImage($b);"
            "$g.CopyFromScreen(0,0,0,0,$b.Size);"
            "$ms = New-Object System.IO.MemoryStream;"
            "$b.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png);"
            "[Convert]::ToBase64String($ms.ToArray())"
        )
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            import base64
            img_data = base64.b64decode(result.stdout.strip())
            return Image.open(io.BytesIO(img_data))
    except Exception:
        pass

    raise RuntimeError("screen grab failed — all backends exhausted")


def _capture_region(x: int, y: int, w: int, h: int) -> "PIL.Image.Image":
    """Capture a specific region of the screen."""
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=(x, y, x + w, y + h))


def _capture_active_window() -> "PIL.Image.Image":
    """
    Capture only the currently focused window on Windows.
    Falls back to full-screen if window rect cannot be determined.
    """
    try:
        import ctypes
        from PIL import ImageGrab
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        return ImageGrab.grab(bbox=bbox)
    except Exception:
        return _capture_full()


def _save_screenshot(img, path: str = "memory/screen_capture.png"):
    """Save a PIL image to disk and return the path."""
    os.makedirs("memory", exist_ok=True)
    img.save(path, "PNG")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# OCR  (pytesseract — graceful no-op if not installed)
# ──────────────────────────────────────────────────────────────────────────────

def _ocr(img) -> str:
    """
    Extract text from a PIL image using pytesseract.
    Returns an empty string if Tesseract is not installed.
    """
    try:
        import pytesseract  # type: ignore
        # Try common Tesseract install locations on Windows
        _tess_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for p in _tess_paths:
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
        text = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
        return text.strip()
    except ImportError:
        return ""   # pytesseract not installed — silent fallback
    except Exception as e:
        print(f"[ScreenReader] OCR error: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# OLLAMA VISION (Llava / Llava-phi3)
# ──────────────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
VISION_MODEL = "llava:7b"


def _img_to_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _ask_vision(img, prompt: str, timeout: int = 30) -> str:
    """Send an image + prompt to Ollama's vision model (Llava)."""
    import requests
    try:
        payload = {
            "model": VISION_MODEL,
            "prompt": prompt,
            "images": [_img_to_b64(img)],
            "stream": False,
        }
        r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return None   # Ollama offline
    except Exception as e:
        return f"[Vision error: {e}]"


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

class ScreenReader:
    """
    High-level screen reading for JARVIS.
    Hybrid approach: fast OCR for text-heavy screens, Llava for UI understanding.
    """

    def read_screen(self) -> str:
        """
        Full-screen OCR → returns extracted text.
        Falls back to Llava if OCR yields nothing.
        """
        img  = _capture_full()
        text = _ocr(img)
        if len(text) > 30:
            return self._format_ocr(text)

        # Llava fallback
        vision = _ask_vision(img,
            "Describe all the text, windows, and UI elements visible on this screen. "
            "Be brief but include any error messages, code, or important information.")
        if vision:
            return f"[Screen Vision] {vision}"
        return "Screen capture completed but no readable text was found, sir."

    def read_active_window(self) -> str:
        """OCR + Vision on the currently focused window only."""
        img  = _capture_active_window()
        text = _ocr(img)
        if len(text) > 30:
            return self._format_ocr(text, prefix="[Active Window] ")
        vision = _ask_vision(img,
            "Describe the contents of this focused window. Include any text, code, "
            "error messages, or key UI elements.")
        if vision:
            return f"[Active Window Vision] {vision}"
        return "Could not extract text from the active window, sir."

    def find_text(self, query: str) -> str:
        """
        Answers a question about what's visible on screen.
        E.g.: "what is the error message?" / "what is the filename shown?"
        """
        img  = _capture_full()
        text = _ocr(img)

        # Try answering via OCR text first (fast, no GPU needed)
        if len(text) > 20:
            q = query.lower()
            # Simple keyword match — return surrounding lines
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            keywords = [w for w in q.split() if len(w) > 3 and w not in
                        ("what", "show", "find", "read", "tell", "is", "the", "on")]
            relevant = [l for l in lines if any(kw in l.lower() for kw in keywords)]
            if relevant:
                return "I can see on your screen, sir: " + " | ".join(relevant[:5])

        # Fall back to Llava if OCR didn't find anything useful
        vision = _ask_vision(img,
            f"Looking at this screenshot, please answer: {query}\n"
            "Be concise and direct. Only answer based on what you actually see.")
        if vision:
            return f"Based on your screen, sir: {vision}"
        return "I couldn't read that from your screen, sir. Please try pytesseract for better OCR."

    def describe_screen(self) -> str:
        """Full Llava visual description — best for UI elements, images, charts."""
        img    = _capture_full()
        vision = _ask_vision(img,
            "Describe everything visible on this computer screen in detail. "
            "What applications are open? What is the main content? "
            "Are there any errors, notifications, or important messages?",
            timeout=45)
        if vision:
            return vision
        # Try OCR as fallback
        text = _ocr(img)
        if text:
            return self._format_ocr(text)
        return "Llava vision model is offline, sir. Cannot describe the screen right now."

    def save_screenshot(self, path: str = "memory/screen_capture.png") -> str:
        """Take a screenshot and save it to disk."""
        img = _capture_full()
        saved = _save_screenshot(img, path)
        return f"Screenshot saved to {saved}, sir."

    @staticmethod
    def _format_ocr(text: str, prefix: str = "[Screen Text] ") -> str:
        """Clean and format raw OCR output."""
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 1]
        cleaned = "\n".join(lines[:40])   # cap at 40 lines for voice output
        # Condense for speech
        if len(cleaned) > 800:
            cleaned = cleaned[:800] + "…"
        return f"{prefix}{cleaned}"


# ── Singleton ────────────────────────────────────────────────────────────────
_screen_reader: Optional[ScreenReader] = None

def get_screen_reader() -> ScreenReader:
    global _screen_reader
    if _screen_reader is None:
        _screen_reader = ScreenReader()
    return _screen_reader
