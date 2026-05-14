# ui/jarvis_desktop/panels.py — JARVIS DESKTOP PANELS
"""
System Health, Runtime Status, Context Awareness, Live Narratives panels.
"""
import math
import random
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                          QRadialGradient, QFont, QPainterPath, QConicalGradient)
from ui.jarvis_desktop.glassmorphic_panel import GlassPanel, draw_glass_panel, glow_color, accent_color


def _draw_circular_indicator(p, cx, cy, r, value, color, label, unit="",
                              bg_color=None, line_width=4.0):
    """Draw a circular gauge indicator with value arc."""
    # Background track
    if bg_color:
        p.save()
        pen = QPen(QColor(bg_color), line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setOpacity(0.2)
        p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2),
                  90 * 16, -360 * 16)
        p.restore()

    # Value arc
    p.save()
    span = -int(value * 360 * 16)
    pen = QPen(color, line_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setOpacity(0.9)
    p.drawArc(int(cx - r), int(cy - r), int(r * 2), int(r * 2),
              90 * 16, span)
    p.restore()

    # Center value
    p.save()
    p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    p.setPen(QColor(220, 240, 255))
    p.drawText(int(cx - 16), int(cy - 8), 32, 16,
               Qt.AlignmentFlag.AlignCenter, f"{value * 100:.0f}")
    p.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
    p.setPen(QColor(140, 170, 200))
    p.drawText(int(cx - 16), int(cy + 6), 32, 12,
               Qt.AlignmentFlag.AlignCenter, unit)
    p.restore()

    # Label
    p.save()
    p.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
    p.setPen(QColor(100, 150, 200, 180))
    p.drawText(int(cx - 20), int(cy + r + 10), 40, 12,
               Qt.AlignmentFlag.AlignCenter, label)
    p.restore()


class SystemHealthPanel(GlassPanel):
    """Left-center panel: AI reasoning, voice, memory, automation, vision, web."""

    def __init__(self, parent=None):
        super().__init__(parent, fill_alpha=20, glow_strength=0.2,
                         corner_radius=10, animated=True)
        self._health = {
            "AI": 0.92, "VOICE": 0.88, "MEM": 0.75,
            "AUTO": 0.95, "VIS": 0.60, "WEB": 0.85,
        }
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_health)
        self._timer.start(3000)

    def _update_health(self):
        # Simulate slow drift
        for k in self._health:
            delta = (random.random() - 0.5) * 0.03
            self._health[k] = max(0.3, min(1.0, self._health[k] + delta))
        self.update()

    def _paint_content(self, p: QPainter, rect):
        self._draw_health_indicators(p, rect)

    def _draw_health_indicators(self, p, rect):
        items = list(self._health.items())
        cols = 3
        cw = rect.width() / cols
        for i, (label, value) in enumerate(items):
            col = i % cols
            row = i // cols
            cx = rect.left() + col * cw + cw / 2
            cy = rect.top() + 25 + row * 65
            r = 16

            color = QColor(0, 200, 255) if value > 0.8 else (
                QColor(200, 180, 0) if value > 0.5 else QColor(220, 80, 80))
            _draw_circular_indicator(p, cx, cy, r, value, color,
                                     label, bg_color="0,60,100", line_width=3.5)


class RuntimeStatusPanel(GlassPanel):
    """Right-top panel: CPU, RAM, GPU, VRAM, TEMP, NET circular gauges."""

    def __init__(self, parent=None):
        super().__init__(parent, fill_alpha=20, glow_strength=0.2,
                         corner_radius=10, animated=True)
        self._metrics = {
            "CPU": 0.45, "RAM": 0.62, "GPU": 0.38,
            "VRAM": 0.55, "TEMP": 0.42, "NET": 0.30,
        }
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_metrics)
        self._timer.start(2000)

    def _update_metrics(self):
        for k in self._metrics:
            delta = (random.random() - 0.5) * 0.05
            self._metrics[k] = max(0.1, min(1.0, self._metrics[k] + delta))
        self.update()

    def _paint_content(self, p: QPainter, rect):
        items = list(self._metrics.items())
        cols = 3
        cw = rect.width() / cols
        for i, (label, value) in enumerate(items):
            col = i % cols
            row = i // cols
            cx = rect.left() + col * cw + cw / 2
            cy = rect.top() + 20 + row * 55
            r = 14
            color = QColor(0, 180, 255) if value < 0.8 else QColor(220, 120, 40) if value < 0.95 else QColor(230, 60, 60)
            _draw_circular_indicator(p, cx, cy, r, value, color, label,
                                     bg_color="0,50,80", line_width=3.0)


class ContextAwarenessPanel(GlassPanel):
    """Right-center panel: current focus, active file, project, state."""

    def __init__(self, parent=None):
        super().__init__(parent, fill_alpha=18, glow_strength=0.15,
                         corner_radius=10, animated=False)
        self._data = {
            "FOCUS": "Python development",
            "FILE": "jarvis_brain.py",
            "PROJECT": "JARVIS-v3",
            "STATE": "ACTIVE",
            "DIR": "D:/JARVIS-v3/core/agent",
        }

    def set_context(self, focus="", file="", project="", state="", directory=""):
        if focus: self._data["FOCUS"] = focus
        if file: self._data["FILE"] = file
        if project: self._data["PROJECT"] = project
        if state: self._data["STATE"] = state
        if directory: self._data["DIR"] = directory
        self.update()

    def _paint_content(self, p: QPainter, rect):
        labels = list(self._data.keys())
        y = rect.top() + 18
        for label, value in self._data.items():
            # Label
            p.save()
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Medium))
            p.setPen(QColor(80, 130, 170, 180))
            p.drawText(int(rect.left() + 12), int(y), label)
            p.restore()

            # Value
            p.save()
            p.setFont(QFont("Consolas", 9, QFont.Weight.Normal))
            p.setPen(QColor(180, 220, 255))
            # Truncate long values
            display = value if len(value) <= 28 else value[:25] + "..."
            p.drawText(int(rect.left() + 12), int(y + 14), display)
            p.restore()

            # Separator line
            p.save()
            p.setPen(QPen(QColor(0, 100, 150, 30), 0.5))
            p.drawLine(int(rect.left() + 8), int(y + 18),
                       int(rect.right() - 8), int(y + 18))
            p.restore()

            y += 32

    def minimumHeightHint(self):
        return 160


