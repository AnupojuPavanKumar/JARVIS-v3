# -*- coding: utf-8 -*-
import math, random
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QTimer, QPointF, Qt, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QRadialGradient,
                          QBrush, QLinearGradient, QConicalGradient, QPixmap)
from ui.styles import Theme


class HUDBackground(QWidget):
    """
    Massive central AI reactor — QPainter at 30 fps.
    8 concentric rings (alternating CW/CCW), radar scan arc,
    orbital particle system (blue + orange sparks), neural network lines,
    radial grid, volumetric core glow.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._t = 0.0
        self._cache_pixmap = None
        self._cache_size = None

        # Orbital particles
        self._particles = []
        for _ in range(90):
            r = random.uniform(45, 230)
            self._particles.append({
                "r":  r,
                "a":  random.uniform(0, math.pi * 2),
                "sp": random.uniform(-0.005, 0.005) * (1 if random.random() > 0.5 else -1),
                "sz": random.uniform(0.8, 2.2),
                "op": random.uniform(0.3, 0.85),
                "orange": random.random() < 0.18,
            })

        # Flying sparks from core
        self._sparks = []

        # Neural network line pairs (indices into particles)
        self._neural = [(random.randint(0, 89), random.randint(0, 89))
                        for _ in range(30)]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # 30 fps

    # ─────────────────────────────────────────────────────────────────
    def _tick(self):
        self._t += 0.033

        # Advance orbital particles
        for pt in self._particles:
            pt["a"] += pt["sp"]

        # Spawn orange sparks
        if random.random() < 0.10:
            a = random.uniform(0, math.pi * 2)
            self._sparks.append({
                "a": a, "r": random.uniform(18, 30),
                "v": random.uniform(1.8, 4.5),
                "l": 0, "max": random.randint(28, 55),
                "orange": random.random() < 0.55,
            })
        alive = []
        for s in self._sparks:
            s["r"] += s["v"]
            s["l"] += 1
            if s["r"] < 600 and s["l"] < s["max"]:
                alive.append(s)
        self._sparks = alive

        self.update()

    def _update_cache(self, w, h):
        self._cache_pixmap = QPixmap(w, h)
        self._cache_pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(self._cache_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = w / 2, h / 2

        # 1 ── Volumetric ambient glow
        fog = QRadialGradient(cx, cy, max(w, h) * 0.65)
        fog.setColorAt(0.00, QColor(0, 80, 180,  28))
        fog.setColorAt(0.30, QColor(0, 50, 120,  12))
        fog.setColorAt(0.65, QColor(0, 10,  30,   5))
        fog.setColorAt(1.00, QColor(0,  0,   0,   0))
        p.setBrush(QBrush(fog))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(0, 0, w, h)

        p.save()
        p.translate(cx, cy)

        # 2 ── Radial grid lines
        p.setPen(QPen(QColor(0, 120, 255, 9), 0.5))
        for deg in range(0, 360, 15):
            rad = math.radians(deg)
            p.drawLine(QPointF(28 * math.cos(rad),  28 * math.sin(rad)),
                       QPointF(260 * math.cos(rad), 260 * math.sin(rad)))

        # 3 ── Concentric background rings (faint)
        for r in range(60, 280, 35):
            alpha = max(6, 22 - r // 16)
            p.setPen(QPen(QColor(0, 150, 255, alpha), 0.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), r, r)
        
        p.restore()
        p.end()
        self._cache_size = (w, h)

    # ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2

        # 1 ── Deep background
        p.fillRect(0, 0, W, H, QColor(Theme.BG))

        # 2 ── Draw static cache
        if self._cache_pixmap is None or self._cache_size != (W, H):
            self._update_cache(W, H)
        p.drawPixmap(0, 0, self._cache_pixmap)

        p.save()
        p.translate(cx, cy)

        # 3 ── Animated mechanical rings (8 rings, alternating direction)
        RINGS = [
            (220, 0.0008, "#00aaff", 0.15, 1.0),
            (195, -0.0012,"#00d4ff", 0.20, 1.2),
            (168, 0.0018, "#0088dd", 0.25, 1.0),
            (142, -0.0025,"#00d4ff", 0.30, 1.5),
            (116, 0.0038, "#00aaff", 0.38, 1.5),
            (90,  -0.006, "#00d4ff", 0.45, 2.0),
            (65,  0.010,  "#00ccff", 0.55, 2.0),
            (42,  -0.016, "#aaddff", 0.65, 2.5),
        ]
        for (ring_r, speed, col_hex, op, width) in RINGS:
            p.save()
            p.rotate(math.degrees(self._t * speed * 1000))
            c = QColor(col_hex)
            c.setAlpha(int(op * 255))
            p.setPen(QPen(c, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Full ring
            p.drawEllipse(QPointF(0, 0), ring_r, ring_r)
            # Tick marks
            p.setPen(QPen(c, width * 0.7))
            n_ticks = 12 if ring_r > 140 else 8
            for i in range(n_ticks):
                a = i * math.pi * 2 / n_ticks
                x1, y1 = ring_r * math.cos(a), ring_r * math.sin(a)
                x2 = (ring_r - 5) * math.cos(a)
                y2 = (ring_r - 5) * math.sin(a)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            p.restore()

        # 6 ── Radar scan arc
        scan_ang = (self._t * 0.55) % (math.pi * 2)
        scan_deg = math.degrees(scan_ang)
        # Sweep fill
        sweep = QConicalGradient(0, 0, scan_deg)
        sweep.setColorAt(0.00, QColor(0, 200, 255, 50))
        sweep.setColorAt(0.08, QColor(0, 180, 255, 12))
        sweep.setColorAt(0.15, QColor(0,   0,   0,  0))
        sweep.setColorAt(1.00, QColor(0,   0,   0,  0))
        p.setBrush(QBrush(sweep))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0, 0), 225, 225)
        # Scan line
        p.setPen(QPen(QColor(0, 220, 255, 180), 1.5))
        p.drawLine(QPointF(0, 0),
                   QPointF(225 * math.cos(scan_ang), 225 * math.sin(scan_ang)))

        # 7 ── Orbital particles
        for pt in self._particles:
            px = pt["r"] * math.cos(pt["a"])
            py = pt["r"] * math.sin(pt["a"])
            if pt["orange"]:
                c = QColor(255, 110, 30, int(pt["op"] * 220))
            else:
                c = QColor(0, 185, 255, int(pt["op"] * 220))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(px, py), pt["sz"], pt["sz"])

        # 8 ── Neural network lines between close particles
        p.setBrush(Qt.BrushStyle.NoBrush)
        for (i, j) in self._neural:
            pi_ = self._particles[i]; pj = self._particles[j]
            x1 = pi_["r"] * math.cos(pi_["a"])
            y1 = pi_["r"] * math.sin(pi_["a"])
            x2 = pj["r"]  * math.cos(pj["a"])
            y2 = pj["r"]  * math.sin(pj["a"])
            dist = math.hypot(x1 - x2, y1 - y2)
            if dist < 80:
                alpha = int(30 * (1 - dist / 80))
                p.setPen(QPen(QColor(0, 160, 255, alpha), 0.5))
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # 9 ── Energy sparks
        for s in self._sparks:
            fade = 1.0 - s["l"] / s["max"]
            col = QColor(255, 120, 40) if s["orange"] else QColor(0, 210, 255)
            col.setAlpha(int(210 * fade))
            p.setPen(QPen(col, 1.4))
            r1, r2 = s["r"], s["r"] + 12
            a = s["a"]
            p.drawLine(QPointF(r1 * math.cos(a), r1 * math.sin(a)),
                       QPointF(r2 * math.cos(a + 0.03), r2 * math.sin(a + 0.03)))

        # 10 ── Reactor core glow
        self._draw_reactor(p)

        p.restore()
        p.end()

    # ─────────────────────────────────────────────────────────────────
    def _draw_reactor(self, p: QPainter):
        pulse = math.sin(self._t * 2.4)

        # Outer atmosphere halo
        halo_r = 110 + pulse * 7
        halo = QRadialGradient(0, 0, halo_r * 1.8)
        halo.setColorAt(0.00, QColor(0, 150, 255, 55))
        halo.setColorAt(0.40, QColor(0, 120, 200, 18))
        halo.setColorAt(0.75, QColor(0,  40,  90,  6))
        halo.setColorAt(1.00, QColor(0,   0,   0,  0))
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0, 0), halo_r * 1.8, halo_r * 1.8)

        # Mid volumetric
        mid = QRadialGradient(0, 0, 70)
        mid.setColorAt(0.0, QColor(100, 210, 255, 90))
        mid.setColorAt(0.5, QColor(0, 150, 255, 35))
        mid.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(mid))
        p.drawEllipse(QPointF(0, 0), 70, 70)

        # Bright inner core
        core_r = 22 + pulse * 3
        cg = QRadialGradient(0, 0, core_r)
        cg.setColorAt(0.00, QColor(255, 255, 255, 255))
        cg.setColorAt(0.20, QColor(180, 235, 255, 240))
        cg.setColorAt(0.50, QColor(0,   170, 255, 160))
        cg.setColorAt(0.80, QColor(0,   100, 200,  55))
        cg.setColorAt(1.00, QColor(0,     0,   0,   0))
        p.setBrush(QBrush(cg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0, 0), core_r, core_r)
