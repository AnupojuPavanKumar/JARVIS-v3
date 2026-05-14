import sys, os
from unittest.mock import MagicMock

# Mock pynvml to avoid issues on systems without NVIDIA GPUs
sys.modules['pynvml'] = MagicMock()

# Ensure project root is in path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

def test_vector_memory():
    print("[Testing Vector Memory]")
    try:
        from core.tools.long_term_memory import LongTermMemory
        mem = LongTermMemory()
        print("  - Initialized")
        result = mem.commit_memory("test task", "pattern: use vite + react")
        print(f"  - Commit result: {result}")
        search = mem.search_memory("react vite frontend")
        print(f"  - Search result: {search[:100]}...")
        print("  [PASS] Vector Memory")
    except Exception as e:
        print(f"  [FAIL] Vector Memory: {e}")

def test_conversation_history():
    print("\n[Testing Conversation History]")
    try:
        from core.memory.conversation_history import get_history
        hist = get_history()
        print("  - Initialized")
        hist.add("user", "Hello Jarvis")
        hist.add("jarvis", "Hello sir")
        recent = hist.get_recent(2)
        print(f"  - Recent: {recent}")
        assert len(recent) == 2
        ok = hist.format_for_prompt(2)
        print(f"  - Formatted: {ok[:100]}...")
        print("  [PASS] Conversation History")
    except Exception as e:
        print(f"  [FAIL] Conversation History: {e}")

def test_proactive_engine():
    print("\n[Testing Proactive Engine]")
    try:
        from core.engines.proactive_engine import get_proactive_engine
        pe = get_proactive_engine()
        print("  - Initialized")
        pe.record_command("build a website")
        print("  - Command recorded")
        suggestions = pe.get_top_suggestions(1)
        print(f"  - Top suggestions: {suggestions}")
        print("  [PASS] Proactive Engine")
    except Exception as e:
        print(f"  [FAIL] Proactive Engine: {e}")

if __name__ == "__main__":
    test_vector_memory()
    test_conversation_history()
    test_proactive_engine()
