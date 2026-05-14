# ui/glassmorphic_panel.py — JARVIS GLASSMORPHIC PANEL BASE
"""
Base class for all JARVIS UI panels.
Provides glassmorphism styling with luminous borders, soft glow, and blur backdrop.
"""
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient, QPainterPath, QFont, QConicalGradient


def glass_color(alpha: int = 30) -> QColor:
    return QColor(20, 30, 50, alpha)


def glow_color() -> QColor:
    return QColor(0, 212, 255, 200)


def accent_color() -> QColor:
    return QColor(0, 191, 255)


def panel_border_color() -> QColor:
    return QColor(0, 180, 230, 100)


def text_color() -> QColor:
    return QColor(220, 235, 255)


def subtext_color() -> QColor:
    return QColor(140, 170, 200)


def draw_glass_panel(p, rect, border_alpha: int = 60, fill_alpha: int = 25,
                      corner_radius: float = 12.0, glow_strength: float = 0.3):
    """Draw a glassmorphic panel with border, gradient fill, and soft glow."""
    from PyQt6.QtCore import QRectF
    rect_f = QRectF(rect)
    path = QPainterPath()
    path.addRoundedRect(rect_f, corner_radius, corner_radius)

    # Outer glow
    p.save()
    p.setOpacity(glow_strength)
    glow_path = QPainterPath()
    glow_path.addRoundedRect(rect_f.adjusted(-4, -4, 4, 4), corner_radius + 2, corner_radius + 2)
    glow_brush = QBrush(QColor(0, 180, 255, 60))
    p.fillPath(glow_path, glow_brush)
    p.restore()

    # Fill
    p.save()
    gradient = QLinearGradient(rect_f.topLeft(), rect_f.bottomRight())
    gradient.setColorAt(0, QColor(15, 25, 45, fill_alpha))
    gradient.setColorAt(1, QColor(8, 15, 30, fill_alpha))
    p.fillPath(path, QBrush(gradient))
    p.restore()

    # Border
    p.save()
    border_pen = QPen(panel_border_color().lighter(120))
    border_pen.setWidthF(0.8)
    p.setPen(border_pen)
    p.drawPath(path)
    p.restore()


def draw_section_label(p, text: str, x: float, y: float, font_size: int = 9):
    """Draw a small section label with uppercase tracking."""
    p.save()
    p.setFont(QFont("Segoe UI", font_size, QFont.Weight.Medium))
    p.setPen(QColor(100, 160, 200, 180))
    p.drawText(int(x), int(y), text.upper())
    p.restore()


def draw_glow_dot(p, cx: float, cy: float, r: float, color: QColor):
    """Draw a soft glowing dot."""
    grad = QConicalGradient(cx, cy, 0)
    grad.setColorAt(0, color.lighter(150))
    grad.setColorAt(0.5, color)
    grad.setColorAt(1, QColor(0, 0, 0, 0))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx, cy), r * 2, r * 2)


def pulse_alpha(t: float, freq: float = 1.0, min_a: int = 100, max_a: int = 220) -> int:
    """Compute pulsing alpha value."""
    import math
    return int(min_a + (max_a - min_a) * 0.5 * (1 + math.sin(2 * math.pi * freq * t)))


class GlassPanel(QWidget):
    """
    Base glassmorphic panel widget.
    Subclasses override _paint_content() to draw their specific content.
    """
    updated = pyqtSignal()

    def __init__(self, parent=None, corner_radius: float = 12.0,
                 fill_alpha: int = 25, glow_strength: float = 0.25,
                 border_alpha: int = 60, animated: bool = True):
        super().__init__(parent)
        self._corner_radius = corner_radius
        self._fill_alpha = fill_alpha
        self._glow_strength = glow_strength
        self._border_alpha = border_alpha
        self._animated = animated
        self._t = 0.0
        self._bg_cache = None
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_tick)
        if animated:
            self._anim_timer.start(50)

    def _on_tick(self):
        self._t += 0.05
        self.update()
        self.updated.emit()

    def stop_animation(self):
        self._anim_timer.stop()

    def start_animation(self):
        if not self._anim_timer.isActive():
            self._anim_timer.start(50)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        if self._bg_cache is None or self._bg_cache.size() != self.size():
            from PyQt6.QtGui import QPixmap
            self._bg_cache = QPixmap(self.size())
            self._bg_cache.fill(Qt.GlobalColor.transparent)
            cache_p = QPainter(self._bg_cache)
            cache_p.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_glass_panel(cache_p, rect,
                             border_alpha=self._border_alpha,
                             fill_alpha=self._fill_alpha,
                             corner_radius=self._corner_radius,
                             glow_strength=self._glow_strength)
            cache_p.end()

        if self._bg_cache:
            p.drawPixmap(0, 0, self._bg_cache)

        self._paint_content(p, rect)

    def _paint_content(self, p: QPainter, rect):
        """Override in subclass."""
        pass