import time
import os
import json
import sys
import psutil

# Add project root to path
sys.path.append("D:/JARVIS-v3")

from core.agent.agent import JarvisAgent
from core.providers.ollama_manager import OllamaManager

def get_vram_usage():
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return info.used / 1024**2  # MiB
    except:
        return 0

def run_audit():
    print("=== JARVIS-v3 PERFORMANCE AUDIT ===")
    print(f"Baseline VRAM: {get_vram_usage():.1f} MiB")
    
    agent = JarvisAgent(identity="owner")
    
    task = (
        "Research the current weather in New York and the latest news headline about it. "
        "Create a premium HTML/JS dashboard on my Desktop named 'WeatherDashboard.html' "
        "that displays this data with an elegant dark theme. Finally, verify it works by opening it."
    )
    
    print("\n[AUDIT] Starting Mission: Complex Dashboard Generation")
    start_time = time.time()
    
    # Run the agent
    result = agent.run(task)
    
    end_time = time.time()
    total_duration = end_time - start_time
    
    print("\n=== AUDIT RESULTS ===")
    print(f"Total Time: {total_duration:.2f}s")
    print(f"Final VRAM: {get_vram_usage():.1f} MiB")
    print(f"Result: {result}")
    
    # Check if file exists
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    target_file = os.path.join(desktop, "WeatherDashboard.html")
    if os.path.exists(target_file):
        print(f"Verification: SUCCESS (File created at {target_file})")
        with open(target_file, 'r', encoding='utf-8') as f:
            content_size = len(f.read())
        print(f"Payload Size: {content_size} bytes")
    else:
        print("Verification: FAILED (File not found on Desktop)")

if __name__ == "__main__":
    run_audit()
