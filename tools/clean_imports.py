"""
Clean unused imports from UI files.
Only removes imports confirmed unused by the audit.
Verifies each file parses cleanly before and after.
"""
import ast, re, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CHANGES = {
    'ui/main_ui.py': [
        # Remove: math, random, QApplication, QThread, QSize, QLinearGradient, QPalette
        # Keep: everything actually used
        (r'import math, random, datetime, time, re, threading\n',
         'import datetime, time, re, threading\n'),
        (r'    QWidget, QVBoxLayout, QHBoxLayout, QLabel,\n    QLineEdit, QPushButton, QTextEdit, QFrame, QScrollArea, QSizePolicy,\n    QApplication\)',
         '    QWidget, QVBoxLayout, QHBoxLayout, QLabel,\n    QLineEdit, QPushButton, QTextEdit, QFrame, QScrollArea, QSizePolicy)'),
        (r'from PyQt6\.QtCore  import Qt, QTimer, QThread, pyqtSignal, QSize\n',
         'from PyQt6.QtCore  import Qt, QTimer, pyqtSignal\n'),
        (r'from PyQt6\.QtGui   import \(QPainter, QColor, QPen, QFont, QTextCursor,\n                            QLinearGradient, QPalette, QBrush\)\n',
         'from PyQt6.QtGui   import QPainter, QColor, QPen, QFont, QTextCursor, QBrush\n'),
    ],
    'ui/jarvis_core.py': [
        # Remove: QFont, QRadialGradient, QLinearGradient, QPolygonF
        (r'from PyQt6\.QtGui import \(QPainter, QColor, QPen, QBrush, QFont,\n                          QRadialGradient, QLinearGradient, QPainterPath, QPolygonF\)\n',
         'from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath\n'),
    ],
    'ui/boot_sequence.py': [
        # Remove: QLinearGradient, QPainterPath
        (r'from PyQt6\.QtGui     import \(QPainter, QColor, QPen, QBrush, QFont,\n                              QLinearGradient, QPainterPath\)\n',
         'from PyQt6.QtGui     import QPainter, QColor, QPen, QBrush, QFont\n'),
    ],
    'ui/stats_window.py': [
        # Remove: annotations, QScrollArea, QSize, QPalette, QMetaObject, Qt as _Qt
        (r'from __future__ import annotations\n\n',
         ''),
        (r'    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,\n    QPushButton, QSizeGrip, QScrollArea\n',
         '    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,\n    QPushButton, QSizeGrip\n'),
        (r'from PyQt6\.QtCore import Qt, QTimer, QPoint, QSize, pyqtSignal\n',
         'from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal\n'),
        (r'from PyQt6\.QtGui  import \(\n    QColor, QPainter, QPen, QFont, QLinearGradient,\n    QBrush, QPalette, QCursor\n\)\n',
         'from PyQt6.QtGui  import (\n    QColor, QPainter, QPen, QFont, QLinearGradient,\n    QBrush, QCursor\n)\n'),
    ],
}

root = 'd:/JARVIS-v3'
all_ok = True

for rel_path, patches in CHANGES.items():
    full = os.path.join(root, rel_path.replace('/', os.sep))
    try:
        with open(full, encoding='utf-8', errors='replace') as f:
            src = f.read()
    except FileNotFoundError:
        print(f'[MISS] {rel_path}')
        continue

    # Verify before
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f'[PRE-FAIL] {rel_path}: {e}')
        all_ok = False
        continue

    new_src = src
    applied = []
    for pattern, replacement in patches:
        result = re.sub(pattern, replacement, new_src, count=1)
        if result != new_src:
            applied.append(pattern[:50])
            new_src = result

    # Verify after
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f'[POST-FAIL] {rel_path}: {e} — skipping this file')
        all_ok = False
        continue

    if new_src != src:
        with open(full, 'w', encoding='utf-8') as f:
            f.write(new_src)
        print(f'[CLEANED] {rel_path}: {len(applied)} patches applied')
    else:
        print(f'[SKIP] {rel_path}: patterns not matched (may already be clean)')

print()
print('All OK' if all_ok else 'SOME FAILURES — review above')
