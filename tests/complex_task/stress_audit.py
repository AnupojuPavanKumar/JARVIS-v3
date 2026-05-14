import time
import os
import json
import sys

# Add project root to path
sys.path.append("D:/JARVIS-v3")

from core.agent.agent import JarvisAgent

def get_vram_usage():
    try:
        from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo
        nvmlInit()
        handle = nvmlDeviceGetHandleByIndex(0)
        info = nvmlDeviceGetMemoryInfo(handle)
        return info.used / 1024**2  # MiB
    except:
        return 0

def run_audit():
    print("=== JARVIS-v3 STRESS AUDIT ===")
    print(f"Baseline VRAM: {get_vram_usage():.1f} MiB")
    
    agent = JarvisAgent(identity="owner")
    
    # MISSION: Deep research + Synthesis + UI Coding + Notification
    task = (
        "Perform deep web research on the current Bitcoin price and the 24-hour market sentiment. "
        "Synthesize this into a professional market report. "
        "Then, generate a high-end HTML dashboard on my Desktop named 'MarketReport.html' "
        "using a glassmorphism aesthetic and HSL gradients. "
        "Finally, notify me via push notification that it's ready and open the file."
    )
    
    print("\n[AUDIT] Starting Stress Mission: Deep Research & synthesis")
    start_time = time.time()
    
    # Run the agent
    result = agent.run(task)
    
    end_time = time.time()
    total_duration = end_time - start_time
    
    print("\n=== STRESS AUDIT RESULTS ===")
    print(f"Total Execution Time: {total_duration:.2f}s")
    print(f"Peak VRAM Reported: {get_vram_usage():.1f} MiB")
    print(f"Agent Final Reply: {result}")
    
    # Verification
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    target_file = os.path.join(desktop, "MarketReport.html")
    if os.path.exists(target_file):
        print(f"Payload Verification: SUCCESS (File created at {target_file})")
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"Lines of Code: {len(content.splitlines())}")
            if "glass" in content.lower() or "backdrop-filter" in content.lower():
                print("Style Verification: SUCCESS (Glassmorphism found)")
    else:
        print("Payload Verification: FAILED")

if __name__ == "__main__":
    run_audit()
