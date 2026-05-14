# ui/jarvis_desktop/background.py — JARVIS AMBIENT PARTICLE BACKGROUND
"""
Ambient particle field and weather effect background.
"""
import math
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient


class Particle:
    def __init__(self, w, h):
        self.x = random.random() * w
        self.y = random.random() * h
        self.vx = (random.random() - 0.5) * 0.3
        self.vy = (random.random() - 0.5) * 0.3 - 0.1
        self.size = random.uniform(0.8, 2.5)
        self.alpha = random.uniform(20, 80)
        self.color_choice = random.choice([0, 0, 1])  # 0=cyan, 1=blue

    def update(self, w, h):
        self.x += self.vx
        self.y += self.vy
        if self.x < 0: self.x = w
        if self.x > w: self.x = 0
        if self.y < 0: self.y = h
        if self.y > h: self.y = 0


class RainDrop:
    def __init__(self, w, h):
        self.reset(w, h)

    def reset(self, w, h):
        self.x = random.random() * w
        self.y = random.random() * -100
        self.len = random.uniform(15, 35)
        self.speed = random.uniform(4, 8)
        self.alpha = random.uniform(15, 40)

    def update(self, w, h):
        self.y += self.speed
        self.x += self.speed * 0.15
        if self.y > h + 50:
            self.reset(w, h)


class ParticleBackground(QWidget):
    """
    Ambient particle field with rain streaks and distant glow.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._particles: list[Particle] = []
        self._raindrops: list[RainDrop] = []
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)
        self._static_bg = None

    def _tick(self):
        self._t += 0.02
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            return
        for p in self._particles:
            p.update(w, h)
        for r in self._raindrops:
            r.update(w, h)
        self.update()

    def _ensure_particles(self):
        w, h = self.width(), self.height()
        if not self._particles:
            self._particles = [Particle(w, h) for _ in range(80)]
        if not self._raindrops:
            self._raindrops = [RainDrop(w, h) for _ in range(40)]

    def paintEvent(self, _):
        self._ensure_particles()
        w, h = self.width(), self.height()

        if w < 10 or h < 10:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw static cached background first
        if self._static_bg is None or self._static_bg.size() != self.size():
            self._render_static_bg(w, h)
        if self._static_bg:
            p.drawPixmap(0, 0, self._static_bg)

        # Rain streaks


        # Rain streaks
        p.save()
        for drop in self._raindrops:
            p.setOpacity(drop.alpha / 255)
            p.setPen(QPen(QColor(100, 160, 200, int(drop.alpha)), 1.0))
            p.drawLine(int(drop.x), int(drop.y), int(drop.x + drop.len * 0.15), int(drop.y + drop.len))
        p.restore()

        # Particles
        p.save()
        for particle in self._particles:
            alpha = int(particle.alpha + 20 * math.sin(self._t + particle.x * 0.01))
            col = QColor(0, 200, 255, alpha) if particle.color_choice == 0 else QColor(80, 150, 220, alpha)
            p.setBrush(QBrush(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.setOpacity(0.6)
            p.drawEllipse(QPointF(particle.x, particle.y), particle.size, particle.size)
        p.restore()

    def _render_static_bg(self, w, h):
        """Render expensive static gradients once per resize."""
        from PyQt6.QtGui import QPixmap, QRadialGradient
        self._static_bg = QPixmap(w, h)
        self._static_bg.fill(Qt.GlobalColor.transparent)

        p = QPainter(self._static_bg)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Distant city lights
        for i in range(5):
            bx = w * (0.1 + i * 0.18)
            bw = w * 0.12
            p.save()
            p.setOpacity(0.04 + i * 0.01)
            grad = QLinearGradient(bx, h, bx, h - 200)
            grad.setColorAt(0, QColor(20, 40, 60, 100))
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(int(bx), int(h - 200), int(bw), 200, QBrush(grad))
            p.restore()

        # Ambient glow orbs
        for ox, oy, col in [
            (w * 0.2, h * 0.3, QColor(0, 60, 120, 8)),
            (w * 0.7, h * 0.2, QColor(60, 0, 100, 6)),
            (w * 0.85, h * 0.6, QColor(0, 80, 140, 7)),
        ]:
            p.save()
            grad = QRadialGradient(ox, oy, 200)
            grad.setColorAt(0, col)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, w, h, QBrush(grad))
            p.restore()

        # Scanline overlay
        p.save()
        p.setOpacity(0.015)
        p.fillRect(0, 0, w, h, QBrush(QColor(0, 200, 255, 30)))
        p.restore()

        # Subtle vignette
        p.save()
        vign = QRadialGradient(w / 2, h / 2, max(w, h) * 0.7)
        vign.setColorAt(0, QColor(0, 0, 0, 0))
        vign.setColorAt(1, QColor(0, 0, 0, 180))
        p.fillRect(0, 0, w, h, QBrush(vign))
        p.restore()
        p.end()

