# ui/stats_window.py — JARVIS FLOATING SYSTEM STATS WINDOW
import time
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QSizeGrip
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui  import (
    QColor, QPainter, QPen, QFont, QLinearGradient,
    QBrush, QCursor
)

from ui.styles import Theme, get_color

# ── Palette ──────────────────────────────────────────────────────────────────
_BG      = get_color(Theme.BG)
_PANEL   = get_color(Theme.DIM)
_BORDER  = QColor(249, 115, 22, 55) # Theme.ORANGE with alpha
_GOLD    = get_color(Theme.AMBER)
_GRN     = get_color(Theme.GREEN)
_YLW     = get_color(Theme.AMBER)
_RED     = get_color(Theme.RED)
_PUR     = get_color(Theme.PURPLE)
_CYAN    = get_color(Theme.CYAN)
_TXT     = get_color(Theme.TEXT)
_MUT     = get_color(Theme.MUTED)

_SS = f"""
QWidget {{ background: transparent; color: {Theme.TEXT};
          font-family: 'Share Tech Mono', 'Consolas', monospace; }}
QLabel  {{ background: transparent; }}
QPushButton {{
    background: rgba(249,115,22,10); border: 1px solid rgba(249,115,22,60);
    color: {Theme.ORANGE}; font-size: 9px; padding: 2px 7px; border-radius: 2px;
}}
QPushButton:hover  {{ background: rgba(249,115,22,30); color: {Theme.GOLD}; }}
QPushButton:pressed{{ background: rgba(249,115,22,55); }}
"""

