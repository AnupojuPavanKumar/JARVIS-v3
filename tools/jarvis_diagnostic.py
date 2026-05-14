from __future__ import annotations

import asyncio
import json
import importlib
import os
import subprocess
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_version_text(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    parts = value.strip().split(".")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def repo_venv_entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    venv_names = [name.strip() for name in os.environ.get("JARVIS_VENV_NAMES", "venv311,venv").split(",") if name.strip()]
    for name in venv_names:
        venv_dir = ROOT / name
        cfg = parse_pyvenv_cfg(venv_dir / "pyvenv.cfg")
        entries.append(
            {
                "venv": name,
                "venv_dir": venv_dir,
                "site_packages": venv_dir / "Lib" / "site-packages",
                "launcher": venv_dir / "Scripts" / "python.exe",
                "version": cfg.get("version"),
                "version_tuple": parse_version_text(cfg.get("version")),
                "config": cfg,
            }
        )
    return entries


def select_bootstrap_site_packages() -> tuple[Path | None, str | None]:
    active_site_packages = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages"
    if active_site_packages.exists() and ROOT in active_site_packages.parents:
        return active_site_packages, active_site_packages.parent.parent.name

    requested_venv = os.environ.get("JARVIS_BOOTSTRAP_VENV", "").strip()
    entries = repo_venv_entries()
    if requested_venv:
        for entry in entries:
            site_packages = entry["site_packages"]
            if entry["venv"] == requested_venv and isinstance(site_packages, Path) and site_packages.exists():
                return site_packages, requested_venv

    current_version = sys.version_info[:2]
    for entry in entries:
        site_packages = entry["site_packages"]
        if (
            isinstance(site_packages, Path)
            and site_packages.exists()
            and entry.get("version_tuple") == current_version
        ):
            return site_packages, str(entry["venv"])

    return None, None


def bootstrap_paths() -> tuple[list[str], str | None]:
    added = []
    preferred_site_packages, selected_venv = select_bootstrap_site_packages()

    candidates = [ROOT]
    if preferred_site_packages is not None:
        candidates.insert(0, preferred_site_packages)

    for candidate in reversed(candidates):
        path_str = str(candidate)
        if candidate.exists() and path_str not in sys.path:
            sys.path.insert(0, path_str)
            added.append(path_str)
    return added, selected_venv


def preferred_repo_runtime() -> tuple[Path, str, str] | None:
    for entry in repo_venv_entries():
        venv_name = str(entry["venv"])
        launcher = entry["launcher"]
        if isinstance(launcher, Path):
            probe = probe_python_runtime(launcher)
            if probe.get("launch_ok"):
                return launcher, venv_name, f"{venv_name} launcher"

        cfg = entry["config"]
        base_executable = cfg.get("executable")
        if base_executable:
            base_path = Path(base_executable)
            probe = probe_python_runtime(base_path)
            if probe.get("launch_ok"):
                return base_path, venv_name, f"{venv_name} base"
    return None


def reexec_into_repo_runtime_if_needed():
    current_executable = Path(sys.executable).resolve()
    if ROOT in current_executable.parents:
        return
    if os.environ.get("JARVIS_DIAGNOSTIC_REEXECED") == "1":
        return

    preferred = preferred_repo_runtime()
    if not preferred:
        return

    runtime_path, venv_name, source = preferred
    env = os.environ.copy()
    env["JARVIS_DIAGNOSTIC_REEXECED"] = "1"
    env["JARVIS_BOOTSTRAP_VENV"] = venv_name
    env["JARVIS_PYTHON_SOURCE"] = source
    completed = subprocess.run(
        [str(runtime_path), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=str(ROOT),
        env=env,
    )
    raise SystemExit(completed.returncode)


def run_check(name, func, *, critical=False):
    try:
        value = func()
        return {
            "name": name,
            "ok": True,
            "critical": critical,
            "value": make_json_safe(value),
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "critical": critical,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=3),
        }


def make_json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): make_json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    return repr(value)


def import_symbol(module_name, symbol_name=None):
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name) if symbol_name else module


