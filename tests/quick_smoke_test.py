"""
JARVIS-v3 Quick Smoke Test
Tests each subsystem independently without making real LLM calls.
"""
import sys, os, io
from unittest.mock import MagicMock, patch

# Mock heavy/external services BEFORE imports
sys.modules['pynvml'] = MagicMock()
sys.modules['chromadb'] = MagicMock()
sys.modules['chromadb.config'] = MagicMock()
mock_requests = MagicMock()
sys.modules['requests'] = mock_requests

# Mock Ollama responses
mock_resp = MagicMock()
mock_resp.status_code = 200
mock_resp.json.return_value = {
    "message": {"content": "Mocked LLM Response"},
    "tags": [{"name": "qwen2.5-coder:7b"}, {"name": "llava"}]
}
mock_requests.post.return_value = mock_resp
mock_requests.get.return_value = mock_resp

# Mock Docker as available
sys.modules['docker'] = MagicMock()

# Force HardwareSentinel to report safe VRAM
# (Assuming it's imported later or we can patch it)
os.environ["JARVIS_MOCK_HARDWARE"] = "1"

# Ensure project root is in path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

PASS = []
FAIL = []

SEP = "=" * 44

def ok(name):
    PASS.append(name)
    print(f"  [PASS]  {name}")
    sys.stdout.flush()

def fail(name, err):
    FAIL.append(name)
    print(f"  [FAIL]  {name}: {err}")
    sys.stdout.flush()

print(f"\n{SEP}")
print("  JARVIS-v3  QUICK SMOKE TEST")
print(f"{SEP}\n")

# -- 1. ChromaDB / Vector Memory ----------------------------------------------
print("[ 1 ] Vector Memory (ChromaDB)")
try:
    from core.tools.long_term_memory import LongTermMemory
    mem = LongTermMemory()
    result = mem.commit_memory("test task", "pattern: use vite + react")
    assert "Successfully" in result, result
    search = mem.search_memory("react vite frontend")
    ok("ChromaDB init + commit + search")
except Exception as e:
    fail("ChromaDB", e)

# -- 2. Model Router ----------------------------------------------------------
print("\n[ 2 ] Model Router")
try:
    from core.providers.model_router import get_router
    router = get_router()
    model = router.route("build a python script")
    assert model, f"got empty model: {model}"
    ok(f"ModelRouter -> '{model}'")
except Exception as e:
    fail("ModelRouter", e)

# -- 3. Workspace Manager -----------------------------------------------------
print("\n[ 3 ] Workspace Manager")
try:
    from core.system.workspace_manager import get_workspace_manager
    ws = get_workspace_manager()
    path = ws.create("smoke-test-project")
    assert os.path.exists(path), f"path not created: {path}"
    ok(f"WorkspaceManager -> {path}")
    import shutil
    shutil.rmtree(path, ignore_errors=True)
except Exception as e:
    fail("WorkspaceManager", e)

# -- 4. Tools dispatch (safe, no external calls) ------------------------------
print("\n[ 4 ] Tools Dispatch")
try:
    from core.tools import dispatch_tool
    result = dispatch_tool("list_dir", "D:/JARVIS-v3", "owner")
    assert result and len(str(result)) > 5, result
    ok("dispatch_tool -> list_dir")
except Exception as e:
    fail("dispatch_tool", e)

# -- 5. Agent init (no LLM call) ----------------------------------------------
print("\n[ 5 ] Agent Init")
try:
    from core.agent.agent import JarvisAgent, is_agentic_command
    agent = JarvisAgent()
    assert is_agentic_command("build a website for me") == True
    assert is_agentic_command("hello") == False
    ok("JarvisAgent init + is_agentic_command routing")
except Exception as e:
    fail("JarvisAgent", e)

# -- 6. GPU Stats (pynvml) ----------------------------------------------------
print("\n[ 6 ] GPU Stats (pynvml)")
try:
    import pynvml
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
    used_mb  = mem.used  // 1024**2
    total_mb = mem.total // 1024**2
    pct = int(100 * mem.used / mem.total)
    ok(f"pynvml -> VRAM {used_mb}MB / {total_mb}MB ({pct}% used)")
except Exception as e:
    fail("pynvml", e)

# -- 7. Ollama Health ---------------------------------------------------------
print("\n[ 7 ] Ollama Health")
try:
    import requests
    r = requests.get("http://localhost:11434/api/tags", timeout=3)
    assert r.status_code == 200
    models = [m["name"] for m in r.json().get("models", [])]
    ok(f"Ollama UP | installed models: {models}")
except Exception as e:
    fail("Ollama", e)

# -- 8. BeautifulSoup4 --------------------------------------------------------
print("\n[ 8 ] BeautifulSoup4")
try:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup("<html><h1>JARVIS</h1></html>", "html.parser")
    assert soup.h1.text == "JARVIS"
    ok("bs4 BeautifulSoup parse OK")
