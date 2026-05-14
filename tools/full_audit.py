"""
JARVIS Full Codebase Audit - finds every crash risk in every .py file.
Run: venv311\Scripts\python.exe tools\full_audit.py
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import os, ast, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"venv311", "venv", ".git", "__pycache__", "vosk-model", "node_modules", "memory", "build", "generated"}

issues = []

def scan(path, rel):
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return

    lines = src.splitlines()

    # ── 1. bare time.sleep() in a function/method ──────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if re.match(r"time\.sleep\s*\(", stripped) and "# audit:ok" not in stripped:
            issues.append((rel, i, "BARE_SLEEP", stripped[:80]))

    # ── 2. threading.Event.wait() NOT inside try/except ────────────────────
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        issues.append((rel, e.lineno or 0, "SYNTAX_ERROR", str(e)))
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Expr):
            val = node.value
            # detect self._xxx.wait(...) or evt.wait(...)
            if (isinstance(val, ast.Call) and
                    isinstance(val.func, ast.Attribute) and
                    val.func.attr == "wait"):
                # check if it's inside a try block — simplistic but effective
                src_line = lines[node.lineno - 1].strip()
                if "try:" not in lines[max(0, node.lineno - 3):node.lineno]:
                    issues.append((rel, node.lineno, "UNGUARDED_WAIT", src_line[:80]))

    # ── 3. chromadb calls not inside a standalone thread ───────────────────
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if ("self._collection" in s or "_collection.count()" in s or
                "_collection.query(" in s or "_collection.upsert(" in s):
            # check no 'with _CHROMA_LOCK' on same or prev line
            ctx = " ".join(lines[max(0, i-3):i])
            if "_CHROMA_LOCK" not in ctx and "# audit:ok" not in s:
                issues.append((rel, i, "CHROMA_NO_LOCK", s[:80]))

    # ── 4. asyncio.run() — creates/destroys loop ───────────────────────────
    for i, line in enumerate(lines, 1):
        if re.search(r"\basyncio\.run\s*\(", line) and "# audit:ok" not in line:
            issues.append((rel, i, "ASYNCIO_RUN", line.strip()[:80]))

    # ── 5. daemon thread with no stop mechanism ─────────────────────────────
    for i, line in enumerate(lines, 1):
        if "daemon=True" in line and "Thread(" in line:
            # look for a stop flag somewhere in the file
            func_ctx = "\n".join(lines[max(0, i-2):i+2])
            if "stop" not in src.lower()[max(0, src.find(line)-200):src.find(line)+200]:
                issues.append((rel, i, "DAEMON_NO_STOP", line.strip()[:80]))

    # ── 6. bare except: pass ───────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        if re.match(r"\s*except\s*:\s*(pass\s*)?$", line):
            issues.append((rel, i, "BARE_EXCEPT", line.strip()[:80]))

def walk():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                full = os.path.join(dirpath, fname)
                rel  = os.path.relpath(full, ROOT)
                scan(full, rel)

walk()

# ── Print grouped report ────────────────────────────────────────────────────
cats = {}
for rel, line, cat, snippet in issues:
    cats.setdefault(cat, []).append((rel, line, snippet))

PRIORITY = ["SYNTAX_ERROR", "ASYNCIO_RUN", "CHROMA_NO_LOCK",
            "BARE_SLEEP", "UNGUARDED_WAIT", "DAEMON_NO_STOP", "BARE_EXCEPT"]

print(f"\n{'='*70}")
print(f"  JARVIS FULL CODEBASE AUDIT — {sum(len(v) for v in cats.values())} issues in {len(cats)} categories")
print(f"{'='*70}\n")

for cat in PRIORITY:
    items = cats.pop(cat, [])
    if not items:
        continue
    print(f"[{cat}] — {len(items)} occurrences")
    for rel, line, snippet in items[:30]:   # cap at 30 per category
        print(f"   {rel}:{line}  =>  {snippet}")
    if len(items) > 30:
        print(f"   ... and {len(items)-30} more")
    print()

for cat, items in cats.items():
    print(f"[{cat}] — {len(items)} occurrences")
    for rel, line, snippet in items[:15]:
        print(f"   {rel}:{line}  =>  {snippet}")
    print()

print(f"{'='*70}")
print("DONE")
