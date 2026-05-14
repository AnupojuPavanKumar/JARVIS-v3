import requests
import time
import threading
import psutil

OLLAMA_URL = "http://localhost:11434/api"

class ModelOrchestrator:
    """
    Manages LLM traffic and VRAM usage.
    Ensures that multiple models aren't fighting for GPU resources.
    """
    def __init__(self, max_vram_gb=5.5):
        self.max_vram_gb = max_vram_gb
        self.lock = threading.Lock()
        self.active_model = None
        self._last_use = 0

    def get_vram_usage(self):
        """Return GPU VRAM usage percentage (0-100), or CPU RAM as last resort."""
        try:
            from core.system.gpu_probe import get_vram_used_pct
            pct = get_vram_used_pct()
            if pct is not None:
                return pct
        except Exception:
            pass
        return psutil.virtual_memory().percent  # CPU RAM fallback — not accurate for GPU

    def request_model(self, model_name: str, keep_alive: int = 300):
        """
        Request a model to be loaded. 
        If a different heavy model is loaded, we can signal Ollama to unload it.
        """
        with self.lock:
            if self.active_model == model_name:
                self._last_use = time.time()
                return True
            
            # If switching models, proactively tell Ollama to unload the current one
            if self.active_model:
                print(f"[Orchestrator] Switching: {self.active_model} -> {model_name}. Unloading old model...")
                self.unload_model(self.active_model)
                
            self.active_model = model_name
            self._last_use = time.time()
            return True

    def unload_model(self, model_name: str):
        """Unload a model from Ollama VRAM."""
        try:
            # Sending a request with keep_alive: 0 immediately unloads it
            requests.post(
                f"{OLLAMA_URL}/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=1
            )
        except Exception:
            pass

    def run_query(self, model_name: str, prompt: str, system: str = None, **kwargs):
        """Execute a query through the orchestrator's traffic control."""
        self.request_model(model_name)
        
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": kwargs.get("options", {})
        }
        if system: payload["system"] = system
        
        try:
            start = time.time()
            response = requests.post(f"{OLLAMA_URL}/generate", json=payload, timeout=120)
            print(f"[Orchestrator] Query finished in {time.time()-start:.2f}s")
            return response.json().get("response", "")
        except Exception as e:
            print(f"[Orchestrator] Query failed: {e}")
            return f"Error: {e}"

# Singleton
_orchestrator = ModelOrchestrator()
def get_orchestrator(): return _orchestrator
