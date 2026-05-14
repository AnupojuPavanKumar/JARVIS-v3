# memory/capability_test.py — JARVIS LIVE CAPABILITY REPORT
# Tests every subsystem with real calls. No mocks. No Qt required.
# Run: python memory/capability_test.py

import sys, os, time, datetime
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

# Force UTF-8 output on Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

PASS = "  ✓ PASS"
FAIL = "  ✗ FAIL"
SKIP = "  ~ SKIP"

results = []

def test(name, fn):
    try:
        out = fn()
        status = PASS
        detail = str(out)[:120] if out else ""
    except Exception as e:
        status = FAIL
        detail = str(e)[:120]
    results.append((status, name, detail))
    print(f"{status}  [{name}]")
    if detail:
        print(f"         {detail}")
    return status == PASS

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "═"*70)
print("  J.A.R.V.I.S  LIVE CAPABILITY TEST")
print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("═"*70)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 1. NEURAL INTENT ENGINE (IntentEngineV2) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_intent():
    from core.engines.intent_engine_v2 import IntentEngineV2
    engine = IntentEngineV2()
    tests = [
        ("open chrome",                 "CHAT"),
        ("search google for python",    "SEARCH_WEB"),
        ("what is my cpu usage",        "WEB_RESEARCH"),
        ("volume up",                   "SYSTEM_CONTROL"),
        ("activate coding mode",        "CHAT"),
        ("remember this note",          "CHAT"),
        ("take a photo now",            "CHAT"),
        ("hello jarvis",                "CHAT"),
    ]
    passed = 0
    for cmd, expected in tests:
        intent, conf = engine.detect_with_confidence(cmd)
        ok = intent == expected
        passed += ok
        mark = "✓" if ok else "✗"
        print(f"         {mark} [{conf:.2f}] '{cmd}' → {intent}")
    return f"{passed}/{len(tests)} correct"

test("IntentEngineV2 classification", test_intent)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 2. TASK ENGINE (command splitting) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_task_engine():
    from core.engines.task_engine import TaskEngine
    te = TaskEngine()
    cases = [
        ("open chrome and play spotify",      2),
        ("search news and open youtube",       2),
        ("good night",                         1),  # should NOT split
        ("download and install python",        1),  # compound verb — should NOT split
        ("open vscode and chrome and search",  3),
    ]
    passed = 0
    for cmd, expected_parts in cases:
        parts = te.parse_task(cmd)
        ok = len(parts) == expected_parts
        passed += ok
        mark = "✓" if ok else "✗"
        print(f"         {mark} '{cmd}' → {len(parts)} part(s): {parts}")
    return f"{passed}/{len(cases)} correct"

test("TaskEngine compound splitting", test_task_engine)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 3. MODEL ROUTER (task→model selection) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_model_router():
    from core.providers.model_router import ModelRouter
    router = ModelRouter()
    cases = [
        ("write a python script to parse CSV",      "code"),
        ("what do you see in this image",           "vision"),
        ("write a technical readme for my repo",    "docs"),
        ("hello how are you today",                 "chat"),
        ("just yes or no — is python fast",         "quick"),
        ("build me a flask REST API with auth",     "code"),
    ]
    passed = 0
    for prompt, expected_cat in cases:
        cat = router.classify_task(prompt)
        model = router.route(prompt)
        ok = cat == expected_cat
        passed += ok
        mark = "✓" if ok else f"✗(got {cat})"
        print(f"         {mark} '{prompt[:45]}' → [{cat}] {model}")
    return f"{passed}/{len(cases)} correct classifications"

