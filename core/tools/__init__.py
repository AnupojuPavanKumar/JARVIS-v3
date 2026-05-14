# core/tools/__init__.py  —  JARVIS TOOL REGISTRY (LAZY V4 UNIFIED)
# ──────────────────────────────────────────────────────────────────────────────
# Single dispatch point for all agent tools.
# Tools are initialized LAZILY to prevent module-import hangs and reduce VRAM pressure.
# ──────────────────────────────────────────────────────────────────────────────

import json
import logging

log = logging.getLogger("ToolDispatcher")

# ── Lazy Instance Cache ───────────────────────────────────────────────────────
_INSTANCES = {}

def _get_tool(tool_class_name: str):
    """Lazily instantiates and returns a tool instance."""
    if tool_class_name in _INSTANCES:
        return _INSTANCES[tool_class_name]

    log.info(f"[Dispatcher] Lazily initializing {tool_class_name}...")
    
    if tool_class_name == "shell":
        from core.tools.shell_tool import ShellTool
        _INSTANCES[tool_class_name] = ShellTool()
    elif tool_class_name == "file":
        from core.tools.file_tool import FileTool
        _INSTANCES[tool_class_name] = FileTool()
    elif tool_class_name == "python":
        from core.tools.python_tool import PythonTool
        _INSTANCES[tool_class_name] = PythonTool()
    elif tool_class_name == "browser":
        from core.tools.browser_tool import BrowserTool
        _INSTANCES[tool_class_name] = BrowserTool()
    elif tool_class_name == "mapper":
        from core.tools.repo_mapper import RepoMapper
        _INSTANCES[tool_class_name] = RepoMapper()
    elif tool_class_name == "git":
        from core.tools.git_tool import GitTool
        _INSTANCES[tool_class_name] = GitTool()
    elif tool_class_name == "web":
        from core.agent.web_research import get_web_agent
        _INSTANCES[tool_class_name] = get_web_agent()

    return _INSTANCES[tool_class_name]

def dispatch_tool(action: str, tool_input, identity: str = "owner") -> str:
    """Route an agent action to the correct tool. Returns observation string."""
    try:
        sinput = str(tool_input).strip()
        data = _parse_json_input(tool_input)

        # ── Shell & OS ─────────────────────────────────────────────
        if action == "shell":
            return _get_tool("shell").run(sinput, identity)
        elif action == "read_shell_output":
            return _get_tool("shell").read_output()

        # ── Python REPL ────────────────────────────────────────────
        elif action == "python":
            if data and "code" in data:
                return _get_tool("python").run(data["code"])
            return _get_tool("python").run(sinput)

        # ── File Operations ────────────────────────────────────────
        elif action == "read_file":
            return _get_tool("file").read(sinput)
        elif action == "write_file":
            if not data or "path" not in data or "content" not in data:
                return "write_file requires JSON: {\"path\": \"...\", \"content\": \"...\"}"
            return _get_tool("file").write(data["path"], data["content"])
        elif action == "replace_in_file":
            if not data or "path" not in data or "target" not in data or "replacement" not in data:
                return "replace_in_file requires JSON: {\"path\": \"...\", \"target\": \"...\", \"replacement\": \"...\"}"
            return _get_tool("file").replace_in_file(data["path"], data["target"], data["replacement"])
        elif action == "list_dir":
            return _get_tool("file").list_dir(sinput)
        elif action == "map_structure":
            return _get_tool("mapper").map_structure(sinput)
        elif action == "delete_file":
            return _get_tool("file").delete(sinput, identity)

        # ── Git & Deployment ───────────────────────────────────────
        elif action == "git_init":
            return _get_tool("git").init(sinput)
        elif action == "git_commit":
            if not data or "path" not in data: return "git_commit requires path"
            return _get_tool("git").add_commit(data["path"], data.get("message", "JARVIS update"))
        elif action == "git_status":
            return _get_tool("git").status(sinput)
        elif action == "github_push":
            if not data or "path" not in data or "repo_name" not in data:
                return "github_push requires JSON: {\"path\": \"...\", \"repo_name\": \"...\"}"
            return _get_tool("git").create_and_push(data["path"], data["repo_name"], data.get("private", False))
        elif action == "deploy":
            if not data or "path" not in data: return "deploy requires path"
            target = data.get("target", "vercel").lower()
            if target == "netlify": return _get_tool("git").deploy_netlify(data["path"])
            return _get_tool("git").deploy_vercel(data["path"])

        # ── Browser & Research ─────────────────────────────────────
        elif action == "web_search":
            return _get_tool("web").research(sinput)
        elif action == "quick_search":
            return _get_tool("web").quick_answer(sinput)
        elif action == "open_url":
            return _get_tool("browser").open_url(sinput)
        elif action == "diagnose_error":
            from core.agent.ghost_debugger import GhostDebugger
            return GhostDebugger().diagnose(sinput)

        return f"Unknown tool action: {action}"

    except Exception as e:
        log.error(f"[Dispatcher] Error executing {action}: {e}", exc_info=True)
        return f"Tool Error: {e}"

def _parse_json_input(val):
    if isinstance(val, dict): return val
    try:
        return json.loads(val)
    except Exception:
        return None
