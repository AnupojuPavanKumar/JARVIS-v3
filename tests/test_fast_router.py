import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=== JARVIS Fast Router Verification ===\n")

from core.intents.command_patterns import FastIntent, resolve_intent
print("[OK] command_patterns")

from core.router.fast_router import FastRouter, get_fast_router
router = get_fast_router()
print("[OK] fast_router")

# ── Intent resolution unit tests ────────────────────────────────────────────────
tests = [
    ("open vscode", "OPEN_APP", 0.95),
    ("launch chrome", "OPEN_APP", 0.95),
    ("volume up", "VOLUME_CONTROL", 0.95),
    ("volume down", "VOLUME_CONTROL", 0.95),
    ("mute", "VOLUME_CONTROL", 0.95),
    ("play music", "MEDIA_CONTROL", 0.95),
    ("pause music", "MEDIA_CONTROL", 0.95),
    ("next song", "MEDIA_CONTROL", 0.95),
    ("lock computer", "SYSTEM_CONTROL", 0.95),
    ("minimize window", "WINDOW_CONTROL", 0.85),
    ("search for python news", "WEB_SEARCH", 0.90),
    ("open file report.pdf", "FILE_OPEN", 0.85),
    ("close chrome", "CLOSE_APP", 0.90),
]

passed = 0
failed = 0
for cmd, expected_name, expected_conf in tests:
    intent = resolve_intent(cmd)
    is_det = intent.is_deterministic(0.85)
    expected_det = expected_conf >= 0.85

    ok_name = intent.name == expected_name
    ok_conf = abs(intent.confidence - expected_conf) < 0.1

    status = "PASS" if (ok_name and ok_conf) else "FAIL"
    if ok_name and ok_conf:
        passed += 1
    else:
        failed += 1

    print(f"  [{status}] '{cmd}' -> {intent.name} (conf={intent.confidence:.2f}, det={is_det})")
    if not ok_name:
        print(f"         Expected: {expected_name}")
    if not ok_conf:
        print(f"         Expected conf: {expected_conf}")

print(f"\n  Unit tests: {passed}/{passed+failed} passed")

# ── Full pipeline routing tests ────────────────────────────────────────────────
print("\n=== Full Pipeline Routing (deterministic vs AI) ===")
pipeline_tests = [
    # (command, expect_fallback_to_ai)
    ("open vscode", False),
    ("launch chrome", False),
    ("volume up", False),
    ("volume down", False),
    ("mute", False),
    ("unmute", False),
    ("play music", False),
    ("pause music", False),
    ("lock computer", False),
    ("minimize window", False),
    ("search for python news", False),
    ("close chrome", False),
    ("build a fullstack app", True),
    ("create a python script", True),
    ("analyze my data", True),
    ("hello jarvis", True),
    ("fix the bug in my code", True),
    ("tell me about space", True),
]
pipeline_passed = 0
for cmd, expect_ai in pipeline_tests:
    _intent, is_det = router.route(cmd)
    fell_to_ai = not is_det
    ok = fell_to_ai == expect_ai
    status = "PASS" if ok else "FAIL"
    if ok:
        pipeline_passed += 1
    print(f"  [{status}] '{cmd}' -> {'AI_FALLBACK' if fell_to_ai else 'DETERMINISTIC'} (expected={'AI_FALLBACK' if expect_ai else 'DETERMINISTIC'})")

print(f"  Pipeline: {pipeline_passed}/{len(pipeline_tests)} passed")

# ── App Registry ────────────────────────────────────────────────────────────────
print("\n[OK] app_registry")
from core.apps.app_registry import get_app_registry
reg = get_app_registry()
print(f"  Indexed apps: {reg.indexed_count}")

tests_reg = [("vscode", "Code.exe"), ("chrome", "chrome.exe"), ("notepad", "Notepad.exe")]
for name, expected_exe in tests_reg:
    path = reg.resolve(name)
    if path:
        has_exe = expected_exe.lower() in path.lower()
        if name == "chrome" and path.lower().endswith(".lnk"):
            has_exe = True
        status = "PASS" if has_exe else "FAIL"
        print(f"  [{status}] '{name}' -> {os.path.basename(path)}")
    else:
        print(f"  [SKIP] '{name}' -> not found")

# ── Executor (safe commands only — no side effects) ────────────────────────────
print("\n[OK] deterministic_executor")
from core.executor.deterministic_executor import get_executor, execute_fast
exec_obj = get_executor()
print("  Executor ready")

# Test that open_app returns correct response (no actual launch)
result = execute_fast("OPEN_APP", "notepad", "open notepad")
print(f"  execute_fast(OPEN_APP, notepad) -> '{result}'")
ok_exec = "opening" in result.lower() or "opening" in result.lower()
print(f"  [{'PASS' if ok_exec else 'FAIL'}] Response format")

# Test web_search returns correct response
result2 = execute_fast("WEB_SEARCH", "test query", "search for test query")
print(f"  execute_fast(WEB_SEARCH, 'test query') -> '{result2}'")

print("\n=== All verification complete ===")
