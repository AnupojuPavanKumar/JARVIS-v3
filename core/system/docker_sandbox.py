# core/docker_sandbox.py — JARVIS Docker Execution Sandbox (Upgrade #6)
# ──────────────────────────────────────────────────────────────────────────────
# Routes agent-generated code execution into an isolated Docker container
# instead of running directly on the Windows host.
#
# Safety model:
#   - Code runs in python:3.11-slim container (no host filesystem access)
#   - 30s timeout per execution (configurable)
#   - Container auto-removed after each run (--rm)
#   - No network access by default (--network=none)
#   - Memory cap: 512MB per container
#   - Falls back to direct host execution if Docker is not available
#
# Usage (called from agent tools.py):
#   from core.system.docker_sandbox import get_sandbox
#   sb = get_sandbox()
#   result = sb.run_python(code)
#   result = sb.run_shell(command)
#   result = sb.is_available()  -> True/False
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from typing import Optional

log = logging.getLogger("DockerSandbox")

# ── Container configuration ────────────────────────────────────────────────────
PYTHON_IMAGE    = "python:3.11-slim"
SHELL_IMAGE     = "ubuntu:22.04"
TIMEOUT_S       = 30          # Max execution time per container
MEMORY_LIMIT    = "512m"      # RAM cap per container
CPU_LIMIT       = "1.0"       # CPU shares (1 core)
NETWORK_MODE    = "none"      # Fully air-gapped execution
SANDBOX_LABEL   = "jarvis-sandbox"   # Docker label for cleanup

# ── Packages pre-installed in the Python container ────────────────────────────
# Avoids re-installing common deps on every run
PYTHON_DEPS     = "requests flask fastapi uvicorn numpy pandas"


