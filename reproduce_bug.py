
import sys
import os

# Add the project root to sys.path
sys.path.insert(0, os.getcwd())

from core.memory.project_memory import ProjectMemory
from core.system.hardware_sentinel import HardwareSentinel

print("Testing ProjectMemory...")
pm = ProjectMemory()
if hasattr(pm, 'record_job'):
    print("ProjectMemory has record_job")
else:
    print("ProjectMemory MISSING record_job")

print("\nTesting HardwareSentinel...")
hs = HardwareSentinel()
if hasattr(hs, '_get_vram_usage'):
    print("HardwareSentinel has _get_vram_usage")
else:
    print("HardwareSentinel MISSING _get_vram_usage")
