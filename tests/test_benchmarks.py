import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import time
import threading

print("=== JARVIS v3 Performance Benchmarks ===\n")

# Setup
from core.intents.trigger_scoring import get_trigger_scorer
from core.intents.lru_cache import get_lru_cache
from core.intents.command_decomposer import get_decomposer
from core.intents.shortcuts import get_shortcut_registry
from core.executor.execution_queue import get_execution_queue
from core.executor.execution_safety import get_safety_validator
from core.events import get_event_bus, Event
from core.resource import get_resource_monitor
from core.tracing import get_tracer

# ── Routing Latency ────────────────────────────────────────────────────────────
scorer = get_trigger_scorer()
cache = get_lru_cache()
decomposer = get_decomposer()

routing_times = []
for cmd in ["open vscode", "close chrome", "volume up", "switch to notepad", "open spotify"]:
    t0 = time.perf_counter()
    for _ in range(5):
        results = scorer.score(cmd)
        top = results[0] if results else None
    t1 = time.perf_counter()
    routing_times.append((t1 - t0) / 5 * 1000)
avg_routing = sum(routing_times) / len(routing_times)
print(f"1. Routing latency: {avg_routing:.2f}ms avg ({min(routing_times):.1f}-{max(routing_times):.1f}ms)")
print(f"   Budget: <50ms - {'PASS' if avg_routing < 50 else 'FAIL'}")

# ── Cache Lookup ────────────────────────────────────────────────────────────────
cache_times = []
for _ in range(20):
    cache.put("test_cmd", "test_result", confidence=0.9)
    t0 = time.perf_counter()
    for _ in range(10):
        cache.get("test_cmd")
    t1 = time.perf_counter()
    cache_times.append((t1 - t0) / 10 * 1000)
avg_cache = sum(cache_times) / len(cache_times)
print(f"\n2. Cache lookup: {avg_cache:.2f}ms avg")
print(f"   Budget: <5ms - {'PASS' if avg_cache < 5 else 'FAIL'}")

# ── Command Decomposition ──────────────────────────────────────────────────────
decomp_times = []
for cmd in ["open chrome and close notepad", "open vscode, also volume up", "close that and switch to spotify"]:
    t0 = time.perf_counter()
    for _ in range(5):
        decomposer.decompose(cmd)
    t1 = time.perf_counter()
    decomp_times.append((t1 - t0) / 5 * 1000)
avg_decomp = sum(decomp_times) / len(decomp_times)
print(f"\n3. Command decomposition: {avg_decomp:.2f}ms avg")
print(f"   Budget: <100ms - {'PASS' if avg_decomp < 100 else 'FAIL'}")

# ── Event Bus Dispatch ──────────────────────────────────────────────────────────
bus = get_event_bus()
bus_times = []
for _ in range(20):
    t0 = time.perf_counter()
    for _ in range(50):
        bus.emit(Event(event_type="bench.event", source="benchmark"))
    t1 = time.perf_counter()
    bus_times.append((t1 - t0) / 50 * 1000)
avg_bus = sum(bus_times) / len(bus_times)
print(f"\n4. Event bus dispatch: {avg_bus:.2f}ms per event")
print(f"   Budget: <10ms - {'PASS' if avg_bus < 10 else 'FAIL'}")

# ── Queue Insertion ────────────────────────────────────────────────────────────
q = get_execution_queue()
q_times = []
for i in range(50):
    t0 = time.perf_counter()
    q.submit("test", lambda: None, priority=5)
    t1 = time.perf_counter()
    q_times.append((t1 - t0) * 1000)
avg_queue = sum(q_times) / len(q_times)
print(f"\n5. Queue insertion: {avg_queue:.2f}ms avg")
print(f"   Budget: <5ms - {'PASS' if avg_queue < 5 else 'FAIL'}")

# ── Safety Validation ───────────────────────────────────────────────────────────
safety = get_safety_validator()
safety_times = []
test_paths = [r"C:\Users\Pavan2808\AppData\Local\Programs\Microsoft VS Code\Code.exe"] * 10
for _ in range(10):
    t0 = time.perf_counter()
    for p in test_paths:
        safety.validate_path(p)
    t1 = time.perf_counter()
    safety_times.append((t1 - t0) / len(test_paths) * 1000)
avg_safety = sum(safety_times) / len(safety_times)
print(f"\n6. Safety validation: {avg_safety:.2f}ms avg")
print(f"   Budget: <10ms - {'PASS' if avg_safety < 10 else 'FAIL'}")

# ── Thread Safety: Concurrent Queue Access ────────────────────────────────────
q2 = get_execution_queue()
q2.start()
errors = []
def submitter(idx):
    try:
        for i in range(20):
            q2.submit(f"test_{idx}", lambda: idx, priority=5)
    except Exception as e:
        errors.append(e)
threads = [threading.Thread(target=submitter, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
concurrency_ok = len(errors) == 0
print(f"\n7. Thread safety (concurrent access): {'PASS' if concurrency_ok else 'FAIL'}")
print(f"   Errors: {len(errors)}")

# ── Memory Stability ───────────────────────────────────────────────────────────
import gc
gc.collect()
import tracemalloc
tracemalloc.start()
snap1 = tracemalloc.take_snapshot()
for _ in range(100):
    scorer.score("open vscode")
    cache.put("cmd", "result", confidence=0.9)
    decomposer.decompose("open chrome and close notepad")
gc.collect()
snap2 = tracemalloc.take_snapshot()
top = snap2.compare_to(snap1, 'lineno')[:3]
tracemalloc.stop()
top = snap2.compare_to(snap1, 'lineno')[:3]
total_diff_kb = sum(s.size_diff for s in top) / 1024
print(f"\n8. Memory stability: {total_diff_kb:.1f}KB net over 100 iterations")
print(f"   Top diff: {[(str(s.traceback).split(chr(10))[-1].strip()[:60], round(s.size_diff/1024,1)) for s in top]}")

# ── Resource Monitor ───────────────────────────────────────────────────────────
mon = get_resource_monitor()
snap = mon.current_snapshot() or mon._sample()
st = mon.stats()
print(f"\n9. Resource monitor: CPU={st.get('avg_cpu_percent', 0):.1f}% RAM={st.get('avg_ram_percent', 0):.1f}%")
print(f"   GPU: {st.get('gpu_name', 'N/A')} ({st.get('avg_gpu_util', 0):.1f}% util)")
print(f"   Profile: {st.get('profile', 'unknown')}")

# ── Startup Profiling ──────────────────────────────────────────────────────────
t0 = time.perf_counter()
from core.platform import get_platform
from core.services.container import service_container
from core.capabilities import get_capability_registry
from core.architecture.validation import get_architecture_validator
t1 = time.perf_counter()
startup = (t1 - t0) * 1000
print(f"\n10. Startup profiling: {startup:.1f}ms to load all new modules")
print(f"    Budget: <500ms - {'PASS' if startup < 500 else 'FAIL'}")

print("\n=== Benchmark Complete ===")
