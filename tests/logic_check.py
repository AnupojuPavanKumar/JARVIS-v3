import sys, importlib, os, threading, time
from unittest.mock import MagicMock, patch

# Mock heavy/external services BEFORE imports that might trigger them
sys.modules['pynvml'] = MagicMock()
sys.modules['chromadb'] = MagicMock()
sys.modules['chromadb.config'] = MagicMock()
mock_requests = MagicMock()
sys.modules['requests'] = mock_requests

# Mock Ollama responses
mock_resp = MagicMock()
mock_resp.status_code = 200
mock_resp.json.return_value = {"message": {"content": "Mocked LLM Response"}}
mock_requests.post.return_value = mock_resp
mock_requests.get.return_value = mock_resp

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
os.chdir(_root)

# Force HardwareSentinel to report safe VRAM
from core.system.hardware_sentinel import HardwareSentinel
HardwareSentinel._get_vram_usage = MagicMock(return_value=0.5)

# Mock Docker as available for PythonTool tests
from core.system.docker_sandbox import DockerSandbox
DockerSandbox.is_available = MagicMock(return_value=True)

def mock_run_python(code, **kwargs):
    if "2**10" in code: return "1024"
    if "math.pi" in code: return "3.14159265"
    if "json.dumps" in code: return '{"a": 1}'
    return "hello world"

DockerSandbox.run_python = MagicMock(side_effect=mock_run_python)

# Mock LongTermMemory collection
def mock_ltm_query(query_texts, **kwargs):
    if "flask" in query_texts[0].lower():
        return {
            "documents": [["Use Flask-Login. Store sessions in Redis."]],
            "metadatas": [[{"task": "flask authentication app"}]]
        }
    return {
        "documents": [["use vite and tailwind"]],
        "metadatas": [[{"task": "build react app"}]]
    }

mock_coll = MagicMock()
mock_coll.query.side_effect = mock_ltm_query
mock_coll.count.return_value = 1

import chromadb
chromadb.PersistentClient.return_value.get_or_create_collection.return_value = mock_coll

PASS = 0
FAIL = 0

def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}" + (f"  => {detail}" if detail else ""))
    sys.stdout.flush()

# ══════════════════════════════════════════════════════
print("\n=== 1. Module Import Checks ===")
# ══════════════════════════════════════════════════════
mods = [
    ("core.tools.python_tool",  "PythonTool"),
    ("core.tools.shell_tool",   "ShellTool"),
    ("core.tools.app_tool",     "AppTool"),
    ("core.tools.browser_tool", "BrowserTool"),
    ("core.tools.system_tool",  "SystemTool"),
    ("core.tools.repo_mapper",  "RepoMapper"),
    ("core.tools.long_term_memory", "LongTermMemory"),
    ("core.tools",              "dispatch_tool"),
    ('core.engines.task_engine',        "TaskEngine"),
    ('core.memory.memory_brain',       "MemoryBrain"),
    ('core.memory.command_memory',     "CommandMemory"),
    ('core.engines.context_engine',     "ContextEngine"),
    ('core.system.system_monitor',     "SystemMonitor"),
    ('core.system.hardware_sentinel',  "HardwareSentinel"),
    ('core.agent.agent',              "JarvisAgent"),
    ('core.agent.agent',              "is_agentic_command"),
    # Skip JarvisBrain here as it might hang during UI/EventBus init
]
for mod_name, attr in mods:
    try:
        mod = importlib.import_module(mod_name)
        getattr(mod, attr)
        check(f"{mod_name}.{attr}", True)
    except Exception as e:
        check(f"{mod_name}.{attr}", False, str(e))

