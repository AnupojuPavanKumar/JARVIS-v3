# ui/jarvis_desktop/command_bar.py — JARVIS COMMAND BAR & ARC REACTOR
"""
Command bar with glowing voice button, holographic input field,
and arc-reactor style bottom center module.
"""
import math
import random
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal, QSize
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                          QRadialGradient, QPainterPath, QFont, QConicalGradient,
                          QIcon, QPixmap)


class ArcReactor(QWidget):
    """
    Arc-reactor style power module at the bottom center.
    Multi-layered glowing rings with rotating energy cells.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._cell_angles = [i * 60 + random.random() * 20 for i in range(6)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)
        self.setFixedSize(100, 50)

    def _tick(self):
        self._t += 0.03
        self._cell_angles = [(a + 1) % 360 for a in self._cell_angles]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # Outer glow
        for glow_r, alpha in [(50, 15), (40, 25), (30, 40)]:
            p.save()
            grad = QRadialGradient(cx, cy, glow_r)
            grad.setColorAt(0, QColor(0, 180, 255, alpha))
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), glow_r, glow_r * 0.4)
            p.restore()

        # Outer ring
        p.save()
        p.setPen(QPen(QColor(0, 150, 200, 120), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 38, 16)
        p.restore()

        # Inner ring
        p.save()
        p.setPen(QPen(QColor(0, 180, 240, 150), 1.5))
        p.drawEllipse(QPointF(cx, cy), 28, 12)
        p.restore()

        # Core glow
        core_glow = QRadialGradient(cx, cy, 15)
        core_glow.setColorAt(0, QColor(200, 240, 255, 220))
        core_glow.setColorAt(0.4, QColor(0, 180, 255, 180))
        core_glow.setColorAt(1, QColor(0, 80, 150, 0))
        p.setBrush(QBrush(core_glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 15, 6)

        # Energy cells
        for angle in self._cell_angles:
            rad = math.radians(angle)
            x = cx + 28 * math.cos(rad)
            y = cy + 12 * math.sin(rad)
            pulse = 0.5 + 0.5 * math.sin(self._t * 3 + angle * 0.05)
            r = 3 + pulse * 1.5
            # Cell glow
            cell_grad = QRadialGradient(x, y, r * 2)
            cell_grad.setColorAt(0, QColor(100, 230, 255, int(200 * pulse)))
            cell_grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(cell_grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), r * 2, r * 2)
            # Cell core
            p.setBrush(QBrush(QColor(180, 240, 255, int(200 * pulse))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), r * 0.6, r * 0.6)


class VoiceButton(QWidget):
    """Glowing voice activation button with pulse animation."""
    clicked = pyqtSignal()
    speaking = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = 0.0
        self._active = False
        self._speaking = False
        self._pulse_t = 0.0
        self.setFixedSize(52, 52)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_speaking(self, speaking: bool):
        self._speaking = speaking
        self.update()

    def enterEvent(self, _):
        self._hover = 1.0

    def leaveEvent(self, _):
        self._hover = 0.0

    def mousePressEvent(self, _):
        self._active = not self._active
        self._speaking = self._active
        self.clicked.emit()
        self.speaking.emit(self._speaking)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = 20

        pulse = 0.5 + 0.5 * math.sin(self._pulse_t * (4 if self._speaking else 2))
        self._pulse_t += 0.08

        # Pulse ring
        if self._speaking:
            p.save()
            p.setOpacity(pulse * 0.4)
            p.setPen(QPen(QColor(0, 220, 255, 200), 1.5))
            p.drawEllipse(QPointF(cx, cy), r + 6 + pulse * 8, r + 6 + pulse * 8)
            p.restore()

        # Hover glow
        if self._hover > 0.01:
            p.save()
            p.setOpacity(self._hover * 0.3)
            p.setBrush(QBrush(QColor(0, 180, 255, 80)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), r + 4, r + 4)
            p.restore()

        # Outer ring
        p.save()
        color = QColor(0, 200, 255, 200 if self._active else 150)
        pen = QPen(color, 2.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.restore()

        # Inner gradient
        inner = QRadialGradient(cx, cy - 4, r * 0.7)
        inner.setColorAt(0, QColor(60, 180, 240, 220))
        inner.setColorAt(1, QColor(0, 80, 150, 150))
        p.setBrush(QBrush(inner))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r - 2, r - 2)

        # Microphone icon (simplified)
        p.save()
        p.setPen(QPen(QColor(220, 245, 255, 220), 1.5))
        # Mic body
        p.drawArc(int(cx - 4), int(cy - 10), 8, 12, 0 * 16, 180 * 16)
        p.drawLine(int(cx - 4), int(cy - 5), int(cx - 6), int(cy + 2))
        p.drawLine(int(cx + 4), int(cy - 5), int(cx + 6), int(cy + 2))
        p.drawLine(int(cx - 6), int(cy + 2), int(cx + 6), int(cy + 2))
        p.restore()


class CommandBar(QWidget):
    """
    Futuristic command input with glowing borders and voice button.
    """
    command_submitted = pyqtSignal(str)
    voice_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim_t = 0.0
        self._glow_progress = 0.0
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._anim_t += 0.03
        self.update()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        # Voice button
        self._voice_btn = VoiceButton()
        self._voice_btn.clicked.connect(lambda: self._voice_btn.set_speaking(not self._voice_btn._speaking))
        self._voice_btn.speaking.connect(self.voice_toggled)
        layout.addWidget(self._voice_btn)

        # Input field
        self._input = QLineEdit()
        self._input.setFont(QFont("Segoe UI", 13))
        self._input.setPlaceholderText("Command JARVIS...")
        self._input.setStyleSheet("""
            QLineEdit {
                background: rgba(10, 20, 40, 180);
                border: 1px solid rgba(0, 160, 220, 80);
                border-radius: 10px;
                padding: 8px 16px;
                color: rgba(200, 230, 255, 220);
                selection-background-color: rgba(0, 180, 255, 60);
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 200, 255, 160);
                background: rgba(15, 30, 55, 200);
            }
            QLineEdit::placeholder {
                color: rgba(100, 150, 200, 120);
            }
        """)
        self._input.setMinimumHeight(40)
        self._input.returnPressed.connect(self._on_submit)
        layout.addWidget(self._input, 1)

        # Arc reactor
        self._reactor = ArcReactor()
        layout.addWidget(self._reactor)

    def _on_submit(self):
        text = self._input.text().strip()
        if text:
            self.command_submitted.emit(text)
            self._input.clear()

    def paintEvent(self, _):
        self._glow_progress = 0.5 + 0.5 * math.sin(self._anim_t)
        self._anim_t += 0.03
