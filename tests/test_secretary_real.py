import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

async def test_secretary_real():
    print("=== JARVIS-V3 SECRETARY TEST ===")
    
    from core.agent.jarvis_brain import JarvisBrain
    brain = JarvisBrain("guest")
    
    # We wait for the bootstrapper to finish (simulation)
    print("[Test] Waiting for engines to bootstrap...")
    await asyncio.sleep(5)
    
    # 1. Test SMS/Call Intent
    command = "Text +1234567890 that I am busy"
    print(f"\n[Command]: {command}")
    
    # We use process_async to see the full pipeline
    result = await brain.process_async(command)
    print(f"\n[JARVIS Response]:\n{result}")

    # 2. Test WhatsApp Intent
    command = "Open WhatsApp and message Thomas"
    print(f"\n[Command]: {command}")
    
    result = await brain.process_async(command)
    print(f"\n[JARVIS Response]:\n{result}")

if __name__ == "__main__":
    asyncio.run(test_secretary_real())