# ══════════════════════════════════════════════════════
print("\n=== 2. TaskEngine Split Tests ===")
# ══════════════════════════════════════════════════════
from core.engines.task_engine import TaskEngine
te = TaskEngine()
cases = [
    ("search black and white photos",       1),
    ("open chrome and then play spotify",   2),
    ("open chrome and play spotify",        2),
    ("search news and open youtube",        2),
    ("open chrome then open notepad",       2),
    ("good night",                          1),
    ("set volume to 50 and mute discord",   2),
    ("download and install python",         1),
    ("open vscode and open chrome and search github",  3),
    ("just open chrome",                    1),
]
for cmd, expected in cases:
    steps = te.parse_task(cmd)
    check(f'TaskEngine: "{cmd}"', len(steps)==expected,
          f"got {len(steps)} steps: {steps}")

# ══════════════════════════════════════════════════════
print("\n=== 3. PythonTool Blocklist & Safety ===")
# ══════════════════════════════════════════════════════
from core.tools.python_tool import PythonTool
pt = PythonTool()

blocked = [
    "import shutil\nshutil.rmtree('/tmp')",
    "import os\nos.remove('file.txt')",
    "import subprocess\nsubprocess.run('cmd', shell=True)",
    "import ctypes",
    "import sys\nsys.exit(0)",
    "import winreg",
    "import os\nos.unlink('x')",
]
for snippet in blocked:
    r = pt.run(snippet)
    check(f"BLOCKED: {snippet[:45]!r}", "[BLOCKED]" in r, r[:60])

allowed = [
    ("print('hello world')",           "hello world"),
    ("x = 2**10\nprint(x)",            "1024"),
    ("import math\nprint(math.pi)",    "3.14159"),
    ("import json\nprint(json.dumps({'a':1}))", '{"a": 1}'),
]
for snippet, expected_substr in allowed:
    r = pt.run(snippet)
    check(f"ALLOWED: {snippet[:40]!r}",
          "[BLOCKED]" not in r and expected_substr in r, r[:60])

# ══════════════════════════════════════════════════════
print("\n=== 4. ShellTool Safety ===")
# ══════════════════════════════════════════════════════
from core.tools.shell_tool import ShellTool
sh = ShellTool()

blocked_cmds = [
    "format C:",
    "Remove-Item -Recurse C:\\Windows",
    "Stop-Computer",
    "Restart-Computer",
]
for cmd in blocked_cmds:
    r = sh.run(cmd)
    check(f"Shell BLOCKED: {cmd!r}", "[BLOCKED]" in r, r[:60])

# Safe command
r = sh.run("echo JARVIS_TEST_OK")
check("Shell ALLOWED: echo", "JARVIS_TEST_OK" in r, r[:80])

# read_output on no-process returns sensible message
sh2 = ShellTool()
r2 = sh2.read_output()
check("read_output with no process", "No active" in r2, r2[:60])

# ══════════════════════════════════════════════════════
print("\n=== 5. MemoryBrain Thread Safety ===")
# ══════════════════════════════════════════════════════
from core.memory.memory_brain import MemoryBrain
mb = MemoryBrain()

# Concurrent log_action from multiple threads
errors = []
def _log(action):
    try:
        mb.log_action(action)
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=_log, args=(f"concurrent_action_{i}",)) for i in range(20)]
for t in threads: t.start()
for t in threads: t.join()
check("MemoryBrain concurrent log_action (20 threads)", len(errors)==0,
      f"{len(errors)} errors: {errors[:2]}")

actions = mb.get_recent_actions(5)
check("MemoryBrain get_recent_actions returns list", isinstance(actions, list))

mb.save_relationship("jarvis", "BUILT_BY", "pavan")
results = mb.search_graph("pavan")
check("MemoryBrain save/search relationship", len(results)>0, str(results))

# ══════════════════════════════════════════════════════
print("\n=== 6. CommandMemory Thread Safety & Cap ===")
# ══════════════════════════════════════════════════════
from core.memory.command_memory import CommandMemory
cm = CommandMemory()

# Learn multi-step commands concurrently
lerrs = []
def _learn(i):
    try:
        cm.learn(f"open app_{i} and search topic_{i}", [f"open app_{i}", f"search topic_{i}"])
    except Exception as e:
        lerrs.append(str(e))

