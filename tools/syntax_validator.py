import os
import py_compile
from pathlib import Path

def check_all():
    print("Starting Global Syntax Check...")
    root = Path(".")
    targets = [
        "main.py",
        "core/agent",
        "core/system",
        "core/engines/builders",
        "ui",
        "identity"
    ]
    
    failed = []
    passed = 0
    
    for t in targets:
        p = root / t
        if p.is_file():
            files = [p]
        else:
            files = list(p.rglob("*.py"))
            
        for f in files:
            if "venv" in str(f) or "__pycache__" in str(f) or "legacy" in str(f):
                continue
            try:
                py_compile.compile(str(f), doraise=True)
                passed += 1
            except Exception as e:
                print(f"FAILED: {f}\n  {e}")
                failed.append(f)
                
    print(f"\nCheck Complete: {passed} passed, {len(failed)} failed.")
    if failed:
        exit(1)

if __name__ == "__main__":
    check_all()
