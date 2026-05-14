import os, re, ast, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

root = 'd:/JARVIS-v3'
all_files = {}
for dp, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if d not in ('venv','venv311','__pycache__','.git')]
    for f in files:
        if f.endswith('.py'):
            rel = os.path.relpath(os.path.join(dp,f), root).replace(os.sep,'/')
            try: all_files[rel] = open(os.path.join(dp,f), encoding='utf-8', errors='replace').read()
            except Exception: pass  # skip unreadable files

total_issues = []

# ── 6. UI internal call consistency ──────────────────────────────────────────
print('=== 6. UI INTERNAL CALL CONSISTENCY ===')
ui_src = all_files.get('ui/main_ui.py','')
calls  = set(re.findall(r'self\.(_\w+)\(', ui_src))
defs   = set(re.findall(r'def (_\w+)\(', ui_src))
missing = [c for c in calls if c not in defs and c not in ('__init__','__class__')]
if missing:
    for m in sorted(missing):
        print(f'  [WARN] self.{m}() called but not defined in main_ui.py')
        total_issues.append(m)
else:
    print('  CLEAN')

# ── 7. Brain internal consistency ─────────────────────────────────────────────
print()
print('=== 7. BRAIN INTERNAL CONSISTENCY ===')
brain_src = all_files.get('core/jarvis_brain.py','')
calls_b   = set(re.findall(r'self\.(_\w+)\(', brain_src))
defs_b    = set(re.findall(r'def (_\w+)\(', brain_src))
attrs_b   = set(re.findall(r'self\.(_\w+)\s*=', brain_src))
missing_b = [c for c in calls_b if c not in defs_b]
if missing_b:
    for m in sorted(missing_b):
        print(f'  [WARN] self.{m}() called but not defined in brain (may be inherited)')
        total_issues.append(m)
else:
    print('  CLEAN')

# ── 8. Non-daemon threads in key files ────────────────────────────────────────
print()
print('=== 8. NON-DAEMON THREADS ===')
key = ['core/jarvis_brain.py','core/speech_engine.py','core/wake_word.py',
       'core/system_watcher.py','core/episodic_memory.py','main.py',
       'ui/main_ui.py','ui/stats_window.py']
for rel in key:
    if rel not in all_files: continue
    src = all_files[rel]
    lines = src.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if 'threading.Thread(' in line and 'daemon=True' not in line:
            # Check next 3 lines for daemon
            window = ' '.join(lines[i:i+4])
            if 'daemon=True' not in window and 'daemon = True' not in window:
                bad.append(f'L{i+1}: {line.strip()[:70]}')
    if bad:
        print(f'  [WARN] {rel}: {len(bad)} non-daemon thread(s)')
        for b in bad[:2]: print(f'    {b}')
        total_issues.extend(bad)
    else:
        print(f'  [OK]  {rel}')

# ── 9. QTimer() without parent (minor leak in some cases) ─────────────────────
print()
print('=== 9. PARENTLESS QTimer() IN UI FILES ===')
for rel in ['ui/main_ui.py','ui/boot_sequence.py','ui/jarvis_core.py','ui/stats_window.py']:
    if rel not in all_files: continue
    src = all_files[rel]
    orphans = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if 'QTimer()' in stripped and 'QTimer.singleShot' not in stripped:
            if 'self._timer' in stripped or 'self._master' in stripped:
                continue  # these are assigned to self — fine
            orphans.append(f'L{i}: {stripped[:70]}')
    if orphans:
        print(f'  [WARN] {rel}: parentless QTimer:')
        for o in orphans[:3]: print(f'    {o}')
    else:
        print(f'  [OK]  {rel}')

# ── 10. core_v2 PACKAGE (Renamed to engines/intent_engine_v2) ────────────────
print()
print('=== 10. IntentEngineV2 PACKAGE ===')
if 'core/engines/intent_engine_v2.py' not in all_files:
    print('  [WARN] core/engines/intent_engine_v2.py missing — IntentEngineV2 import will fail')
    total_issues.append('intent_engine_v2.py')
else:
    print('  [OK]  core/engines/intent_engine_v2.py exists')


# ── 11. command_engine.py at root — check key methods exist ──────────────────
print()
print('=== 11. command_engine.py INTERFACE ===')
ce_src = all_files.get('command_engine.py','')
for method in ['execute','CommandEngine']:
    if method in ce_src:
        print(f'  [OK]  {method} found')
    else:
        print(f'  [MISS] {method} NOT found in command_engine.py')
        total_issues.append(method)

# ── 12. auth_window.py — check finished signal ────────────────────────────────
print()
print('=== 12. auth_window.py SIGNAL ===')
auth_src = all_files.get('ui/auth_window.py','')
for sig in ['authenticated','pyqtSignal']:
    if sig in auth_src:
        print(f'  [OK]  {sig}')
    else:
        print(f'  [MISS] {sig} not in auth_window.py')
        total_issues.append(sig)

# ── 13. Verify main.py boot sequence wiring ───────────────────────────────────
print()
print('=== 13. main.py BOOT WIRING ===')
main_src = all_files.get('main.py','')
checks = [
    ('boot.finished.connect', 'boot.finished signal connected'),
    ('reveal_ui',             'reveal_ui function defined'),
    ('registry.start_service("worker")', 'JarvisWorker thread started'),
    ('loop.run_forever()',    'Qt event loop started'),
    ('boot.show()',           'boot window shown'),
]
for pattern, desc in checks:
    found = pattern in main_src
    print(f'  {"[OK] " if found else "[MISS]"} {desc}')
    if not found: total_issues.append(pattern)

print()
print(f'=== SUMMARY: {len(total_issues)} issue(s) found ===')
if not total_issues:
    print('  ALL CLEAN')