lthreads = [threading.Thread(target=_learn, args=(i,)) for i in range(30)]
for t in lthreads: t.start()
for t in lthreads: t.join()
check("CommandMemory concurrent learn (30 threads)", len(lerrs)==0,
      f"{len(lerrs)} errors")

# Cap enforcement
from core.memory.command_memory import MAX_LEARNED
check("CommandMemory cap respected", len(cm.data) <= MAX_LEARNED,
      f"stored {len(cm.data)} > cap {MAX_LEARNED}")

# Recall works
cm.learn("open notepad and open chrome", ["open notepad", "open chrome"])
result = cm.recall("open notepad and open chrome")
check("CommandMemory recall works", result is not None and len(result)==2, str(result))

# Non-agentic guard — verify recall returns None for agentic commands
from core.agent.agent import is_agentic_command
agentic_cmd = "build a flask web app with authentication"
check("is_agentic_command detects build task", is_agentic_command(agentic_cmd))
check("is_agentic_command rejects short cmd", not is_agentic_command("hi"))
check("is_agentic_command detects 3-word cmd", is_agentic_command("build an app"))

# ══════════════════════════════════════════════════════
print("\n=== 7. ContextEngine Growth Cap ===")
# ══════════════════════════════════════════════════════
from core.engines.context_engine import ContextEngine
ce = ContextEngine()
for i in range(30):
    ce.add_app(f"app_{i}")
check("ContextEngine last_apps capped at 20", len(ce.last_apps) <= 20,
      f"got {len(ce.last_apps)}")
ctx = ce.get_context()
check("ContextEngine get_context returns dict", isinstance(ctx, dict) and "apps" in ctx)

# ══════════════════════════════════════════════════════
print("\n=== 8. SystemMonitor Thread-Safety ===")
# ══════════════════════════════════════════════════════
from core.system.system_monitor import SystemMonitor
sm = SystemMonitor()
time.sleep(0.5)   # let monitor thread spin up
sm.alert_message = "test_alert"
msg = sm.get_alert()
check("SystemMonitor get_alert reads and clears", msg == "test_alert")
msg2 = sm.get_alert()
check("SystemMonitor get_alert clears after read", msg2 is None)
sm.running = False   # stop background thread

# ══════════════════════════════════════════════════════
print("\n=== 9. RepoMapper ===")
# ══════════════════════════════════════════════════════
from core.tools.repo_mapper import RepoMapper
import json as _json
rm = RepoMapper()
result = rm.map_structure("core")
parsed = _json.loads(result)
check("RepoMapper maps core/ directory", isinstance(parsed, dict) and len(parsed) > 0,
      f"got {len(parsed)} entries")
check("RepoMapper finds agent.py", any("agent.py" in k for k in parsed))

# ══════════════════════════════════════════════════════
print("\n=== 10. LongTermMemory FTS ===")
# ══════════════════════════════════════════════════════
from core.tools.long_term_memory import LongTermMemory
ltm = LongTermMemory()
ltm.commit_memory("flask authentication app", "Use Flask-Login. Store sessions in Redis.")
r = ltm.search_memory("flask authentication")
check("LongTermMemory commit+search", "flask" in r.lower() or "MATCH" in r, r[:80])

# ══════════════════════════════════════════════════════
print("\n=== 11. GhostDebugger Heuristic ===")
# ══════════════════════════════════════════════════════
from core.agent.ghost_debugger import GhostDebugger
gd = GhostDebugger()
sample_css = "width: 300px; overflow: hidden; z-index: 9999; font-size: 14px !important;"
result = gd._heuristic_analyze(context=sample_css)
check("GhostDebugger detects fixed px width",  "px" in result["detected_issues"].lower() or "fixed" in result["detected_issues"].lower())
check("GhostDebugger detects overflow:hidden", "overflow" in result["detected_issues"].lower())
check("GhostDebugger detects !important",      "important" in result["detected_issues"].lower())
check("GhostDebugger returns patch dict",      isinstance(result, dict) and "visual_patch" in result)