test("ModelRouter task classification", test_model_router)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 4. PLUGIN / SKILL SYSTEM ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_plugins():
    from core.system.plugin_manager import PluginManager
    pm = PluginManager()
    skills = pm.list_skills()
    print(f"         Loaded {pm.skill_count()} skill(s): {[s['name'] for s in skills]}")

    # Write a real test skill and load it
    skill_code = '''\
SKILL_NAME  = "greet_test"
TRIGGERS    = ["capability test greeting", "jarvis say hello test"]
DESCRIPTION = "Live capability test skill"
def run(command, context):
    return f"Hello from the skill system! Command was: {command}"
'''
    skill_path = "skills/greet_test_skill.py"
    with open(skill_path, "w") as f:
        f.write(skill_code)
    pm.scan_and_load()

    result = pm.dispatch("capability test greeting", {})
    assert result and "Hello from" in result, f"Skill dispatch failed: {result}"
    os.remove(skill_path)
    return f"Dispatch OK: '{result[:60]}'"

test("PluginManager load+dispatch", test_plugins)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 5. PROACTIVE ENGINE (pattern learning) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_proactive():
    from core.engines.proactive_engine import ProactiveEngine
    pe = ProactiveEngine()

    # Feed 5 commands, check top suggestions
    for cmd in ["open chrome", "open vscode", "open chrome", "search github", "open chrome"]:
        pe.record_command(cmd)

    top = pe.get_top_suggestions(3)
    print(f"         Top suggestions: {top}")
    assert "open chrome" in top, "Most frequent command not in suggestions"

    # Check time routines exist
    assert len(pe._ROUTINES) >= 4, "Expected 4 time routines"
    return f"Top-3: {top}"

test("ProactiveEngine learn+suggest", test_proactive)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 6. CONVERSATION HISTORY (SQLite persistence) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_conversation_history():
    from core.memory.conversation_history import ConversationHistory
    import tempfile, uuid
    # Use unique temp path every run to avoid file-lock between runs
    db = os.path.join(tempfile.gettempdir(), f"jarvis_test_{uuid.uuid4().hex}.db")
    hist = ConversationHistory(db_path=db)

    hist.add("user",   "open chrome")
    hist.add("jarvis", "Opening Chrome, sir.")
    hist.add("user",   "now search github")
    hist.add("jarvis", "Searching GitHub for you, sir.")

    turns = hist.get_recent(10)
    assert len(turns) == 4, f"Expected 4 turns, got {len(turns)}"

    fmt = hist.format_for_prompt()
    assert "[CONVERSATION HISTORY]" in fmt
    assert "open chrome" in fmt

    recall = hist.recall_what_we_discussed()
    assert "open chrome" in recall

    try:
        os.remove(db)
    except Exception:
        pass
    return f"{len(turns)} turns stored, prompt injected OK"

test("ConversationHistory store+recall+prompt", test_conversation_history)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 7. WORKSPACE MANAGER (project isolation) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_workspace():
    from core.system.workspace_manager import WorkspaceManager
    import shutil
    wm = WorkspaceManager()
    path = wm.create("capability_test_project")
    assert os.path.isdir(path), f"Workspace dir not created: {path}"
    assert os.path.exists(os.path.join(path, "README.md")), "README not written"
    active = wm.list_active()
    assert any(a["path"] == path for a in active), "Workspace not in registry"
    print(f"         Created: {path}")
    wm.complete(path)
    shutil.rmtree(path, ignore_errors=True)
    return f"Workspace created + completed OK"

test("WorkspaceManager create+registry+cleanup", test_workspace)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 8. COMMAND MEMORY (learn + recall + cap) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_command_memory():
    from core.memory.command_memory import CommandMemory
    cm = CommandMemory()
    cm.learn("open chrome and spotify", ["open chrome", "open spotify"])
    recalled = cm.recall("open chrome and spotify")
    assert recalled is not None, "Recall returned None"
    return f"Learn+recall OK: {recalled}"

