# ui/jarvis_core.py — JARVIS SOVEREIGN CORE V9 (Premium 60fps)
# ─────────────────────────────────────────────────────────────────
# Improvements over V8:
#   • Field-line tendrils that emanate from core toward nearest particles
#   • State-morph easing: all colour and size changes use exponential decay
#   • Magnetic hover: particles slightly "lean" toward cursor
#   • Glass inner ring: thin white 1px ring with gradient stops
#   • Conical sweep always active at low opacity in idle, high in listening
#   • Speaking: radial shockwave ring erupts on state entry
import math, random, time
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore    import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui     import (QPainter, QColor, QPen, QBrush,
                              QPainterPath, QFont,
                              QRadialGradient, QConicalGradient,
                              QLinearGradient)

from ui.styles import Theme, get_color

PI2 = math.pi * 2

# Target core radius per state
STATE_CORE_R = {
    "boot": 60, "idle": 62, "listening": 68,
    "thinking": 70, "speaking": 85, "danger": 78,
}

# Particle orbit radius per state
STATE_ORBIT = {
    "boot": 180, "idle": 178, "listening": 155,
    "thinking": 122, "speaking": 245, "danger": 200,
}


class Particle:
    def __init__(self, index, total):
        self.angle  = (index / total) * PI2
        self.radius = random.uniform(80, 240)
        self.speed  = random.uniform(0.018, 0.075)
        self.size   = random.uniform(1.5, 3.5)
        self.alpha  = random.randint(90, 210)
        self.z      = random.uniform(0.3, 1.0)
        self.phase  = random.uniform(0, PI2)
        self.float_y = 0.0
        self._mx    = 0.0   # magnetic x offset
        self._my    = 0.0   # magnetic y offset

    def update(self, dt, state, t, cursor_cx, cursor_cy):
        speed_mult = 2.2 if state in ("thinking", "speaking") else \
                     1.5 if state == "listening" else 1.0
        self.angle += self.speed * speed_mult

        target_r = STATE_ORBIT.get(state, 178)
        if state == "thinking":
            target_r += math.sin(t * 10 + self.angle * 2) * 28
        elif state == "speaking":
            target_r += math.sin(t * 22 + self.phase) * 45
        elif state == "listening":
            target_r += math.sin(t * 8) * 18
        elif state == "idle":
            target_r += math.sin(t * 2 + self.phase) * 14

        self.radius  += (target_r - self.radius) * 0.08
        self.float_y  = math.sin(t + self.phase) * 9

        # Magnetic pull toward cursor (subtle)
        px = math.cos(self.angle) * self.radius * self.z
        py = math.sin(self.angle) * self.radius * self.z + self.float_y
        if cursor_cx is not None:
            dx = cursor_cx - px
            dy = cursor_cy - py
            dist = math.sqrt(dx*dx + dy*dy) + 0.001
            if dist < 180:
                pull = 6 * (1 - dist / 180)
                tx = pull * dx / dist
                ty = pull * dy / dist
                self._mx += (tx - self._mx) * 0.12
                self._my += (ty - self._my) * 0.12
                return
        self._mx += (0 - self._mx) * 0.08
        self._my += (0 - self._my) * 0.08


class JarvisCoreWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(600, 600)
        self.setMouseTracking(True)

        self._t          = 0.0
        self._state      = "idle"
        self._prev_state = "idle"
        
        # Initialize color from Theme
        idle_col = get_color(Theme.STATE_COLORS["idle"])
        self._cur_col = [float(idle_col.red()), float(idle_col.green()), float(idle_col.blue())]
        
        self._cur_core_r = 62.0
        self._vram_pct   = 0.0

        # Cursor (relative to widget centre) for magnetic effect
        self._cursor_cx = None
        self._cursor_cy = None

        # Shockwave for speaking state entry
        self._shock_r    = -1.0    # -1 = inactive
        self._shock_alpha= 0

        # Neural map
        self._neural_map = [
            {"x": random.uniform(-400,400), "y": random.uniform(-400,400), "links": []}
            for _ in range(50)
        ]
        for node in self._neural_map:
            for _ in range(random.randint(1, 3)):
                node["links"].append(random.choice(self._neural_map))

        # Rings
        self._rings = [
            {"r": 158, "s":  0.38, "a": 0.0, "dash": [28, 65]},
            {"r": 200, "s": -0.20, "a": 0.0, "dash": [ 5, 14]},
            {"r": 232, "s":  0.12, "a": 0.0, "dash": [12, 48]},
        ]

        # Data arcs
        self._arcs = [
            {"r": 262, "start":   0, "span": 58, "speed":  1.1, "data": "SCAN_MOD_01"},
            {"r": 282, "start": 118, "span": 42, "speed": -0.9, "data": "AUTH_VERIFIED"},
            {"r": 304, "start": 252, "span": 76, "speed":  0.6, "data": "ORCHESTRATOR_UP"},
        ]

        self._num_particles = 240
        self._particles = [Particle(i, self._num_particles) for i in range(self._num_particles)]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_mode(self, name: str):
        if name != self._state:
            self._prev_state = self._state
            self._state = name
            if name == "speaking":
                self._shock_r     = 0.0
                self._shock_alpha = 200

    def update_vram(self, pct: float):
        self._vram_pct = pct

    def mouseMoveEvent(self, e):
        cx, cy = self.width()//2, self.height()//2
        self._cursor_cx = e.position().x() - cx
        self._cursor_cy = e.position().y() - cy

    def leaveEvent(self, e):
        self._cursor_cx = None
        self._cursor_cy = None

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        dt = 0.016
        self._t += dt

        # Smooth colour transition (exponential decay)
        tgt_hex = Theme.STATE_COLORS.get(self._state, Theme.STATE_COLORS["idle"])
        tgt_qcol = get_color(tgt_hex)
        tgt = (float(tgt_qcol.red()), float(tgt_qcol.green()), float(tgt_qcol.blue()))
        
        for i in range(3):
            self._cur_col[i] += (tgt[i] - self._cur_col[i]) * 0.07

        # Smooth core radius
        tr = STATE_CORE_R.get(self._state, 62)
        if self._state == "speaking":
            tr += 18 * abs(math.sin(self._t * 28))
        elif self._state == "thinking":
            tr += 8  * abs(math.sin(self._t * 18))
        self._cur_core_r += (tr - self._cur_core_r) * 0.09

        # Shockwave expand
        if self._shock_r >= 0:
            self._shock_r     += 12
            self._shock_alpha  = max(0, self._shock_alpha - 5)
            if self._shock_alpha == 0:
                self._shock_r = -1.0

        for p in self._particles:
            p.update(dt, self._state, self._t, self._cursor_cx, self._cursor_cy)

        for r in self._rings:
            r["a"] += r["s"] * dt
        for arc in self._arcs:
            arc["start"] += arc["speed"]

        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W // 2, H // 2
        p.translate(cx, cy)

        rgb = [int(c) for c in self._cur_col]
        col = QColor(*rgb)

        # 1. Neural map (background texture)
        self._draw_neural_map(p, rgb)

        # 2. Perspective grid
        self._draw_grid(p)

        # 3. Radial rays
        self._draw_rays(p, rgb)

        # 4. Conical sweep (listening=strong, idle=subtle)
        sweep_alpha = 90 if self._state == "listening" else 22
        self._draw_conical_sweep(p, rgb, sweep_alpha)

        # 5. Occasional energy pulse
        if random.random() < 0.06 and self._state in ("thinking","speaking"):
            self._draw_energy_pulse(p, rgb)

        # 6. Atmospheric glow
        grad = QRadialGradient(0,0,360)
        grad.setColorAt(0, QColor(*rgb, 38))
        grad.setColorAt(0.7, QColor(*rgb, 10))
        grad.setColorAt(1,   QColor(0,0,0,0))
        p.setBrush(grad); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(-460,-460,920,920)

        # 7. Compute particle positions, draw them + field lines
        coords = []
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            sc  = 0.65 + (pt.z - 0.3) / 0.7 * 0.35
            px  = math.cos(pt.angle) * pt.radius * sc + pt._mx
            py  = math.sin(pt.angle) * pt.radius * sc + pt.float_y + pt._my
            a   = int(pt.alpha * sc)
            p.setBrush(QColor(*rgb, a))
            p.drawEllipse(QPointF(px, py), pt.size*sc, pt.size*sc)
            coords.append((px, py, sc, a))

        # 8. Thinking: particle interconnect
        if self._state == "thinking":
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            for i in range(0, len(coords), 10):
                x1,y1,s1,a1 = coords[i]
                for j in range(i+1, min(i+4, len(coords))):
                    x2,y2,s2,a2 = coords[j]
                    dist = math.sqrt((x1-x2)**2+(y1-y2)**2)
                    if dist < 95:
                        p.setPen(QPen(QColor(*rgb, int(55*(1-dist/95))),1))
                        p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # 9. Field lines — tendrils from core to 6 nearest particles
        self._draw_field_lines(p, rgb, coords)

        # 10. Rings
        for r in self._rings:
            pen = QPen(QColor(*rgb, 88), 1.4)
            pen.setDashPattern(r["dash"]); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.save(); p.rotate(r["a"]*80)
            p.drawEllipse(QPointF(0,0), r["r"], r["r"])
            for i in range(12): p.rotate(30); p.drawLine(int(r["r"]-7),0,int(r["r"]+7),0)
            p.restore()

        # 11. Data arcs
        self._draw_data_arcs(p, rgb)

        # 12. Shockwave ring
        if self._shock_r >= 0:
            p.setPen(QPen(QColor(*rgb, self._shock_alpha), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0,0), self._shock_r, self._shock_r)

        # 13. Core
        self._draw_core(p, rgb)

    # ── Draw helpers ──────────────────────────────────────────────────────────

    def _draw_neural_map(self, p, rgb):
        p.setPen(QPen(QColor(*rgb,14), 0.5))
        for node in self._neural_map:
            for lnk in node["links"]:
                p.drawLine(QPointF(node["x"],node["y"]),QPointF(lnk["x"],lnk["y"]))
            p.setBrush(QColor(*rgb,28)); p.drawEllipse(QPointF(node["x"],node["y"]),2,2)

    def _draw_grid(self, p):
        p.setPen(QPen(QColor(255,255,255,5),1))
        sp, lim = 90, 540
        for i in range(-7,8):
            p.drawLine(-lim, i*sp, lim, i*sp)
            p.drawLine(i*sp, -lim, i*sp,  lim)

    def _draw_conical_sweep(self, p, rgb, alpha):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        grad = QConicalGradient(0, 0, -math.degrees(self._t * 2))
        grad.setColorAt(0,   QColor(*rgb, alpha))
        grad.setColorAt(0.18,QColor(*rgb, 0))
        p.setBrush(QBrush(grad)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(-330,-330,660,660)
        p.restore()

    def _draw_rays(self, p, rgb):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for i in range(16):
            angle  = self._t*0.28 + i*(PI2/16)
            length = 390 + math.sin(self._t*4+i)*65
            grad   = QLinearGradient(0,0,math.cos(angle)*length,math.sin(angle)*length)
            grad.setColorAt(0,   QColor(*rgb,48))
            grad.setColorAt(0.5, QColor(*rgb,14))
            grad.setColorAt(1,   QColor(0,0,0,0))
            p.setPen(QPen(QBrush(grad),2))
            p.drawLine(QPointF(0,0), QPointF(math.cos(angle)*length, math.sin(angle)*length))
        p.restore()

    def _draw_energy_pulse(self, p, rgb):
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        r = (self._t*580) % 660
        a = int(100*(1-r/660))
        p.setPen(QPen(QColor(*rgb,a),2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0,0),r,r)
        p.restore()

    def _draw_field_lines(self, p, rgb, coords):
        """Draw thin tendrils from core centre to the 6 nearest particles."""
        if not coords: return
        dists = sorted(coords, key=lambda c: c[0]**2+c[1]**2)[:8]
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for px,py,sc,a in dists:
            dist = math.sqrt(px*px+py*py)
            if dist < 20: continue
            grad = QLinearGradient(0,0,px,py)
            grad.setColorAt(0,   QColor(*rgb, 80))
            grad.setColorAt(0.6, QColor(*rgb, 25))
            grad.setColorAt(1,   QColor(*rgb,  0))
            p.setPen(QPen(QBrush(grad), 0.8))
            p.drawLine(QPointF(0,0), QPointF(px,py))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    def _draw_data_arcs(self, p, rgb):
        p.setFont(QFont("Consolas", 7))
        for arc in self._arcs:
            p.setPen(QPen(QColor(*rgb,78),1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(-arc["r"],-arc["r"],arc["r"]*2,arc["r"]*2),
                      int(arc["start"]*16), int(arc["span"]*16))
            ar = math.radians(arc["start"]+arc["span"]/2)
            p.save()
            p.translate(math.cos(ar)*(arc["r"]+12), math.sin(ar)*(arc["r"]+12))
            p.rotate(arc["start"]+arc["span"]/2+90)
            p.setPen(QPen(QColor(*rgb,140))); p.drawText(0,0,arc["data"])
            p.restore()

    def _draw_core(self, p, rgb):
        cr = self._cur_core_r

        # Bloom
        bloom = QRadialGradient(0,0,cr*2.2)
        bloom.setColorAt(0,   QColor(*rgb,185))
        bloom.setColorAt(0.38,QColor(*rgb, 68))
        bloom.setColorAt(1,   QColor(0,0,0,0))
        p.setBrush(bloom); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0,0), cr*2.2, cr*2.2)

        # Accent ring
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(*rgb, 50), 1))
        p.drawEllipse(QPointF(0,0), cr+22, cr+22)

        # Hex shells — all theme-colored, no pure white
        p.setPen(QPen(QColor(*rgb, 210), 1.2)); self._draw_hex(p, cr+8,  self._t*1.0)
        p.setPen(QPen(QColor(*rgb, 140), 1.0)); self._draw_hex(p, cr+18, -self._t*0.5)
        p.setPen(QPen(QColor(*rgb,  65), 0.6)); self._draw_hex(p, cr+28,  self._t*0.3)

        # Spinning inner sphere — theme-colored
        inner_r = cr * 0.92
        p.save(); p.rotate(self._t*240)
        ig = QRadialGradient(0,0,inner_r)
        ig.setColorAt(0,   QColor(*rgb, 255))
        ig.setColorAt(0.4, QColor(*rgb, 160))
        ig.setColorAt(1,   QColor(0,0,0,0))
        p.setBrush(ig); p.drawEllipse(QPointF(0,0), inner_r, inner_r)
        p.setPen(QPen(QColor(*rgb, 210), 2.0))
        b = int(inner_r*0.68)
        p.drawLine(-b,0,b,0); p.drawLine(0,-b,0,b)
        p.restore()

        # VRAM arc
        if self._vram_pct > 0:
            rect = QRectF(-cr-36,-cr-36,(cr+36)*2,(cr+36)*2)
            p.setPen(QPen(QColor(*rgb,38),7)); p.drawArc(rect,0,360*16)
            p.setPen(QPen(QColor(*rgb,255),7))
            p.drawArc(rect, 90*16, int(-self._vram_pct*3.6*16))

    def _draw_hex(self, p, r, angle):
        path = QPainterPath()
        for i in range(6):
            a = angle + i*PI2/6
            px, py = math.cos(a)*r, math.sin(a)*r
            if i == 0: path.moveTo(px,py)
            else:      path.lineTo(px,py)
        path.closeSubpath(); p.drawPath(path)