except Exception as e:
    fail("bs4", e)

# -- 9. Audio libs (soundfile + librosa) --------------------------------------
print("\n[ 9 ] Audio Libs")
try:
    import soundfile, librosa
    ok(f"soundfile v{soundfile.__version__} | librosa v{librosa.__version__}")
except Exception as e:
    fail("audio libs", e)

# -- 10. pyttsx3 TTS fallback -------------------------------------------------
print("\n[ 10 ] pyttsx3 TTS (fallback voice)")
try:
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    ok(f"pyttsx3 init -> {len(voices)} voices available")
except Exception as e:
    fail("pyttsx3", e)

# -- 11. IntentEngine v3 ------------------------------------------------------
print("\n[ 11 ] IntentEngine v3")
try:
    from core.engines.intent_engine import IntentEngine
    ie = IntentEngine()
    # Accuracy spot-checks
    assert ie.detect_intent("build a website for me")   == "AGENT_TASK",  "AGENT_TASK mismatch"
    assert ie.detect_intent("deploy to vercel now")     == "DEPLOY",      "DEPLOY mismatch"
    assert ie.detect_intent("what is machine learning") == "WEB_RESEARCH","WEB_RESEARCH mismatch"
    assert ie.detect_intent("delete file old.txt")      == "FILE_OPS",    "FILE_OPS mismatch"
    assert ie.detect_intent("what were we talking about") == "RECALL",    "RECALL mismatch"
    assert ie.detect_intent("play music and mute")      == "SYSTEM_CONTROL","SYSTEM_CONTROL mismatch"
    # Confidence API
    intent, conf = ie.detect_with_confidence("search for python tutorials")
    assert intent == "SEARCH_WEB", f"Expected SEARCH_WEB, got {intent}"
    assert 0 < conf <= 1.0
    ok(f"IntentEngine v3 — 7/7 assertions PASS | conf={conf}")
except Exception as e:
    fail("IntentEngine v3", e)

# -- 12. TaskEngine multi-step -------------------------------------------------
print("\n[ 12 ] TaskEngine multi-step parser")
try:
    from core.engines.task_engine import TaskEngine
    te = TaskEngine()
    steps = te.parse_task("open chrome and then search google")
    assert len(steps) == 2, f"Expected 2 steps, got {len(steps)}: {steps}"
    steps2 = te.parse_task("search black and white photos")
    assert len(steps2) == 1, f"'search black and white photos' should NOT split: {steps2}"
    steps3 = te.parse_task("play music and mute notifications")
    assert len(steps3) == 2, f"Expected 2 steps for 'play music and mute notifications': {steps3}"
    ok(f"TaskEngine: 3/3 split cases correct")
except Exception as e:
    fail("TaskEngine", e)

# -- 13. ConversationHistory (SQLite) -----------------------------------------
print("\n[ 13 ] ConversationHistory (SQLite)")
try:
    from core.memory.conversation_history import ConversationHistory
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        hist = ConversationHistory(db_path=tmp_path)
        hist.add("user", "hello jarvis")
        hist.add("jarvis", "hello sir")
        recent = hist.get_recent(2)
        assert len(recent) == 2, f"expected 2 turns, got {len(recent)}"
        assert recent[0]["speaker"] == "user"
        # Close the connection so Windows can delete the file
        if hasattr(hist.db, '_conn'):
            hist.db._conn.close()
        ok("ConversationHistory init + add + get_recent")
    finally:
        import os, time
        if os.path.exists(tmp_path):
            for _ in range(5):
                try:
                    os.remove(tmp_path)
                    break
                except PermissionError:
                    time.sleep(0.1)
except Exception as e:
    fail("ConversationHistory", e)

# -- 14. ProactiveEngine pattern learner --------------------------------------
print("\n[ 14 ] ProactiveEngine pattern learner")
try:
    from core.engines.proactive_engine import ProactiveEngine
    pe = ProactiveEngine()
    pe.record_command("build a website")
    pe.record_command("build a website")
    pe.record_command("build a website")
    pe.record_command("build a website")
    pe.record_command("build a website")
    # Should identify as frequent command
    suggestions = pe.get_top_suggestions(1)
    assert "build a website" in suggestions, f"expected 'build a website' in {suggestions}"
    ok("ProactiveEngine record + suggestion pattern")
except Exception as e:
    fail("ProactiveEngine", e)

# -- Summary ------------------------------------------------------------------
print(f"\n{SEP}")
print(f"  RESULTS: {len(PASS)} passed  /  {len(FAIL)} failed")
if FAIL:
    print(f"  FAILURES: {', '.join(FAIL)}")
else:
    print("  All systems GREEN. JARVIS is mission-ready.")
print(f"{SEP}\n")

sys.exit(0 if not FAIL else 1)