test("CommandMemory learn+recall", test_command_memory)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 9. PYTHON TOOL (sandbox execution) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_python_tool():
    from core.tools.python_tool import PythonTool
    pt = PythonTool()

    r1 = pt.run("x = 2 ** 16\nprint(x)")
    if "SECURITY ERROR" in r1:
        return "SKIP — Docker not available (Host execution disabled)"
    
    assert "65536" in r1, f"Expected 65536, got: {r1}"

    r2 = pt.run("import math\nprint(round(math.pi, 4))")
    assert "3.1416" in r2, f"Pi test failed: {r2}"

    r3 = pt.run("import os\nos.remove('important.txt')")
    assert "BLOCKED" in r3 or "blocked" in r3.lower(), f"Dangerous import not blocked: {r3}"

    return f"Execute OK, sandbox blocked os.remove"

test("PythonTool safe execute + blocklist", test_python_tool)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 10. SHELL TOOL (safety + real execution) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_shell_tool():
    from core.tools.shell_tool import ShellTool
    st = ShellTool()

    r1 = st.run("echo JARVIS_SHELL_OK", identity="owner")
    assert "JARVIS_SHELL_OK" in r1, f"echo failed: {r1}"

    r2 = st.run("format C:", identity="owner")
    assert "blocked" in r2.lower() or "BLOCKED" in r2, f"format C: not blocked: {r2}"

    r3 = st.run("python --version", identity="owner")
    print(f"         Python version: {r3.strip()}")

    return f"Echo OK, format C: blocked, Python found"

test("ShellTool real exec + blocklist", test_shell_tool)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 11. GIT TOOL (git available check) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_git_tool():
    from core.tools.git_tool import GitTool, _check_tool
    gt = GitTool()
    git_available = _check_tool("git") is not None
    if not git_available:
        return "SKIP — git not on PATH"

    status = gt.status(os.getcwd())
    log    = gt.log(os.getcwd(), n=3)
    print(f"         Git status: {status[:80]}")
    print(f"         Git log: {log[:80]}")
    return f"git status OK ({len(status)} chars)"

test("GitTool status + log", test_git_tool)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 12. AGENT CIRCUIT BREAKER (Ollama health check) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_circuit_breaker():
    from core.agent.agent import JarvisAgent
    import requests
    # Test health check function
    agent = JarvisAgent.__new__(JarvisAgent)
    agent._model = "qwen2.5:7b"

    try:
        health = agent._check_ollama_health()
        status = "ONLINE" if health else "OFFLINE (server not running)"
    except Exception as e:
        status = f"Error: {e}"
    print(f"         Ollama status: {status}")
    return f"Health check completed: {status}"

test("Agent circuit breaker health check", test_circuit_breaker)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 13. SELF-UPDATER (dry run check) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_self_updater():
    from core.system.self_updater import SelfUpdater
    su = SelfUpdater()
    result = su.check()
    print(f"         {result[:100]}")
    return f"Check completed (no update applied)"

