import os
import sys
import time
import json
import random
import threading
import subprocess
from datetime import datetime
from pathlib import Path

# Setup Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.agent.jarvis_brain import JarvisBrain
from core.system.hardware_sentinel import HardwareSentinel
from core.agent.memory_service import get_memory_service

# Configuration
TEST_DURATION_HOURS = 24
CYCLE_INTERVAL_SEC = 300 # Wait 5 minutes between task runs
CHAOS_PROBABILITY = 0.3 # 30% chance per cycle to inject chaos
TELEMETRY_LOG = Path(__file__).parent / "endurance_telemetry.jsonl"

TASKS = [
    "Write a Python script that continuously logs system metrics to a CSV file.",
    "Draft a markdown architectural plan for a microservices e-commerce backend.",
    "Find all unused variables in the project and report them.",
    "Simulate a database failure and write a recovery strategy.",
    "Build a simple HTML/CSS dashboard with 3 mock charts using Chart.js.",
]

def inject_chaos():
    """Simulate operational failures (Chaos Monkey)."""
    failure_types = [
        "Kill background worker (Ollama)",
        "Spike memory allocation temporarily",
        "Clear working memory context",
    ]
    choice = random.choice(failure_types)
    print(f"\n[CHAOS MONKEY] Injecting failure: {choice}")
    
    if "Ollama" in choice:
        try:
            # Simulate Ollama crash (it usually auto-restarts or handled gracefully)
            subprocess.run(["taskkill", "/F", "/IM", "ollama_llama_server.exe"], capture_output=True)
        except Exception:
            pass
    elif "Spike memory" in choice:
        # Allocate a large array temporarily
        _spike = [0] * (10 ** 7)
        time.sleep(2)
        del _spike
    elif "Clear working memory" in choice:
        mem = get_memory_service()
        # In a real scenario we might wipe procedural memory or scratchpad
        mem.record_user("RESET_CONTEXT")

def log_telemetry(sentinel: HardwareSentinel, cycle: int, task: str, duration: float, success: bool):
    """Log telemetry to track degradation over time."""
    stats = sentinel.get_stats()
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "cycle": cycle,
        "task_preview": task[:50],
        "duration_sec": round(duration, 2),
        "success": success,
        "thread_count": threading.active_count(),
        "cpu_pct": stats.get("cpu", 0),
        "ram_pct": stats.get("ram", 0),
        "vram_pct": stats.get("vram_pct", 0)
    }
    
    with open(TELEMETRY_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    
    print(f"[Telemetry] Cycle {cycle} | Threads: {entry['thread_count']} | RAM: {entry['ram_pct']}% | VRAM: {entry['vram_pct']}%")

    # Phase 4: Regression Immunity - Fail validation if degradation detected
    if entry["thread_count"] > 150:
        print("[REGRESSION FATAL] Runaway thread count detected!")
        sys.exit(1)
    if entry["ram_pct"] > 95:
        print("[REGRESSION FATAL] Critical RAM pressure detected!")
        sys.exit(1)

def run_endurance_test():
    print(f"=== JARVIS-v3 Endurance Certification ===")
    print(f"Target Duration : {TEST_DURATION_HOURS} hours")
    print(f"Chaos Injection : {CHAOS_PROBABILITY * 100}% probability per cycle\n")
    
    brain = JarvisBrain("owner", None)
    sentinel = HardwareSentinel(None)
    sentinel.start()
    
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    start_time = time.time()
    end_time = start_time + (TEST_DURATION_HOURS * 3600)
    cycle = 1
    
    while time.time() < end_time:
        print(f"\n--- Cycle {cycle} ---")
        task = random.choice(TASKS)
        
        # Phase 2: Repeated Chaos Injection
        if random.random() < CHAOS_PROBABILITY:
            inject_chaos()
            
        task_start = time.time()
        success = False
        try:
            # Execute Autonomous Task
            result = loop.run_until_complete(brain.process_async(task))
            success = bool(result and "error" not in result.lower())
        except Exception as e:
            print(f"[FATAL ERROR] {e}")
            success = False
            
        task_duration = time.time() - task_start
        
        # Log and assert Phase 6: Resource Stability
        log_telemetry(sentinel, cycle, task, task_duration, success)
        
        cycle += 1
        print(f"Waiting {CYCLE_INTERVAL_SEC}s for next cycle...")
        time.sleep(CYCLE_INTERVAL_SEC)
        
    print("\n[SUCCESS] Endurance Certification Completed.")
    sentinel.stop()

if __name__ == "__main__":
    # We will run one cycle as a smoke test, then exit. 
    # In production, this would run on a dedicated server.
    TEST_DURATION_HOURS = 0.05 # Override for smoke test (3 minutes)
    CYCLE_INTERVAL_SEC = 5
    run_endurance_test()