class _Bar(QWidget):
    def __init__(self, label: str, color: QColor = _GOLD, parent=None):
        super().__init__(parent)
        self._label = label; self._color = color
        self._value = 0.0; self._text  = "—"
        self.setFixedHeight(26)
    def set_value(self, pct: float, text: str = ""):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text or f"{pct:.0f}%"; self.update()
    def set_color(self, color: QColor):
        self._color = color; self.update()
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold)); p.setPen(QPen(_MUT))
        lw = 72; p.drawText(0, 0, lw, H, Qt.AlignmentFlag.AlignVCenter, self._label)
        bx, bw = lw + 8, W - lw - 64
        
        # Background bar
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(30, 20, 10, 100)))
        p.drawRect(bx, H // 2 - 3, bw, 6)
        
        # Bit-block segments
        seg_w = 4; gap = 2
        num_segs = bw // (seg_w + gap)
        active_segs = int(num_segs * self._value / 100)
        
        for i in range(num_segs):
            x = bx + i * (seg_w + gap)
            if i < active_segs:
                p.setBrush(QBrush(self._color))
                p.setOpacity(0.9)
            else:
                p.setBrush(QBrush(QColor(255,255,255,20)))
                p.setOpacity(0.3)
            p.drawRect(x, H // 2 - 3, seg_w, 6)
        p.setOpacity(1.0)
                
        p.setPen(QPen(self._color))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.drawText(W - 52, 0, 52, H, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._text)

class _StatusDot(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label; self._value = "—"; self._color = _GRN
        self.setFixedHeight(20)
    def set(self, value: str, ok: bool = True):
        self._value = value; self._color = _GRN if ok else _RED; self.update()
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setFont(QFont("Consolas", 8))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(self._color))
        p.drawEllipse(2, H // 2 - 3, 6, 6)
        # Glow
        glow = QRadialGradient(5, H//2, 6)
        glow.setColorAt(0, QColor(self._color.red(), self._color.green(), self._color.blue(), 100))
        glow.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(QBrush(glow)); p.drawEllipse(-1, H//2-6, 12, 12)

        p.setPen(QPen(_MUT)); p.drawText(16, 0, 80, H, Qt.AlignmentFlag.AlignVCenter, self._label)
        p.setPen(QPen(self._color)); p.drawText(100, 0, W - 100, H, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._value)

class StatsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(320, 420)
        self._dragging = False; self._drag_pos = QPoint(); self._minimized = False; self._pinned = False
        self.setStyleSheet(_SS); self._build()
        self._timer = QTimer(self); self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _build(self):
        root = QVBoxLayout(self); root.setContentsMargins(5, 5, 5, 5); root.setSpacing(0)
        self._title_bar = self._make_title_bar(); root.addWidget(self._title_bar)
        self._content = QWidget(); self._content.setObjectName("stats_content")
        self._content.setStyleSheet(f"#stats_content {{ background: {Theme.GLASS_PANEL}; border: 1px solid rgba(249,115,22,60); border-top: none; border-radius: 0 0 8px 8px; }}")
        cl = QVBoxLayout(self._content); cl.setContentsMargins(15, 12, 15, 12); cl.setSpacing(6)
        self._b_cpu = _Bar("CPU", _CYAN); self._b_ram = _Bar("RAM", _AMB); self._b_vram = _Bar("VRAM", _PUR)
        self._b_gpu = _Bar("GPU UTIL", _PUR); self._b_bat = _Bar("BATTERY", _GRN)
        for b in (self._b_cpu, self._b_ram, self._b_vram, self._b_gpu, self._b_bat): cl.addWidget(b)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet("background: rgba(249,115,22,40);"); cl.addWidget(sep)
        self._d_ollama = _StatusDot("OLLAMA SERVICE"); self._d_docker = _StatusDot("DOCKER ENGINE")
        for d in (self._d_ollama, self._d_docker): cl.addWidget(d)
        root.addWidget(self._content)

    def _make_title_bar(self) -> QWidget:
        bar = QWidget(); bar.setFixedHeight(36); bar.setStyleSheet(f"background: rgba(249,115,22,25); border: 1px solid rgba(249,115,22,80); border-radius: 8px 8px 0 0;")
        lay = QHBoxLayout(bar); lay.setContentsMargins(12, 0, 10, 0); lay.setSpacing(6)
        title = QLabel("⚡ TACTICAL_MONITOR"); title.setFont(QFont("Consolas", 9, QFont.Weight.Bold)); title.setStyleSheet(f"color:{Theme.ORANGE};letter-spacing:1px;"); lay.addWidget(title); lay.addStretch()
        cls = QPushButton("✕"); cls.setFixedSize(22, 22); cls.setStyleSheet("QPushButton{background:rgba(239,68,68,30);border:1px solid rgba(239,68,68,80);color:#ef4444;border-radius:3px;}QPushButton:hover{background:#ef4444;color:#fff;}"); cls.clicked.connect(self.hide); lay.addWidget(cls)
        bar.mousePressEvent = self._title_mouse_press; bar.mouseMoveEvent = self._title_mouse_move
        return bar


    def _title_mouse_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True; self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def _title_mouse_move(self, e):
        if self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
    def mouseReleaseEvent(self, e): self._dragging = False

    def _refresh(self):
        from core.system.hardware_sentinel import get_hardware_sentinel
        sentinel = get_hardware_sentinel()
        if not sentinel: return
        s = sentinel.get_stats()
        self._b_cpu.set_value(s["cpu"]); self._b_ram.set_value(s["ram"])
        self._b_vram.set_value(s["vram_pct"], s["vram_mb"]); self._b_gpu.set_value(s["gpu_util"])
        if s["battery"]:
            self._b_bat.set_value(s["battery"]["percent"], f"{'⚡' if s['battery']['plugged'] else '🔋'}{s['battery']['percent']:.0f}%")
        self._d_ollama.set("ONLINE" if s["ollama_online"] else "OFFLINE", s["ollama_online"])
        self._d_docker.set("ACTIVE" if s["docker_online"] else "OFFLINE", s["docker_online"])

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(245, 158, 11, 18), 6)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 5, 5)

_instance = None
def get_stats_window(parent=None) -> 'StatsWindow':
    global _instance
    if _instance is None: _instance = StatsWindow(parent)
    return _instance
