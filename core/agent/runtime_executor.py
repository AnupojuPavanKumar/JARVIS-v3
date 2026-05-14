from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import subprocess
import sys


@dataclass
class RuntimeResult:
    success: bool
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class RuntimeExecutor:
    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def py_compile(self, paths: Sequence[str | Path], cwd: str | Path | None = None) -> RuntimeResult:
        command = [sys.executable, "-m", "py_compile", *[str(Path(path)) for path in paths]]
        return self._run(command, cwd=cwd)

    def run_python(
        self,
        script_path: str | Path,
        args: Sequence[str] | None = None,
        cwd: str | Path | None = None,
        timeout: int | None = None,
    ) -> RuntimeResult:
        command = [sys.executable, str(Path(script_path))]
        if args:
            command.extend(args)
        return self._run(command, cwd=cwd, timeout=timeout)

    def run_inline(
        self,
        code: str,
        cwd: str | Path | None = None,
        timeout: int | None = None,
    ) -> RuntimeResult:
        command = [sys.executable, "-c", code]
        return self._run(command, cwd=cwd, timeout=timeout)

    def _run(
        self,
        command: Sequence[str],
        cwd: str | Path | None = None,
        timeout: int | None = None,
    ) -> RuntimeResult:
        try:
            completed = subprocess.run(
                list(command),
                cwd=str(Path(cwd).resolve()) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
            )
            return RuntimeResult(
                success=completed.returncode == 0,
                command=list(command),
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        except subprocess.TimeoutExpired as exc:
            return RuntimeResult(
                success=False,
                command=list(command),
                returncode=124,
                stdout=(exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
                stderr=f"Timed out after {timeout or self.timeout} seconds.",
            )
        except OSError as exc:
            return RuntimeResult(
                success=False,
                command=list(command),
                returncode=1,
                stdout="",
                stderr=str(exc),
            )