def parse_pyvenv_cfg(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def probe_python_runtime(executable: Path) -> dict[str, object]:
    info = {
        "path": str(executable),
        "exists": executable.exists(),
    }

    if not executable.exists():
        return info

    try:
        proc = subprocess.run(
            [str(executable), "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        info["launch_ok"] = proc.returncode == 0
        info["returncode"] = proc.returncode

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        if stdout:
            info["stdout"] = stdout.splitlines()[:2]
        if stderr:
            info["stderr"] = stderr.splitlines()[:2]
    except Exception as exc:
        info["launch_ok"] = False
        info["error"] = str(exc)

    return info


def inspect_python_launchers():
    results = []
    for entry in repo_venv_entries():
        venv_name = str(entry["venv"])
        venv_dir = entry["venv_dir"]
        cfg = entry["config"]
        command = cfg.get("command", "")
        expected_target = str(venv_dir).lower()

        entry = {
            "venv": venv_name,
            "venv_dir": str(venv_dir),
            "launcher": probe_python_runtime(entry["launcher"]),
            "config": {
                "home": cfg.get("home"),
                "executable": cfg.get("executable"),
                "version": cfg.get("version"),
                "command": command,
                "relocated_command": bool(command) and expected_target not in command.lower(),
            },
        }

        base_executable = cfg.get("executable")
        if base_executable:
            entry["base_runtime"] = probe_python_runtime(Path(base_executable))

        results.append(entry)

    return results


@contextmanager
def preserve_runtime_files():
    targets = [
        ROOT / "memory" / "conversations.json",
        ROOT / "memory" / "actions.json",
        ROOT / "memory" / "activity.log",
    ]
    snapshots = {}
    for path in targets:
        if path.exists():
            snapshots[path] = path.read_bytes()
        else:
            snapshots[path] = None

    try:
        yield
    finally:
        for path, content in snapshots.items():
            if content is None:
                if path.exists():
                    path.unlink()
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def main():
    os.chdir(ROOT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    reexec_into_repo_runtime_if_needed()

    added_paths, selected_venv = bootstrap_paths()
    results = []

    results.append(
        {
            "name": "environment",
            "ok": True,
            "critical": False,
            "value": {
                "python": sys.version,
                "executable": sys.executable,
                "cwd": str(Path.cwd()),
                "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
                "bootstrap_venv": selected_venv,
                "python_source": os.environ.get("JARVIS_PYTHON_SOURCE"),
                "added_paths": added_paths,
            },
        }
    )

    def init_memory():
        MemoryBrain = import_symbol('core.memory.memory_brain', "MemoryBrain")
        brain = MemoryBrain()
        return {
            "has_db": brain.db is not None,
            "can_search": len(brain.search_graph("test")) >= 0,
        }

    def init_identity():
        IdentityManager = import_symbol("identity.identity_manager", "IdentityManager")
        identity = IdentityManager()
        return {
            "identity": identity.identity,
            "user_name": identity.user_name,
        }

    def init_auth():
        AuthManager = import_symbol("auth.auth_manager", "AuthManager")
        auth = AuthManager()
        return {
            "device_known": auth.is_known_device(),
            "should_authenticate": auth.should_authenticate(),
        }

    def init_vision():
        VisionEngine = import_symbol('core.engines.vision_engine', "VisionEngine")
        vision = VisionEngine()
        return {
            "camera_index_preference": vision.CAM_INDEX,
            "cascade_loaded": bool(getattr(vision.cascade, "empty", lambda: True)() is False),
        }

    def init_command_engine():
        CommandEngine = import_symbol("command_engine", "CommandEngine")
        engine = CommandEngine(identity="guest")
        return {
            "identity": engine.identity,
            "has_app_scanner": hasattr(engine, 'app_scanner'),
            "who_are_you": engine.execute("who are you"),
        }

    def init_brain():
        JarvisBrain = import_symbol('core.agent.jarvis_brain', "JarvisBrain")
        brain = JarvisBrain("guest")
        TaskEngine = import_symbol('core.engines.task_engine', "TaskEngine")
        task_engine = TaskEngine()
        IntentEngine = import_symbol('core.engines.intent_engine', "IntentEngine")
        intent_engine = IntentEngine()
        try:
            return {
                "brain_identity": brain.identity,
                "task_split": task_engine.parse_task("open chrome and then search youtube for synthwave"),
                "intent_good_night": intent_engine.detect_intent("good night"),
                "brain_reply": brain.process("who are you"),
            }
        finally:
            if hasattr(brain, '_task_queue') and brain._task_queue:
                brain._task_queue.stop_worker()
            elif hasattr(brain, 'task_queue') and brain.task_queue:
                if hasattr(brain.task_queue, 'stop_worker'):
                    brain.task_queue.stop_worker()
                elif hasattr(brain.task_queue, 'stop'):
                    brain.task_queue.stop()

    def preview_autonomy():
        TaskOrchestrator = import_symbol('core.agent.task_orchestrator', "TaskOrchestrator")
        orchestrator = TaskOrchestrator("guest")
        website = orchestrator.create_plan("build a portfolio website for Maya").to_dict()
        college = orchestrator.create_plan("prepare a college report on databases").to_dict()
        workflow = orchestrator.create_plan("create an automation workflow for assignment tracking").to_dict()
        browser_workflow = orchestrator.create_plan("browse https://example.com and follow more information").to_dict()
        python_tool = orchestrator.create_plan("build a python automation script for daily notes").to_dict()
        python_project = orchestrator.create_plan("repair current project").to_dict()
        python_repair = orchestrator.create_plan("repair ./broken_sample.py").to_dict()
        return {
            "website": website,
            "browser": orchestrator.create_plan("research https://example.com").to_dict(),
            "browser_workflow": browser_workflow,
            "python_tool": python_tool,
            "python_project_repair": python_project,
            "python_repair": python_repair,
            "college": college,
            "workflow": workflow,
            "status_query": orchestrator.is_status_query("show me recent autonomous jobs"),
            "verify_tools": [
                website["steps"][0].get("verify_tool"),
                orchestrator.create_plan("research https://example.com").to_dict()["steps"][0].get("verify_tool"),
                browser_workflow["steps"][0].get("verify_tool"),
                python_tool["steps"][0].get("verify_tool"),
                python_project["steps"][0].get("verify_tool"),
                python_repair["steps"][0].get("verify_tool"),
                college["steps"][0].get("verify_tool"),
                workflow["steps"][0].get("verify_tool"),
            ],
        }

    def browser_capabilities():
        BrowserAutomation = import_symbol('core.api.browser_automation', "BrowserAutomation")
        browser = BrowserAutomation()
        return {
            "playwright_available": browser.playwright_available(),
            "sample_url_parse": browser.extract_first_url("research https://example.com"),
        }

    def check_ollama():
        OllamaManager = import_symbol('core.providers.ollama_manager', "OllamaManager")
        mgr = OllamaManager()
        return {
            "running": mgr.is_running(),
        }

    def auth_window_smoke():
        from PyQt6.QtWidgets import QApplication

        AuthWindow = import_symbol("ui.auth_window", "AuthWindow")
        IdentityManager = import_symbol("identity.identity_manager", "IdentityManager")

        app = QApplication.instance() or QApplication([])
        win = AuthWindow(IdentityManager(), auto_start=False)
        info = {
            "title": win.windowTitle(),
            "status": win.status_lbl.text(),
            "pin_button": win.pin_btn.text(),
        }
        win.close()
        if QApplication.instance() is app:
            app.quit()
        return info

    with preserve_runtime_files():
        results.append(run_check("import.main", lambda: import_symbol("main"), critical=True))
        results.append(run_check("import.command_engine", lambda: import_symbol("command_engine"), critical=True))
        results.append(run_check("import.jarvis_brain", lambda: import_symbol('core.agent.jarvis_brain'), critical=True))
        results.append(run_check("import.main_ui", lambda: import_symbol("ui.main_ui"), critical=True))
        results.append(run_check("import.auth_window", lambda: import_symbol("ui.auth_window"), critical=True))
        results.append(run_check("import.voice_engine", lambda: import_symbol('core.engines.voice_engine'), critical=True))
        results.append(run_check("import.speech_engine", lambda: import_symbol('core.engines.speech_engine'), critical=True))
        results.append(run_check("inspect.python_launchers", inspect_python_launchers, critical=False))
        results.append(run_check("init.memory", init_memory, critical=True))
        results.append(run_check("init.identity", init_identity, critical=True))
        results.append(run_check("init.auth", init_auth, critical=True))
        results.append(run_check("init.vision", init_vision, critical=True))
        results.append(run_check("init.command_engine_guest", init_command_engine, critical=True))
        results.append(run_check("init.jarvis_brain_guest", init_brain, critical=True))
        results.append(run_check("preview.autonomy", preview_autonomy, critical=True))
        results.append(run_check("browser.capabilities", browser_capabilities, critical=True))
        results.append(run_check("check.ollama", check_ollama, critical=False))
        results.append(run_check("smoke.auth_window_offscreen", auth_window_smoke, critical=False))

    passed = all(item["ok"] or not item["critical"] for item in results)
    summary = {
        "ok": passed,
        "critical_failures": [item["name"] for item in results if item.get("critical") and not item["ok"]],
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