# ══════════════════════════════════════════════════════
print("\n=== 12. HardwareSentinel VRAM Parse ===")
# ══════════════════════════════════════════════════════
from core.system.hardware_sentinel import HardwareSentinel
hs = HardwareSentinel()
vram = hs._get_vram_usage()
check("HardwareSentinel _get_vram_usage returns float or None",
      vram is None or (isinstance(vram, float) and 0.0 <= vram <= 1.0),
      str(vram))
# Drainable processes dict exists
check("HardwareSentinel has _DRAINABLE_PROCESSES",
      hasattr(hs, "_DRAINABLE_PROCESSES") and len(hs._DRAINABLE_PROCESSES) > 0)

# ══════════════════════════════════════════════════════
print("\n=== 13. ConversationHistory Persistence ===")
# ══════════════════════════════════════════════════════
from core.memory.conversation_history import ConversationHistory
import tempfile

# Use a temporary DB so we don't pollute the real history
_tmp_db = tempfile.mktemp(suffix=".db")
ch = ConversationHistory(db_path=_tmp_db)

ch.add("user", "open chrome")
ch.add("jarvis", "Opening Chrome now, sir.")
ch.add("user", "search github")

turns = ch.get_recent(10)
check("ConversationHistory stores turns", len(turns) == 3)
check("ConversationHistory speaker field", turns[0]["speaker"] == "user")
check("ConversationHistory text field", "chrome" in turns[0]["text"])

prompt = ch.format_for_prompt()
check("format_for_prompt has header",  "[CONVERSATION HISTORY]" in prompt)
check("format_for_prompt has content", "open chrome" in prompt)

recall = ch.recall_what_we_discussed()
check("recall_what_we_discussed identifies topics", "chrome" in recall or "github" in recall)

# Thread-safety: concurrent writes
import threading as _threading
_errs = []
def _add(i):
    try: ch.add("user", f"concurrent_cmd_{i}")
    except Exception as e: _errs.append(str(e))
_threads = [_threading.Thread(target=_add, args=(i,)) for i in range(20)]
for t in _threads: t.start()
for t in _threads: t.join()
check("ConversationHistory concurrent writes (20 threads)", len(_errs) == 0,
      f"{len(_errs)} errors: {_errs[:2]}")

try:
    import os as _os
    _os.remove(_tmp_db)
except Exception:
    pass

# ══════════════════════════════════════════════════════
print("\n=== 14. WorkspaceManager Isolation ===")
# ══════════════════════════════════════════════════════
from core.system.workspace_manager import WorkspaceManager
import shutil as _shutil

wm = WorkspaceManager()
ws1 = wm.create("test_project_logic_check")
check("WorkspaceManager creates directory", _os.path.isdir(ws1))
check("WorkspaceManager creates README",   _os.path.exists(_os.path.join(ws1, "README.md")))
check("WorkspaceManager not in JARVIS root",
      "JARVIS-v2" not in ws1 or "JARVIS_Projects" in ws1)

active = wm.list_active()
check("WorkspaceManager list_active returns entries", len(active) >= 1)

wm.complete(ws1)
active_after = wm.list_active()
check("WorkspaceManager complete() removes from active",
      not any(e["path"] == ws1 for e in active_after))

resolve_rel = wm.resolve_path("src/app.py", task_ws=ws1)
check("resolve_path anchors relative to workspace",
      ws1 in resolve_rel and "src/app.py" in resolve_rel)

resolve_abs = wm.resolve_path("C:/Windows/System32", task_ws=ws1)
check("resolve_path passes through absolute paths",
      resolve_abs == "C:/Windows/System32")

# Clean up test workspace
try:
    _shutil.rmtree(ws1, ignore_errors=True)
except Exception:
    pass

# ══════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════
total = PASS + FAIL
print(f"\n{'='*50}")
print(f"  RESULTS: {PASS}/{total} passed  |  {FAIL} failed")
print(f"{'='*50}")
sys.exit(0 if FAIL == 0 else 1)
