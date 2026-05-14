# core/system/hardware_sentinel.py — JARVIS Central Hardware Telemetry
import subprocess
import time
import threading
import requests
import json
import psutil
from typing import Optional, Dict, Any

class HardwareSentinel:
    """
    Unified Hardware Monitoring for JARVIS-v3.
    Single source of truth for CPU, RAM, VRAM, and Process health.
    """

    # Processes that can be killed to free VRAM when resources are critical.
    # These are non-essential background processes safe to terminate.
    _DRAINABLE_PROCESSES = [
        "ollama_llama_server.exe",
        "ollama.exe",
        "python.exe",       # spawned subprocesses, not main process
        "docker.exe",
        "node.exe",
    ]

    def __init__(self, speech_engine=None):
        self.speech_engine = speech_engine
        self.running = False
        self._stop_evt = threading.Event()  # always initialized

        # Thresholds
        self.vram_hard_limit_gb = 5.2
        self.total_vram_gb = 6.0
        self.vram_threshold = self.vram_hard_limit_gb / self.total_vram_gb

        self.interval = 4.0
        self._loop_count = 0
        self._hibernate_triggered = False

        # State
        self.stats = {
            "cpu": 0.0,
            "ram": 0.0,
            "vram_pct": 0.0,
            "gpu_util": 0.0,
            "vram_mb": "0/0",
            "battery": None,
            "ollama_online": False,
            "docker_online": False,
            "threads": 0
        }
        self._lock = threading.Lock()

    def start(self):
        if not self.running:
            self.running = True
            self._stop_evt.clear()
            threading.Thread(target=self._monitor_loop, daemon=True, name="TelemetryThread").start()
            print("[HardwareSentinel] Unified telemetry active.")

    def stop(self):
        self.running = False
        self._stop_evt.set()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return self.stats.copy()

    def _monitor_loop(self):
        # Initialize COM for this thread in case requests/proxy logic touches it
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        while self.running:
            try:
                self._loop_count += 1
                new_stats = {}
                # 1. CPU & RAM (Cheap)
                new_stats["cpu"] = psutil.cpu_percent()
                new_stats["ram"] = psutil.virtual_memory().percent
                
                # 2. Battery (Cheap)
                bat = psutil.sensors_battery()
                if bat:
                    new_stats["battery"] = {
                        "percent": bat.percent,
                        "plugged": bat.power_plugged
                    }
                
                # 3. VRAM & GPU (Moderate)
                vram_usage = self._update_gpu_stats(new_stats)
                
                # 4. Service health (Expensive - Run every 3rd loop ~12s)
                if self._loop_count % 3 == 0:
                    new_stats["ollama_online"] = self._check_ollama()
                    new_stats["docker_online"] = self._check_docker()
                
                # 5. Thread Sanity Check
                thread_count = threading.active_count()
                new_stats["threads"] = thread_count
                if thread_count > 100:
                    print(f"[HardwareSentinel WARN] High thread count detected: {thread_count} active threads. Possible thread leak.")
                    if self.speech_engine and self._loop_count % 15 == 0:
                        self.speech_engine.speak(f"Alert. Thread leak detected. {thread_count} active threads.")

                with self._lock:
                    self.stats.update(new_stats)
                
                # 5. Logic: Alert if VRAM critical
                if vram_usage and vram_usage > self.vram_threshold and not self._hibernate_triggered:
                    self._trigger_resource_hibernate(vram_usage)
                elif vram_usage and vram_usage < 0.75 and self._hibernate_triggered:
                    self._hibernate_triggered = False
                    print("[HardwareSentinel] VRAM stabilized.")

            except Exception as e:
                print(f"[HardwareSentinel] Loop error: {e}")

            try:
                self._stop_evt.wait(timeout=self.interval)
                if not self.running:
                    break
            except Exception:
                break

    def _get_vram_usage(self) -> Optional[float]:
        """Helper to get just the VRAM usage ratio for capability tests."""
        return self._update_gpu_stats({})

    def _update_gpu_stats(self, target_dict) -> Optional[float]:
        from core.system.gpu_probe import get_gpu_stats
        stats = get_gpu_stats()
        if stats:
            target_dict["gpu_util"] = stats["util_pct"]
            target_dict["vram_pct"] = stats["used_pct"]
            target_dict["vram_mb"]  = f"{stats['used_mb']:.0f}/{stats['total_mb']:.0f}MB"
            return stats["used_pct"] / 100.0   # Return fraction for threshold comparison
        return None

    def _check_ollama(self) -> bool:
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                return s.connect_ex(("127.0.0.1", 11434)) == 0
        except Exception:
            return False

    def _check_docker(self) -> bool:
        try:
            res = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
            return res.returncode == 0
        except Exception as exc:
            import logging; logging.getLogger("HardwareSentinel").debug(f"Docker check failed: {exc}")
            return False

    def _trigger_resource_hibernate(self, usage: float):
        self._hibernate_triggered = True
        pct = int(usage * 100)
        msg = f"Alert. VRAM at {pct} percent. Hibernating non-essential engines."
        print(f"\n[HardwareSentinel WARN] {msg}")
        
        if self.speech_engine:
            self.speech_engine.speak(msg)
        
        self._offload_ollama()

    def _offload_ollama(self):
        """Ask Ollama to unload all currently loaded models."""
        try:
            import requests as _requests
            resp = _requests.get("http://localhost:11434/api/tags", timeout=2)
            if resp.ok:
                models = [m["name"] for m in resp.json().get("models", [])]
                for m in models:
                    try:
                        _requests.post("http://localhost:11434/api/generate",
                                       json={"model": m, "keep_alive": 0}, timeout=2)
                    except Exception:
                        pass
        except Exception as exc:
            import logging; logging.getLogger("HardwareSentinel").debug(f"Ollama offload failed: {exc}")

def get_hardware_sentinel() -> Optional[HardwareSentinel]:
    from core.system.service_registry import get_service_registry
    return get_service_registry().get("hardware_sentinel")
