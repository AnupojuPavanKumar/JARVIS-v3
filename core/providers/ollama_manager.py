# core/ollama_manager.py  —  FIXED v4
# Robust path detection and centralized management

import subprocess
import requests
import time
import threading
import os
import shutil
import json
from typing import Optional, List, Any

OLLAMA_HEALTH  = "http://localhost:11434/api/tags"
OLLAMA_MODEL   = "llama3.2:3b"          # Conversational fallback model (2GB, fast)
AGENT_MODEL    = "qwen2.5-coder:7b"     # Primary agent model — code-tuned, fits RTX 4050 6GB
EMBED_MODEL    = "nomic-embed-text"     # Lightweight contextual Vector RAG model

_global_started = False
_global_lock    = threading.Lock()


class OllamaManager:

    def __init__(self):
        self._ready = False
        self._exe_path = self._find_ollama_exe()

    def _find_ollama_exe(self) -> str:
        """Find the ollama executable in PATH or common Windows locations."""
        # 1. Check PATH
        path_exe = shutil.which("ollama")
        if path_exe:
            return path_exe
        
        # 2. Check common Windows locations
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        common_paths = [
            os.path.join(local_app_data, r"Ollama\ollama.exe"),
            os.path.join(local_app_data, r"Programs\Ollama\ollama.exe"),
            r"C:\Program Files\Ollama\ollama.exe",
        ]
        
        for p in common_paths:
            if os.path.exists(p):
                return p
        
        return "ollama"  # Fallback to just "ollama" and hope for the best

    def is_running(self) -> bool:
        """Check if Ollama is running using a socket probe to avoid Winsock crashes."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                return s.connect_ex(("127.0.0.1", 11434)) == 0
        except Exception:
            return False

    def start_server(self):
        try:
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW

            subprocess.Popen(
                [self._exe_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            print(f"[Ollama] Launched: {self._exe_path}")
        except Exception as e:
            print(f"[Ollama] Failed to start: {e}")

    def ensure_model(self):
        """
        Verify models are downloaded (pull if missing).
        """
        try:
            r = requests.get(OLLAMA_HEALTH, timeout=5)
            available_models = [m.get("name", "") for m in r.json().get("models", [])]

            ready, missing = [], []
            for model_name in (OLLAMA_MODEL, AGENT_MODEL, EMBED_MODEL):
                if not any(model_name in m for m in available_models):
                    missing.append(model_name)
                else:
                    ready.append(model_name.split(":")[0])
            
            if ready:
                print(f"[Ollama] Models ready: {', '.join(ready)}")
            
            for model_name in missing:
                print(f"[Ollama] Pulling {model_name}...")
                subprocess.run([self._exe_path, "pull", model_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"[Ollama] {model_name} downloaded.")

        except Exception as e:
            print(f"[Ollama] Model check failed: {e}")

    def switch_model(self, target_model: str, keep_alive: str = "5m"):
        """
        Transition to a new model by proactively unloading all others.
        Ensures the target model has the full GPU VRAM available.
        """
        if not self.is_running():
            return

        try:
            # Query currently loaded models
            r = requests.get("http://localhost:11434/api/ps", timeout=2)
            if r.status_code == 200:
                loaded = r.json().get("models", [])
                
                # Check if target is already the only one loaded
                if len(loaded) == 1 and loaded[0].get("name") == target_model:
                    return

                # Evict everything ELSE
                for m in loaded:
                    name = m.get("name")
                    if name != target_model:
                        requests.post(
                            "http://localhost:11434/api/generate",
                            json={"model": name, "keep_alive": 0},
                            timeout=5,
                        )
                        print(f"[Ollama] Evicted {name} to make room for {target_model}.")

            # Warm up target model (load into VRAM)
            requests.post(
                "http://localhost:11434/api/generate",
                json={"model": target_model, "prompt": "", "keep_alive": keep_alive},
                timeout=30,
            )
            print(f"[Ollama] Switched to {target_model}.")
        except Exception as e:
            print(f"[Ollama] Model switch error: {e}")

    def unload_all(self):
        """Force-unload every model from VRAM immediately."""
        self.evict_models()

    def evict_models(self, keep: Optional[list[str]] = None):
        """
        Query Ollama for all loaded models and force-evict them to free VRAM.
        If 'keep' is provided, those models will not be evicted.
        """
        try:
            # Query currently loaded models
            r = requests.get("http://localhost:11434/api/ps", timeout=2)
            if r.status_code != 200:
                return
            
            loaded = r.json().get("models", [])
            for m in loaded:
                name = m.get("name")
                if keep and name in keep:
                    continue
                
                # Evict by sending a request with keep_alive=0
                requests.post(
                    "http://localhost:11434/api/generate",
                    json={"model": name, "keep_alive": 0},
                    timeout=5,
                )
                print(f"[Ollama] Evicted {name} from VRAM.")
        except Exception:
            # Silent fail for eviction — never block the main loop
            pass

    def get_vram_usage_pct(self) -> float | None:
        """Return current VRAM usage 0-100%, or None if no GPU / pynvml missing."""
        from core.system.gpu_probe import get_vram_used_pct
        return get_vram_used_pct()

    def warn_if_vram_critical(self, threshold_pct: float = 70.0):
        """Print a warning and flush VRAM if usage is above threshold."""
        pct = self.get_vram_usage_pct()
        if pct is not None and pct > threshold_pct:
            print(
                f"[Ollama] ⚠  VRAM CRITICAL: {pct:.1f}% used "
                f"(>{threshold_pct}%). Forcing VRAM recovery..."
            )
            self.evict_models()


    def generate(self, model: str, prompt: str, stream: bool = False, options: dict = None, timeout: int = 120) -> Any:
        """Central method for /api/generate calls."""
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": options or {}
        }
        
        if stream:
            return self._stream_request(url, payload, "response", timeout)
        
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            print(f"[Ollama] Generate error: {e}")
            return None

    def chat(self, model: str, messages: list[dict], stream: bool = False, options: dict = None, timeout: int = 120) -> Any:
        """Central method for /api/chat calls."""
        url = "http://localhost:11434/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": options or {}
        }
        
        if stream:
            return self._stream_request(url, payload, "message", timeout)
        
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except Exception as e:
            print(f"[Ollama] Chat error: {e}")
            return None

    def _stream_request(self, url: str, payload: dict, key: str, timeout: int):
        """Helper for streaming requests."""
        try:
            with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        if key == "message":
                            token = chunk.get("message", {}).get("content", "")
                        else:
                            token = chunk.get(key, "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
        except Exception as e:
            print(f"[Ollama] Stream error: {e}")

    def ensure_running(self, on_ready=None, on_fail=None) -> bool:
        """
        Starts Ollama exactly once across the entire process lifetime.
        Always call from a background thread.
        """
        global _global_started
        with _global_lock:
            if _global_started:
                self._ready = True
                if on_ready: on_ready()
                return True
            _global_started = True

        if self.is_running():
            self._ready = True
            print("[Ollama] Server already running.")
            self._post_start_warmup()
            if on_ready: on_ready()
            return True

        print("[Ollama] Starting server...")
        self.start_server()

        # Poll every 0.5s for up to 20s (faster than the old 1s/15s)
        for attempt in range(40):
            time.sleep(0.5)
            if self.is_running():
                self._ready = True
                print(f"[Ollama] Online after {(attempt + 1) * 0.5:.1f}s.")
                self._post_start_warmup()
                if on_ready: on_ready()
                return True

        print("[Ollama] Failed to start after 20s.")
        if on_fail: on_fail()
        return False

    def _post_start_warmup(self):
        """Verify models exist and pre-warm the agent model into VRAM."""
        try:
            self.ensure_model()
        except Exception as e:
            print(f"[Ollama] Post-start warmup error: {e}")

    def ensure_running_async(self, on_ready=None, on_fail=None):
        t = threading.Thread(target=self.ensure_running,
                             kwargs={"on_ready": on_ready, "on_fail": on_fail},
                             daemon=True)
        t.start()
        return t

    @property
    def ready(self) -> bool:
        return self._ready

_instance = None

def get_ollama_manager() -> OllamaManager:
    global _instance
    if _instance is None:
        _instance = OllamaManager()
    return _instance