class DockerSandbox:
    """
    Isolated Docker execution environment for JARVIS agent code.

    Runs Python code and shell commands in a throwaway container.
    Never touches the host filesystem or OS.
    """

    def __init__(self):
        self._available: Optional[bool] = None  # None = unchecked
        self._image_ready               = False
        self._lock                      = threading.Lock()
        
        # Check availability in background
        from core.system.thread_manager import get_thread_manager
        get_thread_manager().run_in_background(
            self._check_docker,
            name="DockerSandbox-Init"
        )

    # ── Public API ──────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Returns True if Docker is installed and running."""
        if self._available is None:
            self._check_docker()
        return bool(self._available)

    def ensure_running(self) -> bool:
        """Attempts to start Docker Desktop if it's not running (Windows only)."""
        if self._check_docker_sync():
            self._available = True
            return True

        log.info("[Sandbox] Attempting to start Docker Desktop...")
        try:
            # Common installation paths for Docker Desktop
            paths = [
                r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
                r"C:\Program Files\Docker\Docker\resources\bin\docker.exe", # Try daemon directly if UI path fails
            ]
            started = False
            for p in paths:
                if os.path.exists(p):
                    if p.endswith(".exe"):
                        # Use start command to detached process
                        subprocess.Popen([p], creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
                    else:
                        subprocess.Popen([p, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
                    started = True
                    break
            
            if not started:
                log.warning("[Sandbox] Docker Desktop executable not found. Please start it manually.")
                return False

            # Don't block the whole system; wait in a loop but return True if we *started* the attempt
            # The background _check_docker thread will pick up the availability once it's up.
            return True
        except Exception as e:
            log.error(f"[Sandbox] Error starting Docker: {e}")
            return False

    def run_python(self, code: str,
                   timeout: int = TIMEOUT_S,
                   allow_network: bool = False) -> str:
        """
        Execute Python code in an isolated container.
        Returns stdout + stderr as a single string.
        """
        if not self.is_available():
            return "[SECURITY ERROR] Docker is not available. Host execution is DISABLED for safety. Please start Docker Desktop."

        try:
            # Write code to a temp file that gets bind-mounted read-only
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = f.name

            network = "bridge" if allow_network else NETWORK_MODE
            cmd = [
                "docker", "run",
                "--rm",
                "--label", SANDBOX_LABEL,
                f"--memory={MEMORY_LIMIT}",
                f"--cpus={CPU_LIMIT}",
                f"--network={network}",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-v", f"{tmp_path}:/app/code.py:ro",
                PYTHON_IMAGE,
                "python", "/app/code.py",
            ]
            result = self._run_container(cmd, timeout)
            return result
        except Exception as e:
            log.error(f"[Sandbox] run_python error: {e}")
            return f"Sandbox execution error: {e}"
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def run_shell(self, command: str,
                  timeout: int = TIMEOUT_S,
                  allow_network: bool = False) -> str:
        """
        Execute a shell command in an isolated Ubuntu container.
        """
        if not self.is_available():
            return "[SECURITY ERROR] Docker is not available. Host execution is DISABLED for safety. Please start Docker Desktop."

        try:
            network = "bridge" if allow_network else NETWORK_MODE
            cmd = [
                "docker", "run",
                "--rm",
                "--label", SANDBOX_LABEL,
                f"--memory={MEMORY_LIMIT}",
                f"--cpus={CPU_LIMIT}",
                f"--network={network}",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                SHELL_IMAGE,
                "/bin/bash", "-c", command,
            ]
            return self._run_container(cmd, timeout)
        except Exception as e:
            log.error(f"[Sandbox] run_shell error: {e}")
            return f"Sandbox execution error: {e}"

    def run_python_with_files(self, code: str, files: dict[str, str],
                               timeout: int = TIMEOUT_S) -> str:
        """
        Run Python code with additional files accessible in the container.
        files = {"filename.txt": "content", "data.csv": "csv content", ...}
        """
        if not self.is_available():
            return "[SECURITY ERROR] Docker is not available. Host execution is DISABLED for safety. Please start Docker Desktop."

        tmpdir = None
        try:
            tmpdir = tempfile.mkdtemp(prefix="jarvis_sandbox_")

            # Write main code
            code_path = os.path.join(tmpdir, "main.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)

            # Write supporting files
            for fname, content in files.items():
                fpath = os.path.join(tmpdir, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)

            cmd = [
                "docker", "run",
                "--rm",
                "--label", SANDBOX_LABEL,
                f"--memory={MEMORY_LIMIT}",
                f"--cpus={CPU_LIMIT}",
                f"--network={NETWORK_MODE}",
                "--read-only",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                "-v", f"{tmpdir}:/app:ro",
                "-w", "/app",
                PYTHON_IMAGE,
                "python", "main.py",
            ]
            return self._run_container(cmd, timeout)
        except Exception as e:
            return f"Sandbox error: {e}"
        finally:
            if tmpdir:
                import shutil
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass

    def cleanup_stale_containers(self) -> str:
        """Kill any lingering JARVIS sandbox containers (safety cleanup)."""
        if not self.is_available():
            return "Docker not available."
        try:
            result = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"label={SANDBOX_LABEL}"],
                capture_output=True, text=True, timeout=10
            )
            container_ids = result.stdout.strip().split()
            if container_ids:
                subprocess.run(
                    ["docker", "kill"] + container_ids,
                    capture_output=True, timeout=10
                )
                return f"Killed {len(container_ids)} stale sandbox container(s)."
            return "No stale sandbox containers found."
        except Exception as e:
            return f"Cleanup error: {e}"

    def status(self) -> str:
        """Return sandbox status string."""
        if self.is_available():
            return (
                f"Docker Sandbox: ACTIVE\n"
                f"  Image: {PYTHON_IMAGE}\n"
                f"  Memory cap: {MEMORY_LIMIT}\n"
                f"  Network: {NETWORK_MODE} (air-gapped)\n"
                f"  Timeout: {TIMEOUT_S}s\n"
                f"  All agent code runs isolated, sir."
            )
        return (
            "Docker Sandbox: INACTIVE (Docker not installed or not running)\n"
            "  [SECURITY WARNING] Host execution fallback is DISABLED.\n"
            "  Please install/start Docker Desktop to enable agent capabilities."
        )

    # ── Internal ────────────────────────────────────────────────────────────────

    def _check_docker(self):
        """Check if Docker daemon is running."""
        if self._check_docker_sync():
            self._available = True
            log.info("[Sandbox] Docker available — sandboxed execution enabled.")
            # Pull image in background (non-blocking)
            from core.system.thread_manager import get_thread_manager
            get_thread_manager().run_in_background(
                self._ensure_image,
                name="DockerSandbox-Pull"
            )
        else:
            self._available = False
            log.info("[Sandbox] Docker not available.")

    def _check_docker_sync(self) -> bool:
        """Synchronous check for docker daemon."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _ensure_image(self):
        """Pull the Python image if not already cached."""
        try:
            result = subprocess.run(
                ["docker", "images", "-q", PYTHON_IMAGE],
                capture_output=True, text=True, timeout=10
            )
            if not result.stdout.strip():
                log.info(f"[Sandbox] Pulling {PYTHON_IMAGE}...")
                subprocess.run(
                    ["docker", "pull", PYTHON_IMAGE],
                    capture_output=True, timeout=120
                )
                log.info(f"[Sandbox] Image ready: {PYTHON_IMAGE}")
            self._image_ready = True
        except Exception as e:
            log.warning(f"[Sandbox] Image pull error: {e}")

    def _run_container(self, cmd: list[str], timeout: int) -> str:
        """Run a Docker container command and return combined stdout/stderr."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,   # +5s grace for container startup
                encoding="utf-8",
                errors="replace",
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                # Filter out Docker noise
                stderr = "\n".join(
                    line for line in result.stderr.splitlines()
                    if not line.startswith("Unable to find image")
                    and "Pulling from" not in line
                )
                if stderr.strip():
                    output += f"\n[stderr]\n{stderr}"

            if result.returncode != 0 and not output.strip():
                output = f"[Container exited with code {result.returncode}]"

            return output.strip() or "[No output]"
        except subprocess.TimeoutExpired:
            return f"[TIMEOUT] Execution exceeded {timeout}s limit. Container killed."
        except Exception as e:
            return f"[Container error] {e}"


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: Optional[DockerSandbox] = None


def get_sandbox() -> DockerSandbox:
    global _instance
    if _instance is None:
        _instance = DockerSandbox()
    return _instance