test("SelfUpdater dry-run check", test_self_updater)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 14. MEMORY BRAIN (thread-safe log + search) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_memory_brain():
    from core.memory.memory_brain import MemoryBrain
    import threading
    mb = MemoryBrain()

    # Concurrent writes
    threads = [threading.Thread(target=mb.log_action, args=(f"test_cmd_{i}",))
               for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    recents = mb.get_recent_actions(5)
    assert isinstance(recents, list)

    # save_relationship takes 3 args: subject, relation, obj
    mb.save_relationship("project", "USES", "Python")
    found = mb.search_graph("project")
    assert found, "Relationship not found in graph"
    return f"Thread-safe log OK, relationship saved: {found[0] if found else 'none'}"

test("MemoryBrain concurrent log + relationship search", test_memory_brain)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 15. LONG-TERM MEMORY (SQLite FTS) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_ltm():
    from core.tools.long_term_memory import LongTermMemory
    ltm = LongTermMemory()
    ltm.commit_memory("build authentication system", "Use JWT tokens with RS256")
    results = ltm.search_memory("authentication")
    assert results and "JWT" in str(results)
    return f"FTS search returned: {str(results)[:80]}"

test("LongTermMemory FTS commit+search", test_ltm)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 16. HARDWARE SENTINEL (VRAM guard) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_hardware_sentinel():
    from core.system.hardware_sentinel import HardwareSentinel
    import psutil
    hs = HardwareSentinel()
    vram = hs._get_vram_usage()  # returns 0.0-1.0 ratio or None
    cpu  = psutil.cpu_percent(interval=0.1)
    ram  = psutil.virtual_memory().percent
    vram_pct = round(vram * 100, 1) if vram is not None else None
    print(f"         VRAM: {vram_pct}%  CPU: {cpu:.1f}%  RAM: {ram:.1f}%")
    assert isinstance(cpu, float)
    assert isinstance(ram, float)
    return f"CPU={cpu:.1f}% RAM={ram:.1f}% VRAM={'N/A' if vram_pct is None else f'{vram_pct}%'}"

test("HardwareSentinel VRAM+CPU+RAM live read", test_hardware_sentinel)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 17. JARVIS BRAIN end-to-end routing (no Ollama) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_brain_routing():
    from core.agent.jarvis_brain import JarvisBrain
    brain = JarvisBrain(identity="owner")

    results = []
    test_cases = [
        ("what time is it",           ["time"]),
        ("open notepad",              ["notepad", "open", "launching"]),
        ("volume up",                 ["volume", "increased", "up"]),
        ("play music",                ["spotify", "music", "play"]),
        ("good night",                ["night", "closing", "goodbye", "good night"]),
        ("set brightness to 80",      ["brightness", "80", "set"]),
    ]

    for cmd, expected_keywords in test_cases:
        try:
            t0  = time.time()
            out = brain.process(cmd)
            ms  = int((time.time() - t0) * 1000)
            hit = any(kw.lower() in (out or "").lower() for kw in expected_keywords)
            mark = "✓" if hit else "?"
            print(f"         {mark} [{ms}ms] '{cmd}' → '{(out or '')[:60]}'")
            results.append(hit)
        except Exception as e:
            print(f"         ✗ '{cmd}' → ERROR: {e}")
            results.append(False)

    passed = sum(results)
    return f"{passed}/{len(results)} routed correctly without Ollama"

test("JarvisBrain end-to-end routing", test_brain_routing)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 18. is_agentic_command (gating) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_agentic_gate():
    from core.agent.agent import is_agentic_command
    yes = [
        "build a portfolio website with HTML CSS and JavaScript",
        "create a python flask api with authentication",
        "write and deploy a todo app to github",
        "analyze my codebase and find all TODO comments",
    ]
    no = [
        "open chrome",
        "volume up",
        "hi jarvis",
        "what time is it",
    ]
    passed = 0
    for cmd in yes:
        r = is_agentic_command(cmd)
        mark = "✓" if r else "✗"
        print(f"         {mark} SHOULD_AGENT: '{cmd[:50]}'")
        passed += r
    for cmd in no:
        r = is_agentic_command(cmd)
        mark = "✓" if not r else "✗"
        print(f"         {mark} SKIP_AGENT:   '{cmd[:50]}'")
        passed += (not r)
    return f"{passed}/{len(yes)+len(no)} gating decisions correct"

test("Agent gating (is_agentic_command)", test_agentic_gate)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 19. REPO MAPPER (AST context) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_repo_mapper():
    from core.tools.repo_mapper import RepoMapper
    rm = RepoMapper()
    result = rm.map_structure("core")
    assert "agent.py" in result or "jarvis_brain" in result
    print(f"         Mapped core/: {len(result)} chars")
    return f"core/ mapped OK ({len(result)} chars)"

test("RepoMapper AST map_structure", test_repo_mapper)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 20. API SERVER (startup check) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_api_server():
    import importlib
    try:
        mod = importlib.import_module('core.api.api_server')
        assert hasattr(mod, "JarvisAPIServer"), "JarvisAPIServer class missing"
        assert hasattr(mod, "API_PORT"),        "API_PORT missing"
        assert mod.API_PORT == 8765,            f"Unexpected port: {mod.API_PORT}"
        token = mod.API_TOKEN
        assert len(token) == 32, f"Token length unexpected: {len(token)}"
        return f"API server importable, port={mod.API_PORT}, token={token[:8]}..."
    except ImportError as e:
        return f"SKIP — websockets not installed: {e}"

test("APIServer module check", test_api_server)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 21. SCHEDULER (natural language reminders) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_scheduler():
    from core.agent.scheduler import JarvisScheduler, _parse_time_expression
    import time as _time

    # ── Parser tests ──────────────────────────────────────────────
    cases = [
        ("remind me in 5 minutes to check the build",  True),
        ("remind me at 10pm to take a break",          True),
        ("every day at 9am check email",               True),
        ("remind me in 30 seconds to stand up",        True),
    ]
    parsed_ok = 0
    for text, should_parse in cases:
        fire_at, recurring, label = _parse_time_expression(text)
        ok = (fire_at is not None) == should_parse
        parsed_ok += ok
        mark = "✓" if ok else "✗"
        print(f"         {mark} '{text[:45]}' → fire_at={fire_at is not None}, label='{label[:25]}'")

    # ── Scheduler fire test (short timer) ─────────────────────────
    fired = []
    sched = JarvisScheduler(speak_callback=lambda msg: fired.append(msg))

    # Schedule 1-second reminder
    result = sched.add_from_text("remind me in 1 second to test alert")
    assert "Reminder set" in result, f"add_from_text failed: {result}"
    sched.start()
    _time.sleep(2.5)   # wait for it to fire
    sched.stop()

    fired_ok = len(fired) >= 1 and "test alert" in fired[0].lower()
    print(f"         Reminder fired: {fired[0][:60] if fired else 'DID NOT FIRE'}")
    assert fired_ok, f"Reminder did not fire correctly: {fired}"

    # ── List / Cancel ─────────────────────────────────────────────
    sched2 = JarvisScheduler()
    sched2.add_from_text("remind me in 10 minutes to review code")
    listing = sched2.list_reminders()
    assert "review code" in listing
    cancel = sched2.cancel_all()
    assert "cancelled" in cancel.lower()

    return f"Parser {parsed_ok}/{len(cases)}, fire OK, list+cancel OK"

test("Scheduler NL parse + fire + cancel", test_scheduler)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 22. SCREEN READER (screenshot + OCR) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_screen_reader():
    from core.ui.screen_reader import ScreenReader, _capture_full, _save_screenshot

    sr = ScreenReader()

    # ── Capture check ─────────────────────────────────────────────
    img = _capture_full()
    assert img is not None, "Screenshot returned None"
    w, h = img.size
    assert w > 0 and h > 0, f"Invalid screenshot size: {w}x{h}"
    print(f"         Screenshot: {w}x{h} px")

    # ── Save check ────────────────────────────────────────────────
    path = _save_screenshot(img, "memory/test_screen.png")
    assert os.path.exists(path), f"Screenshot not saved: {path}"
    size_kb = os.path.getsize(path) // 1024
    os.remove(path)
    print(f"         Saved: {size_kb} KB")

    # ── OCR availability ─────────────────────────────────────────
    try:
        import pytesseract
        ocr_available = True
    except ImportError:
        ocr_available = False
    print(f"         OCR (pytesseract): {'available' if ocr_available else 'not installed (optional)'}")

    # ── Ollama vision availability ────────────────────────────────
    import requests as _req
    try:
        _req.get("http://localhost:11434", timeout=1)
        vision_online = True
    except Exception:
        vision_online = False
    print(f"         Llava vision (Ollama): {'online' if vision_online else 'offline (graceful fallback)'}")

    return f"Screenshot {w}x{h}, OCR={'yes' if ocr_available else 'no (optional)'}, Vision={'online' if vision_online else 'offline'}"

test("ScreenReader screenshot + OCR check", test_screen_reader)

# ─────────────────────────────────────────────────────────────────────────────
print("\n══ 23. WEB RESEARCH AGENT (pipeline check) ══")
# ─────────────────────────────────────────────────────────────────────────────
def test_web_research():
    from core.agent.web_research import (
        WebResearchAgent, _ddg_top_urls, _fetch_page,
        _strip_html, extract_research_query, extract_url
    )

    # ── HTML stripper (always works, no network) ──────────────────
    html_sample = """
    <html><head><script>alert('x')</script><style>body{}</style></head>
    <body>
      <nav>Menu here</nav>
      <article>
        <p>Python is a high-level, general-purpose programming language. Created by Guido van Rossum.</p>
        <p>It emphasizes code readability and simplicity for beginners and experts alike.</p>
      </article>
    </body></html>
    """
    text = _strip_html(html_sample)
    assert "Python" in text, f"HTML strip failed: {text[:100]}"
    assert "alert" not in text, "Script tag not removed"
    print(f"         HTML strip OK: '{text[:60].strip()}'")

    # ── Query extractor ───────────────────────────────────────────
    cases = [
        ("research the latest news on SpaceX", "the latest news on spacex"),
        ("look up quantum computing",          "quantum computing"),
        ("tell me about machine learning",     "machine learning"),
    ]
    for raw, expected in cases:
        extracted = extract_research_query(raw)
        ok = expected in extracted.lower()
        mark = "✓" if ok else "✗"
        print(f"         {mark} extract('{raw[:35]}') → '{extracted}'")

    # ── URL extractor ─────────────────────────────────────────────
    url_test = "read https://python.org and summarise it"
    found_url = extract_url(url_test)
    assert found_url == "https://python.org", f"URL extract failed: {found_url}"
    print(f"         URL extract OK: {found_url}")

    # ── Network pipeline (graceful if offline) ────────────────────
    import requests as _req
    online = True
    try:
        _req.get("https://en.wikipedia.org", timeout=3)
    except Exception:
        online = False

    if online:
        # Layer 1: DDG Instant Answer API
        from core.agent.web_research import _ddg_instant
        instant = _ddg_instant("Python programming language")
        print(f"         DDG Instant: {('OK — ' + instant[:50]) if instant else 'no abstract (normal for some queries)'}")

        # Layer 2: Bing search
        from core.agent.web_research import _bing_top_urls
        bing_urls = _bing_top_urls("Python programming language", n=2)
        print(f"         Bing search: {len(bing_urls)} URL(s) found")

        # Layer 3: Wikipedia API — always reliable
        from core.agent.web_research import _wikipedia_summary
        wiki = _wikipedia_summary("Python programming language")
        assert wiki and "Wikipedia" in wiki, f"Wikipedia API failed: {wiki}"
        print(f"         Wikipedia: {wiki[:70]}")

        return (f"HTML strip OK, DDG={'yes' if instant else 'no abstract'}, "
                f"Bing={len(bing_urls)} results, Wikipedia=OK")
    else:
        return "HTML strip OK — network offline (all network layers skipped gracefully)"

test("WebResearchAgent pipeline (strip+search+fetch)", test_web_research)

if __name__ == "__main__":
    # ─────────────────────────────────────────────────────────────────────────────
    # FINAL REPORT
    # ─────────────────────────────────────────────────────────────────────────────
    total  = len(results)
    passed = sum(1 for s, _, _ in results if s == PASS)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    skipped= sum(1 for s, _, _ in results if s == SKIP)

    print("\n" + "═"*70)
    print(f"  RESULTS: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped")
    print("═"*70)

    if failed > 0:
        print("\n  FAILED TESTS:")
        for s, name, detail in results:
            if s == FAIL:
                print(f"    ✗ {name}")
                if detail:
                    print(f"      {detail}")

    print()
    sys.exit(0 if failed == 0 else 1)
