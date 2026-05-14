# ui/jarvis_desktop/holographic_core.py — JARVIS HOLOGRAPHIC CORE
"""
The central holographic AI core — geometric neural reactor.
NOT a simple orb. A dimensional quantum energy structure with:
  - Rotating hexagonal energy lattice
  - Transparent energy rings at different tilt angles
  - Floating energy shards orbiting
  - Central light source with volumetric glow
  - Reactive holographic platform
  - Particle links between nodes
  - Pulsing energy core
"""
import math
import random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtProperty, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                          QRadialGradient, QPainterPath, QFont, QConicalGradient)


def lerp(a, b, t): return a + (b - a) * t


def hex_corners(cx, cy, r, rotation=0):
    """Return 6 corners of a hexagon."""
    corners = []
    for i in range(6):
        angle = math.radians(60 * i - 30 + rotation)
        corners.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return corners


def hex_path(cx, cy, r, rotation=0):
    """Return a QPainterPath for a hexagon."""
    pts = hex_corners(cx, cy, r, rotation)
    path = QPainterPath()
    path.moveTo(*pts[0])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


class HolographicCore(QWidget):
    """
    Central AI core visualization — multi-layered quantum structure.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._ring_rotation = 0.0
        self._shard_angle = 0.0
        self._core_pulse = 0.0
        self._node_phase = [random.random() * math.pi * 2 for _ in range(7)]
        self._ring_tilt = [0.4, 0.65, 0.85]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

        self.setMinimumSize(320, 320)

    def _tick(self):
        self._t += 0.02
        self._ring_rotation = self._t * 0.3
        self._shard_angle = self._t * 0.5
        self._core_pulse = 0.5 + 0.5 * math.sin(self._t * 2.0)
        self.update()

    def _glow(self, p, cx, cy, r_inner, r_outer, color, intensity=1.0):
        """Draw a radial glow."""
        grad = QRadialGradient(cx, cy, r_outer)
        grad.setColorAt(0, color.lighter(180))
        grad.setColorAt(0.4, color)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.setOpacity(intensity)
        p.drawEllipse(QPointF(cx, cy), r_outer, r_outer)
        p.setOpacity(1.0)

    def _draw_hexagonal_lattice(self, p, cx, cy, r_base, layers, t_offset=0.0):
        """Draw rotating hexagonal lattice rings."""
        for layer in range(layers):
            r = r_base * (1 - layer * 0.12)
            rot = self._ring_rotation + layer * 15
            alpha = int(200 - layer * 25)

            corners = hex_corners(cx, cy, r, rot)
            path = QPainterPath()
            path.moveTo(*corners[0])
            for x, y in corners[1:]:
                path.lineTo(x, y)
            path.closeSubpath()

            p.save()
            color = QColor(0, 190, 255, alpha)
            pen = QPen(color, 1.2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # Corner glow nodes
            for i, (hx, hy) in enumerate(corners):
                phase = self._node_phase[layer] + t_offset + i * 0.5
                glow_a = int(150 + 100 * math.sin(self._t * 1.5 + phase))
                dot_r = 2.5 + 1.5 * math.sin(self._t * 2 + phase)
                self._glow_dot(p, hx, hy, dot_r, QColor(0, 220, 255, glow_a))
            p.restore()

            # Internal cross-lines for inner layers
            if layer < 2:
                p.save()
                p.setPen(QPen(QColor(0, 160, 220, int(alpha * 0.4)), 0.5))
                mid = len(corners) // 2
                for i in range(mid):
                    x1, y1 = corners[i]
                    x2, y2 = corners[i + mid]
                    p.drawLine(int(x1), int(y1), int(x2), int(y2))
                p.restore()

    def _draw_tilted_ring(self, p, cx, cy, r, tilt_ratio, rot_angle, color, alpha=80):
        """Draw a tilted ring (simulated 3D with ellipse)."""
        p.save()
        p.translate(cx, cy)
        p.rotate(rot_angle)
        ry = r * tilt_ratio
        p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r, ry)
        # Bright edge dots
        for angle in [0, 60, 120, 180, 240, 300]:
            rad = math.radians(angle)
            x = r * math.cos(rad)
            y = ry * math.sin(rad)
            self._glow_dot(p, x, y, 3, QColor(0, 200, 255, 150))
        p.restore()

    def _draw_energy_ring(self, p, cx, cy, r, color, t_offset=0.0, width=2.0):
        """Draw a glowing energy ring with rotating dashes."""
        p.save()
        pen = QPen(color, width)
        dash_pattern = [8, 4, 2, 4]
        pen.setDashPattern(dash_pattern)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Energy packet moving along the ring
        packet_angle = (self._t * 80 + t_offset * 50) % 360
        rad = math.radians(packet_angle)
        px = cx + r * math.cos(rad)
        py = cy + r * math.sin(rad)
        self._glow_dot(p, px, py, 5, QColor(0, 255, 220, 220))
        p.restore()

    def _draw_core(self, p, cx, cy):
        """Draw the central luminous core."""
        pulse = self._core_pulse

        # Outer glow
        r_outer = 45 + 8 * pulse
        self._glow(p, cx, cy, 0, r_outer, QColor(0, 180, 255), 0.6)

        # Mid glow
        r_mid = 30 + 5 * pulse
        self._glow(p, cx, cy, 0, r_mid, QColor(100, 220, 255), 0.8)

        # Inner core
        grad = QRadialGradient(cx, cy, 20)
        grad.setColorAt(0, QColor(230, 245, 255, 255))
        grad.setColorAt(0.3, QColor(100, 200, 255, 200))
        grad.setColorAt(0.7, QColor(0, 120, 200, 100))
        grad.setColorAt(1, QColor(0, 50, 100, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 20, 20)

        # Core crosshair
        p.save()
        p.setPen(QPen(QColor(200, 230, 255, 100), 0.8))
        for angle in [0, 90, 180, 270]:
            rad = math.radians(angle + self._t * 10)
            x1 = cx + 8 * math.cos(rad)
            y1 = cy + 8 * math.sin(rad)
            x2 = cx + 18 * math.cos(rad)
            y2 = cy + 18 * math.sin(rad)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.restore()

    def _glow_dot(self, p, cx, cy, r, color):
        """Draw a soft glowing dot."""
        grad = QRadialGradient(cx, cy, r * 2)
        grad.setColorAt(0, color.lighter(150))
        grad.setColorAt(0.5, color)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 2, r * 2)

    def _draw_floating_shards(self, p, cx, cy, orbit_r, shard_count=8):
        """Draw energy shards orbiting the core."""
        for i in range(shard_count):
            angle = self._shard_angle + (i * 2 * math.pi / shard_count)
            x = cx + orbit_r * math.cos(angle)
            y = cy + orbit_r * math.sin(angle) * 0.7  # flat orbit

            # Shard shape (small diamond)
            size = 4 + 2 * math.sin(self._t * 3 + i)
            p.save()
            p.translate(x, y)
            p.rotate(math.degrees(angle) + 45)
            path = QPainterPath()
            path.addRect(-size, -size / 3, size * 2, size * 2 / 3)
            color = QColor(0, 200, 255, int(150 + 100 * math.sin(self._t * 2 + i)))
            p.setPen(QPen(color, 1))
            p.setBrush(QBrush(color.lighter(130)))
            p.setOpacity(0.8)
            p.drawPath(path)
            p.restore()

            # Particle link to core
            p.save()
            p.setPen(QPen(QColor(0, 160, 220, int(30 + 20 * math.sin(self._t + i))), 0.7))
            p.drawLine(int(cx), int(cy), int(x), int(y))
            p.restore()

    def _draw_holographic_platform(self, p, cx, cy, r):
        """Draw the reactive platform beneath the core."""
        p.save()

        # Outer ring platform
        for i in range(3):
            ring_r = r + 15 + i * 12
            alpha = int(80 - i * 20)
            p.setPen(QPen(QColor(0, 150, 200, alpha), 0.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy + 8), ring_r, ring_r * 0.3)

        # Reflection gradient
        refl = QLinearGradient(cx - r, cy, cx + r, cy + 30)
        refl.setColorAt(0, QColor(0, 100, 180, 0))
        refl.setColorAt(0.5, QColor(0, 150, 220, 25))
        refl.setColorAt(1, QColor(0, 80, 150, 0))
        p.setBrush(QBrush(refl))
        p.setPen(Qt.PenStyle.NoPen)
        p.setOpacity(0.5)
        p.drawEllipse(QPointF(cx, cy + 10), r + 10, r * 0.35)

        p.restore()

    def _draw_neural_links(self, p, cx, cy, r):
        """Draw neural network-style links between lattice nodes."""
        nodes = []
        for i in range(7):
            angle = self._ring_rotation * 0.3 + i * (2 * math.pi / 7)
            nr = r * (0.4 + 0.4 * (i % 3 == 0))
            nx = cx + nr * math.cos(angle)
            ny = cy + nr * math.sin(angle)
            nodes.append((nx, ny))

        p.save()
        for i, (x1, y1) in enumerate(nodes):
            for j, (x2, y2) in enumerate(nodes):
                if i < j:
                    alpha = int(40 + 30 * math.sin(self._t + i + j))
                    p.setPen(QPen(QColor(0, 150, 200, alpha), 0.6))
                    p.drawLine(int(x1), int(y1), int(x2), int(y2))

            # Node dot
            glow_a = int(150 + 100 * math.sin(self._t * 1.5 + self._node_phase[i]))
            self._glow_dot(p, x1, y1, 3, QColor(0, 200, 255, glow_a))
        p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Note: PaintOutsidePaintEvent removed - not available in PyQt6

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.28

        # Ambient glow behind everything
        self._glow(p, cx, cy, 0, r * 2.5, QColor(0, 80, 160), 0.15)

        # Platform
        self._draw_holographic_platform(p, cx, cy, r)

        # Tilted energy rings
        self._draw_tilted_ring(p, cx, cy, r * 1.15, self._ring_tilt[0],
                               self._ring_rotation * 20, QColor(0, 180, 255), 60)
        self._draw_tilted_ring(p, cx, cy, r * 0.9, self._ring_tilt[1],
                               -self._ring_rotation * 30, QColor(0, 160, 240), 50)
        self._draw_tilted_ring(p, cx, cy, r * 1.35, self._ring_tilt[2],
                               self._ring_rotation * 15, QColor(0, 130, 200), 40)

        # Energy rings
        self._draw_energy_ring(p, cx, cy, r * 1.05, QColor(0, 180, 255), 0.0, 1.5)
        self._draw_energy_ring(p, cx, cy, r * 0.8, QColor(0, 200, 255), 1.0, 1.2)
        self._draw_energy_ring(p, cx, cy, r * 1.2, QColor(0, 140, 220), 2.0, 1.0)

        # Hexagonal lattice
        self._draw_hexagonal_lattice(p, cx, cy, r, 4, 0.0)

        # Neural links
        self._draw_neural_links(p, cx, cy, r)

        # Floating shards
        self._draw_floating_shards(p, cx, cy, r * 1.45, 8)

        # Core
        self._draw_core(p, cx, cy)