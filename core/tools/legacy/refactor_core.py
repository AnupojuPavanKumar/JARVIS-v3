import os
import glob
import re
import shutil

ROOT_DIR = "D:/JARVIS-v3"
CORE_DIR = os.path.join(ROOT_DIR, "core")

# Categories for the new structure
CATEGORIES = {
    "engines": [
        "automation_engine.py", "briefing_engine.py", "context_engine.py",
        "doc_rag_engine.py", "embedding_engine.py", "persona_engine.py",
        "proactive_engine.py", "speech_engine.py", "task_engine.py",
        "vision_engine.py", "vlm_engine.py", "voice_engine.py",
        "whisper_engine.py", "workflow_engine.py", "ai_engine.py", "intent_engine.py"
    ],
    "providers": [
        "ollama_manager.py", "model_router.py", "model_orchestrator.py", "ntfy_launcher.py"
    ],
    "memory": [
        "command_memory.py", "conversation_history.py", "episodic_memory.py",
        "memory_brain.py", "pattern_memory.py", "project_memory.py"
    ],
    "system": [
        "bootstrapper.py", "db.py", "docker_sandbox.py", "event_bus.py",
        "events.py", "hardware_sentinel.py", "logger.py", "security.py",
        "system_monitor.py", "system_watcher.py", "workspace_manager.py",
        "service_registry.py", "tool_registry.py", "plugin_manager.py", "self_updater.py"
    ],
    "agent": [
        "agent.py", "ghost_debugger.py", "intent_classifier.py", "jarvis_brain.py",
        "planner.py", "project_runtime.py", "research_agent.py", "runtime_executor.py",
        "scheduler.py", "self_learning.py", "task_orchestrator.py", "task_queue.py",
        "web_research.py", "work_verifier.py", "mode_manager.py", "llm_fallback.py",
        "llm_stream.py"
    ],
    "ui": [
        "screen_context.py", "screen_reader.py", "voice_fx.py", "voice_interruption.py",
        "wake_word.py"
    ],
    "api": [
        "api_server.py", "app_scanner.py", "auth_bridge.py", "auto_pusher.py",
        "browser_automation.py", "camera_manager.py", "skill_factory.py", "skill_registry.py"
    ]
}

def main():
    print("Starting refactoring...")
    
    # 1. Create directories
    for cat in CATEGORIES:
        os.makedirs(os.path.join(CORE_DIR, cat), exist_ok=True)
        init_file = os.path.join(CORE_DIR, cat, "__init__.py")
        if not os.path.exists(init_file):
            open(init_file, 'w').close()
            
    # 2. Map old import paths to new import paths
    # e.g., 'core.engines.task_engine' -> "core.engines.task_engine"
    import_map = {}
    for cat, files in CATEGORIES.items():
        for f in files:
            module_name = f.replace(".py", "")
            old_import = f"core.{module_name}"
            new_import = f"core.{cat}.{module_name}"
            import_map[module_name] = new_import

    # 3. Move files
    for cat, files in CATEGORIES.items():
        for f in files:
            old_path = os.path.join(CORE_DIR, f)
            new_path = os.path.join(CORE_DIR, cat, f)
            if os.path.exists(old_path):
                shutil.move(old_path, new_path)
                print(f"Moved {f} -> {cat}/")

    # 4. Update imports in all python files
    all_py_files = glob.glob(os.path.join(ROOT_DIR, "**/*.py"), recursive=True)
    all_py_files += glob.glob(os.path.join(ROOT_DIR, "**/*.vbs"), recursive=True) # just in case
    all_py_files += glob.glob(os.path.join(ROOT_DIR, "main.py"))
    
    # We want to replace `from core.module import ...` with `from core.cat.module import ...`
    # and `import core.module` with `import core.cat.module`
    
    for fpath in set(all_py_files):
        if not os.path.isfile(fpath): continue
        if "venv" in fpath or "pycache" in fpath: continue
        
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        original_content = content
        
        for module, new_path in import_map.items():
            # regex for `from core.module import X`
            content = re.sub(rf"from\s+core\.{module}\s+import", f"from {new_path} import", content)
            # regex for `import core.module`
            content = re.sub(rf"import\s+core\.{module}\b", f"import {new_path}", content)
            # handle dynamic imports like import_module("core.module")
            content = re.sub(rf"['\"]core\.{module}['\"]", f"'{new_path}'", content)

        if content != original_content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Updated imports in {os.path.relpath(fpath, ROOT_DIR)}")

if __name__ == "__main__":
    main()
