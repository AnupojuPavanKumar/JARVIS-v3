# core/screen_context.py — JARVIS SCREEN-AWARE CONTEXT ENGINE
# ──────────────────────────────────────────────────────────────────────────────
# Gives JARVIS the ability to SEE the user's screen.
# Used for: "what's on my screen?", "fix this error", "explain this code",
#           "search for this", "read that for me"
#
# Pipeline:
#   1. Capture screen via mss (fast, no UI freeze)
#   2. OCR via pytesseract (extract text, graceful if not installed)
#   3. Context detection: terminal, browser, code editor, error dialog
#   4. LLM analysis via llama3.2:3b for smart responses
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os, re, datetime, logging
import requests

log = logging.getLogger("screen_context")

OLLAMA_URL     = "http://localhost:11434/api/chat"
ANALYSIS_MODEL = "llama3.2:3b"
SCREENSHOT_DIR = "memory"
SCREENSHOT_MAX_CHARS = 2000   # cap OCR text sent to LLM to stay within context


class ScreenContextEngine:
    """
    Captures the screen, extracts text via OCR, classifies context,
    and answers questions about what's visible.
    """

    def __init__(self):
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────────

    def describe_screen(self) -> str:
        """
        'What's on my screen?' — capture + OCR + LLM summary.
        Returns a human-readable description.
        """
        screenshot_path, ocr_text = self._capture_and_ocr()
        context_type              = self._classify_context(ocr_text)

        if not ocr_text.strip():
            return "I can see your screen, sir, but no readable text was found."

        prompt = (
            f"The user asked 'what's on my screen?'. "
            f"Here is the text visible on screen (OCR extracted from the {context_type}): "
            f"\n\n{ocr_text[:SCREENSHOT_MAX_CHARS]}\n\n"
            f"Give a concise, helpful JARVIS-style summary (2-4 sentences, addressed as 'sir'). "
            f"Focus on the most important/relevant visible content."
        )
        return self._llm_analyse(prompt, ocr_text)

    def fix_visible_error(self) -> str:
        """
        'Fix this' / 'fix this error' — reads screen, extracts error/traceback,
        returns diagnosis + fix.
        """
        _, ocr_text = self._capture_and_ocr()

        # Try to extract just the error/traceback portion
        error_text = self._extract_error(ocr_text)

        if not error_text:
            if ocr_text.strip():
                error_text = ocr_text
            else:
                return "I cannot see a clear error on your screen, sir. Could you describe it?"

        # Use GhostDebugger for triage
        try:
            from core.agent.ghost_debugger import GhostDebugger
            diag = GhostDebugger().diagnose_error(error_text)
            return diag
        except Exception:
            pass

        prompt = (
            f"The user said 'fix this'. Here is the error/text visible on their screen:\n\n"
            f"{error_text[:1200]}\n\n"
            f"Diagnose the root cause and give the exact fix. Be concise. Address as 'sir'."
        )
        return self._llm_analyse(prompt, ocr_text)

    def explain_visible_code(self) -> str:
        """'Explain this code' — reads screen and explains what the code does."""
        _, ocr_text = self._capture_and_ocr()

        if not ocr_text.strip():
            return "I cannot read any code on your screen, sir."

        prompt = (
            f"The user said 'explain this code'. Here is what is visible on their screen:\n\n"
            f"{ocr_text[:SCREENSHOT_MAX_CHARS]}\n\n"
            f"Explain what this code does clearly and concisely (3-5 sentences). "
            f"Mention the language, main purpose, and any notable patterns. "
            f"Address as 'sir'."
        )
        return self._llm_analyse(prompt, ocr_text)

    def search_visible_text(self) -> str:
        """'Search for this' — extracts visible text and performs a web search."""
        _, ocr_text = self._capture_and_ocr()

        # Take first meaningful line as the search query
        lines = [l.strip() for l in ocr_text.splitlines() if len(l.strip()) > 10]
        if not lines:
            return "I cannot find searchable text on your screen, sir."

        query = lines[0][:120]
        try:
            from core.agent.web_research import get_web_agent
            result = get_web_agent().research(query)
            return f"Searching for '{query}':\n{result}"
        except Exception as e:
            return f"Search error: {e}"

    def read_screen_aloud(self) -> str:
        """'Read that' / 'read my screen' — just returns the OCR text."""
        _, ocr_text = self._capture_and_ocr()
        if not ocr_text.strip():
            return "I cannot read any text from the screen, sir."
        # Return first 500 chars to keep spoken output reasonable
        return ocr_text.strip()[:500]

    # ── Capture + OCR ───────────────────────────────────────────────────────

    def _capture_and_ocr(self) -> tuple[str, str]:
        """Returns (screenshot_path, ocr_text)."""
        path = os.path.join(SCREENSHOT_DIR, "_screen_context.png")

        # Capture
        try:
            try:
                import mss, mss.tools
                with mss.mss() as sct:
                    monitor = sct.monitors[1]
                    img     = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=path)
            except ImportError:
                from PIL import ImageGrab
                ImageGrab.grab().save(path)
        except Exception as e:
            log.warning(f"[ScreenContext] Capture failed: {e}")
            return "", ""

        # OCR
        ocr_text = ""
        try:
            import pytesseract
            from PIL import Image
            ocr_text = pytesseract.image_to_string(Image.open(path))
        except ImportError:
            log.warning("[ScreenContext] pytesseract not installed — OCR unavailable.")
        except Exception as e:
            log.warning(f"[ScreenContext] OCR failed: {e}")

        return path, ocr_text

    # ── Context Classification ───────────────────────────────────────────────

    def _classify_context(self, text: str) -> str:
        """Classify the screen context from OCR text."""
        tl = text.lower()
        if any(kw in tl for kw in ("traceback", "error:", "exception", "syntaxerror", "typeerror")):
            return "error terminal"
        if any(kw in tl for kw in ("def ", "class ", "import ", "function ", "const ", "var ")):
            return "code editor"
        if any(kw in tl for kw in ("http://", "https://", "www.", ".com", ".html")):
            return "browser"
        if any(kw in tl for kw in ("powershell", "cmd", "bash", "terminal", ">>>")):
            return "terminal"
        return "screen"

    # ── Error Extraction ────────────────────────────────────────────────────

    def _extract_error(self, text: str) -> str:
        """Pull traceback / error lines from OCR text."""
        lines   = text.splitlines()
        err_buf = []
        capture = False
        for line in lines:
            ll = line.lower()
            if any(kw in ll for kw in ("traceback", "error:", "exception", "warning:")):
                capture = True
            if capture:
                err_buf.append(line)
                if len(err_buf) > 30:
                    break
        return "\n".join(err_buf).strip()

    # ── LLM Analysis ────────────────────────────────────────────────────────

    def _llm_analyse(self, prompt: str, fallback_text: str) -> str:
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": ANALYSIS_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 400}
                },
                timeout=20
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "").strip()
        except Exception:
            pass

        # Offline fallback — return raw OCR
        if fallback_text.strip():
            return f"Ollama offline. Screen text: {fallback_text.strip()[:300]}"
        return "I cannot analyse the screen without Ollama running, sir."


# Module singleton
_instance: ScreenContextEngine | None = None


def get_screen_context() -> ScreenContextEngine:
    global _instance
    if _instance is None:
        _instance = ScreenContextEngine()
    return _instance