class LiveNarrativesPanel(GlassPanel):
    """Right-lower panel: human-readable runtime insights."""

    def __init__(self, parent=None):
        super().__init__(parent, fill_alpha=18, glow_strength=0.15,
                         corner_radius=10, animated=False)
        self._narratives = [
            ("INFO", "Runtime stable — 2h 14m uptime"),
            ("WARN", "VRAM at 55% — consider cleanup"),
            ("INFO", "Voice capability nominal"),
            ("RECOVERY", "Ollama recovered — AI reasoning restored"),
        ]

    def add_narrative(self, severity: str, text: str):
        self._narratives.insert(0, (severity, text))
        self._narratives = self._narratives[:6]
        self.update()

    def _paint_content(self, p: QPainter, rect):
        sev_colors = {
            "INFO": QColor(0, 180, 220),
            "WARN": QColor(220, 180, 0),
            "ERROR": QColor(230, 70, 70),
            "RECOVERY": QColor(0, 220, 140),
            "SUMMARY": QColor(150, 200, 255),
        }
        y = rect.top() + 14
        for sev, text in self._narratives:
            color = sev_colors.get(sev, QColor(150, 180, 200))
            # Severity dot
            p.save()
            p.setBrush(QBrush(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.setOpacity(0.9)
            p.drawEllipse(QPointF(rect.left() + 14, y + 3), 4, 4)
            p.restore()
            # Text
            p.save()
            p.setFont(QFont("Segoe UI", 8, QFont.Weight.Normal))
            p.setPen(QColor(180, 210, 240))
            p.drawText(int(rect.left() + 24), int(y + 7),
                       int(rect.width() - 30), 14,
                       Qt.TextFlag.TextWordWrap, text)
            p.restore()
            y += 22

    def minimumHeightHint(self):
        return 120




class PressureVisualization(GlassPanel):
    """Full-width pressure visualization with radial graph."""

    def __init__(self, parent=None):
        super().__init__(parent, fill_alpha=15, glow_strength=0.15,
                         corner_radius=10, animated=True)
        self._level = "NOMINAL"
        self._suppressed = []

    def set_level(self, level, suppressed=None):
        self._level = level
        self._suppressed = suppressed or []
        self.update()

    def _paint_content(self, p: QPainter, rect):
        cx = rect.width() / 2
        cy = rect.top() + 25
        r = min(rect.width() * 0.35, 50)

        level_colors = {
            "NOMINAL": QColor(0, 200, 130),
            "ELEVATED": QColor(200, 200, 0),
            "HIGH": QColor(230, 140, 0),
            "CRITICAL": QColor(230, 80, 40),
            "EMERGENCY": QColor(220, 40, 40),
        }
        color = level_colors.get(self._level, level_colors["NOMINAL"])

        # Draw radial gauge
        p.save()
        # Background arc
        for i in range(8):
            angle = i * 45
            rad = math.radians(angle - 90)
            x1 = cx + (r - 8) * math.cos(rad)
            y1 = cy + (r - 8) * math.sin(rad)
            x2 = cx + (r + 8) * math.cos(rad)
            y2 = cy + (r + 8) * math.sin(rad)
            p.setPen(QPen(QColor(0, 60, 90, 80), 3))
            p.drawArc(int(cx - r - 8), int(cy - r - 8),
                      int((r + 8) * 2), int((r + 8) * 2),
                      int(angle - 90 + 10) * 16, -40 * 16)
        p.restore()

        # Active level arc
        level_map = {"NOMINAL": 1, "ELEVATED": 2, "HIGH": 3, "CRITICAL": 4, "EMERGENCY": 5}
        active = level_map.get(self._level, 0)
        for i in range(active):
            angle = i * 45
            rad = math.radians(angle - 90)
            x1 = cx + (r - 6) * math.cos(rad)
            y1 = cy + (r - 6) * math.sin(rad)
            x2 = cx + (r + 6) * math.cos(rad)
            y2 = cy + (r + 6) * math.sin(rad)
            p.save()
            p.setPen(QPen(color, 4))
            p.drawArc(int(cx - r - 6), int(cy - r - 6),
                      int((r + 6) * 2), int((r + 6) * 2),
                      int(angle - 90 + 10) * 16, -40 * 16)
            p.restore()

        # Center text
        p.save()
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(int(cx - 40), int(cy + 4), 80, 16,
                   Qt.AlignmentFlag.AlignCenter, self._level)
        p.restore()

        # Suppressed systems
        if self._suppressed:
            y_text = cy + r + 18
            p.save()
            p.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
            p.setPen(QColor(200, 150, 80, 180))
            p.drawText(int(cx - 60), int(y_text), 120, 12,
                       Qt.AlignmentFlag.AlignCenter,
                       "SUPPRESSED: " + ", ".join(self._suppressed[:3]))
            p.restore()