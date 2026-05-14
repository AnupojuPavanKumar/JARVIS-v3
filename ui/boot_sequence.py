# ui/boot_sequence.py — JARVIS CINEMATIC BOOT v4 "DIGITAL GENESIS"
# ─────────────────────────────────────────────────────────────────
# Phases:
#   0  (0.0–1.0s) : Black void — single centre point expands
#   1  (1.0–2.2s) : Wireframe construction — hex/globe segments draw in
#   2  (2.2–4.0s) : Data burst + ring spin-up
#   3  (4.0–5.5s) : Full display with parallax particles + boot messages
#   4  (5.5–7.0s) : Fade-out dissolve
import math, random
from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore    import Qt, QTimer, pyqtSignal, QPointF, QRectF
from PyQt6.QtGui     import (QPainter, QColor, QPen, QBrush, QFont,
                              QLinearGradient, QRadialGradient,
                              QPainterPath, QConicalGradient)

from ui.styles import Theme, get_color

# ── Palette ────────────────────────────────────────────────────────────────────
C_ORG  = get_color(Theme.ORANGE)
C_AMB  = get_color(Theme.AMBER)
C_GOLD = get_color(Theme.GOLD)
C_CYAN = get_color(Theme.CYAN)
C_PUR  = get_color(Theme.PURPLE)
C_BG   = get_color(Theme.BG)
C_TXT  = get_color(Theme.TEXT)
PI2    = math.pi * 2

_BOOT_MSGS = [
    "INITIALIZING NEURAL CORE...",
    "LOADING PROPERTY GRAPH MEMORY...",
    "CALIBRATING VOICE SYNTHESIS ENGINE...",
    "CONNECTING SOVEREIGN ORCHESTRATOR...",
    "ENGAGING AGENTIC INTELLIGENCE...",
    "ESTABLISHING SECURE CHANNELS...",
    "VRAM ORCHESTRATOR · LOCKS ARMED...",
    "SYSTEM ONLINE — WELCOME BACK, SIR.",
]


class CinematicBoot(QWidget):
    finished = pyqtSignal()
    phase_advance = pyqtSignal(int)  # emitted when a new boot phase starts

    PHASE_TIMES = [0.0, 1.0, 2.2, 4.0, 5.5, 7.0]   # phase boundaries in seconds

    def __init__(self, parent=None):
        super().__init__(parent,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        screen = QApplication.primaryScreen().geometry()
        W, H = screen.width(), screen.height()
        self.resize(W, H); self.move(0, 0)

        # ── Simulation state ───────────────────────────────────────────────────
        self._t          = 0.0          # total elapsed seconds
        self._phase      = 0
        self._alpha      = 255
        self._blink      = True
        self._blink_t    = 0
        self._glitch_t   = 0
        self._glitch_dx  = 0
        self._glitch_dy  = 0
        self._scanline_y = 0.0

        # Readiness tracking (set via set_readiness)
        self._ready_tracker = None

        # Typewriter
        self._msg_idx   = 0
        self._msg_chars = 0
        self._msg_timer = 0

        # Wireframe construction progress (phase 1)  0→1
        self._wire_prog  = 0.0

        # Ring spin-up speed multiplier (ramps in phase 2)
        self._ring_spin  = 0.0

        # Core pulse radius
        self._core_r     = 0.0

        # ── Parallax particle layers ───────────────────────────────────────────
        self._layers = [
            self._make_layer(W, H, 15, speed=0.4, size_rng=(1.0, 2.0), alpha_rng=(30, 80),  z=0.3),
            self._make_layer(W, H, 10, speed=0.8, size_rng=(1.5, 3.0), alpha_rng=(60, 140), z=0.65),
            self._make_layer(W, H,  5, speed=1.3, size_rng=(2.0, 4.5), alpha_rng=(100, 200),z=1.0),
        ]

        # ── Falling binary streams ─────────────────────────────────────────────
        self._streams = [
            {"x": random.randint(0, W), "y": random.randint(-H, 0),
             "speed": random.uniform(4, 12),
             "chars": [random.choice("01X#@|&%") for _ in range(10)]}
            for _ in range(20)
        ]

        # ── Rotating rings ─────────────────────────────────────────────────────
        self._rings = [
            {"r": 130, "a": 0.0, "s":  0.45, "dash": [20, 40], "col": C_ORG, "alpha": 0},
            {"r": 175, "a": 1.0, "s": -0.30, "dash": [ 6, 20], "col": C_AMB, "alpha": 0},
            {"r": 220, "a": 0.5, "s":  0.22, "dash": [40, 30], "col": C_CYAN,"alpha": 0},
            {"r": 265, "a": 2.0, "s": -0.15, "dash": [10, 70], "col": C_ORG, "alpha": 0},
            {"r": 310, "a": 1.5, "s":  0.08, "dash": [2, 100], "col": C_GOLD, "alpha": 0},
        ]


        # ── Wireframe segments (built incrementally in phase 1) ────────────────
        self._wire_segs = self._build_wire_segs()

        # ── Corner HUD ────────────────────────────────────────────────────────
        self._corners = self._build_corners(W, H)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)   # 60 fps

        QTimer.singleShot(5500, self._start_fadeout)

    def set_readiness(self, tracker):
        """Wire in the ReadinessTracker so CinematicBoot can show subsystem counts."""
        self._ready_tracker = tracker

    # ── Factories ─────────────────────────────────────────────────────────────

    def _make_layer(self, W, H, count, speed, size_rng, alpha_rng, z):
        pts = []
        for _ in range(count):
            pts.append({
                "x":     random.uniform(0, W),
                "y":     random.uniform(0, H),
                "vx":    random.uniform(-0.2, 0.2) * z,
                "vy":    random.uniform(-speed * 0.8, -speed * 0.4) * z,
                "size":  random.uniform(*size_rng),
                "alpha": random.randint(*alpha_rng),
                "col":   random.choice([C_ORG, C_AMB, C_CYAN]),
                "z":     z,
                "hist":  [],
            })
        return pts

    def _build_wire_segs(self):
        """Pre-compute all wireframe line segments for the centre globe."""
        segs = []; r = 290; half = r // 2
        # Latitude rings
        for i in range(-5, 6):
            lat = i * (r // 6)
            rr  = math.sqrt(max(0, half * half - lat * lat))
            pts = []
            for a in range(0, 361, 10):
                rad = math.radians(a)
                pts.append((math.cos(rad) * rr, lat + math.sin(rad) * rr / 3))
            for k in range(len(pts) - 1):
                segs.append(("lat", pts[k], pts[k+1]))
        # Hex rings
        for rad, col in [(92, C_AMB), (104, C_ORG), (80, C_CYAN)]:
            for i in range(6):
                a1 = i * PI2 / 6; a2 = (i + 1) * PI2 / 6
                segs.append(("hex", (math.cos(a1)*rad, math.sin(a1)*rad),
                                    (math.cos(a2)*rad, math.sin(a2)*rad), col))
        return segs

    def _build_corners(self, W, H):
        m, s = 30, 45
        return [
            [(m, m, m+s, m), (m, m, m, m+s)],
            [(W-m, m, W-m-s, m), (W-m, m, W-m, m+s)],
            [(m, H-m, m+s, H-m), (m, H-m, m, H-m-s)],
            [(W-m, H-m, W-m-s, H-m), (W-m, H-m, W-m, H-m-s)],
        ]

    def _start_fadeout(self):
        self._phase = 4
        QTimer.singleShot(1500, self.finished.emit)

    # ── Tick ──────────────────────────────────────────────────────────────────

    def _tick(self):
        dt   = 0.016
        self._t += dt
        W, H  = self.width(), self.height()

        # Phase transitions
        if   self._t < 1.0: self._phase = 0
        elif self._t < 2.2: self._phase = 1
        elif self._t < 4.0: self._phase = 2
        elif self._t < 5.5: self._phase = 3
        else:                self._phase = 4

        # Wireframe build-up (phase 1)
        if self._phase == 1:
            self._wire_prog = min(1.0, (self._t - 1.0) / 1.2)

        # Ring alpha fade-in (phase 2+)
        if self._phase >= 2:
            for r in self._rings:
                r["alpha"] = min(120, r["alpha"] + 3)
        if self._phase >= 2:
            self._ring_spin = min(1.0, self._ring_spin + 0.015)

        # Core ramp
        if self._phase >= 1:
            target_r = 46 if self._phase == 1 else (60 if self._phase >= 3 else 52)
            self._core_r += (target_r - self._core_r) * 0.06

        for r in self._rings:
            r["a"] += r["s"] * dt * self._ring_spin

        # Scanline
        self._scanline_y = (self._scanline_y + H * dt / 3.5) % H

        # Blink
        self._blink_t += 1
        if self._blink_t % 28 == 0:
            self._blink = not self._blink

        # Glitch (phase 2 mostly)
        if self._phase in (2, 3) and random.random() < 0.022:
            self._glitch_t  = random.randint(2, 7)
            self._glitch_dx = random.randint(-22, 22)
            self._glitch_dy = random.randint(-7,   7)
        if self._glitch_t > 0:
            self._glitch_t -= 1

        # Particles (all layers)
        for layer in self._layers:
            for pt in layer:
                pt["hist"].insert(0, (pt["x"], pt["y"]))
                if len(pt["hist"]) > 5: pt["hist"].pop()
                pt["x"] += pt["vx"]
                pt["y"] += pt["vy"]
                if pt["y"] < -10:
                    pt["x"] = random.uniform(0, W)
                    pt["y"] = H + 5
                    pt["hist"] = []

        # Binary streams (phase 3 only)
        if self._phase >= 3:
            for s in self._streams:
                s["y"] += s["speed"]
                if s["y"] > H:
                    s["y"] = -120; s["x"] = random.randint(0, W)
                if random.random() < 0.07:
                    s["chars"].pop(0)
                    s["chars"].append(random.choice("01X#@|"))

        # Typewriter (phase 3)
        if self._phase == 3:
            self._msg_timer += 1
            if self._msg_timer % 3 == 0 and self._msg_idx < len(_BOOT_MSGS):
                msg = _BOOT_MSGS[self._msg_idx]
                if self._msg_chars < len(msg):
                    self._msg_chars += 1
                else:
                    self._msg_timer = 0
                    if self._msg_idx < len(_BOOT_MSGS) - 1:
                        self._msg_idx += 1; self._msg_chars = 0

        # Fade-out
        if self._phase == 4:
            self._alpha = max(0, self._alpha - 5)

        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H   = self.width(), self.height()
        cx, cy = W // 2, H // 2
        cy_globe = int(H * 0.47)
        cy_logo  = int(H * 0.17)

        p.setOpacity(self._alpha / 255)
        p.fillRect(0, 0, W, H, C_BG)

        # Phase 0 — expanding singularity point
        if self._phase == 0:
            prog = self._t / 1.0
            r = prog * 180
            g = QRadialGradient(cx, cy_globe, r)
            g.setColorAt(0,   QColor(255, 255, 255, int(220 * prog)))
            g.setColorAt(0.3, QColor(249, 115,  22, int(120 * prog)))
            g.setColorAt(1,   QColor(0,   0,     0,  0))
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy_globe), r, r)
            self._draw_corners(p)
            return

        # Grid (all phases 1+)
        self._draw_grid(p, W, H)

        # Scanline
        sy = int(self._scanline_y)
        gs = QLinearGradient(0, sy - 40, 0, sy + 40)
        gs.setColorAt(0, QColor(0,0,0,0)); gs.setColorAt(0.5, QColor(249,115,22,20)); gs.setColorAt(1, QColor(0,0,0,0))
        p.fillRect(0, sy - 40, W, 80, QBrush(gs))
        p.setPen(QPen(QColor(249,115,22,28),1)); p.drawLine(0,sy,W,sy)

        # Parallax particles — draw back layers first
        for layer_idx, layer in enumerate(self._layers):
            if self._phase < layer_idx + 1: continue
            fade = min(1.0, (self._t - layer_idx) / 0.8)
            for pt in layer:
                c = QColor(pt["col"]); c.setAlpha(int(pt["alpha"] * fade))
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(pt["x"], pt["y"]), pt["size"], pt["size"])

        # Atmospheric glow
        glow = QRadialGradient(cx, cy_globe, 420)
        glow.setColorAt(0, QColor(249,115,22,28)); glow.setColorAt(0.6, QColor(245,158,11,8)); glow.setColorAt(1,QColor(0,0,0,0))
        p.setBrush(QBrush(glow)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx-500, cy_globe-500, 1000, 1000)

        # Glitch offset
        gx = self._glitch_dx if self._glitch_t > 0 else 0
        gy = self._glitch_dy if self._glitch_t > 0 else 0

        p.save(); p.translate(cx + gx, cy_globe + gy)

        # Phase 1 — wireframe construction
        if self._phase == 1:
            n = int(self._wire_prog * len(self._wire_segs))
            for seg in self._wire_segs[:n]:
                if seg[0] == "lat":
                    p.setPen(QPen(QColor(249,115,22,35), 1))
                else:
                    c = QColor(seg[3]); c.setAlpha(90)
                    p.setPen(QPen(c, 1.8))
                p.drawLine(QPointF(*seg[1]), QPointF(*seg[2]))
            # Flash at build front
            if n < len(self._wire_segs):
                seg = self._wire_segs[n]
                p.setPen(QPen(QColor(255,255,255,200), 2))
                p.drawLine(QPointF(*seg[1]), QPointF(*seg[2]))

        # Phase 2+ — full globe + rings
        if self._phase >= 2:
            self._draw_wireframe_globe(p)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for r in self._rings:
                c = QColor(r["col"]); c.setAlpha(r["alpha"])
                pen = QPen(c, 1.5); pen.setDashPattern(r["dash"]); p.setPen(pen)
                p.save(); p.rotate(math.degrees(r["a"]))
                p.drawEllipse(QPointF(0,0), r["r"], r["r"])
                for _ in range(4):
                    p.rotate(90); p.setBrush(QBrush(c))
                    p.drawRect(-2, int(-r["r"]-5), 4, 10)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.restore()
            self._draw_hex_ring(p,  90, self._t * 0.55,  C_AMB,  160)
            self._draw_hex_ring(p, 100, -self._t * 0.30, C_ORG,   90)
            self._draw_hex_ring(p,  78,  self._t * 0.95, C_CYAN,  65)

        # Core pulse
        if self._phase >= 1:
            pulse_r = self._core_r + math.sin(self._t * 6.5) * 6
            if self._phase >= 3:
                pulse_r += 12 * abs(math.sin(self._t * 18))
            inner = QRadialGradient(0, 0, pulse_r)
            inner.setColorAt(0,    QColor(255,255,255,255))
            inner.setColorAt(0.35, QColor(252,211, 77,220))
            inner.setColorAt(0.7,  QColor(249,115, 22, 80))
            inner.setColorAt(1,    QColor(0,  0,   0,   0))
            p.setBrush(QBrush(inner)); p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(0,0), pulse_r, pulse_r)
            p.setPen(QPen(QColor(255,255,255,100),1.5))
            b = int(pulse_r * 0.65)
            p.drawLine(-b,0,b,0); p.drawLine(0,-b,0,b)

        # Energy pulse rings (phase 2+)
        if self._phase >= 2:
            ep = (self._t * 500) % 600
            ep_alpha = int(100 * (1 - ep/600))
            p.setPen(QPen(QColor(249,115,22,ep_alpha),1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0,0), ep, ep)

        p.restore()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # Binary streams (phase 3)
        if self._phase >= 3:
            p.setFont(QFont("Consolas", 8))
            for s in self._streams:
                for i, ch in enumerate(s["chars"]):
                    a = int(30 * (i / len(s["chars"])))
                    p.setPen(QColor(249,115,22,a))
                    p.drawText(int(s["x"]), int(s["y"]+i*12), ch)

        # ── LOGO ──────────────────────────────────────────────────────────────
        logo_fade = min(1.0, max(0.0, (self._t - 0.6) / 0.8))
        p.setOpacity(self._alpha / 255 * logo_fade)

        p.setFont(QFont("Segoe UI", 52, QFont.Weight.Bold))
        gt = QLinearGradient(cx-280, 0, cx+280, 0)
        gt.setColorAt(0.0, C_ORG); gt.setColorAt(0.5, C_GOLD); gt.setColorAt(1.0, C_AMB)
        p.setPen(QPen(QBrush(gt), 1))
        p.drawText(QRectF(cx-460, cy_logo-44, 920, 78), Qt.AlignmentFlag.AlignCenter, "J · A · R · V · I · S")

        sub_y = cy_logo + 40
        cursor = "▌" if self._blink else " "
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        p.setPen(QPen(QColor(249,115,22,160)))
        p.drawText(QRectF(cx-440, sub_y, 880, 28), Qt.AlignmentFlag.AlignCenter,
                   f"SOVEREIGN ORCHESTRATOR  ·  CORE v6.0  {cursor}")

        div_y = sub_y + 36
        gd = QLinearGradient(cx-220, 0, cx+220, 0)
        gd.setColorAt(0, QColor(0,0,0,0)); gd.setColorAt(0.3, QColor(249,115,22,110))
        gd.setColorAt(0.7, QColor(249,115,22,110)); gd.setColorAt(1, QColor(0,0,0,0))
        p.setPen(QPen(QBrush(gd), 1))
        p.drawLine(cx-220, div_y, cx+220, div_y)

        p.setOpacity(self._alpha / 255)

        # ── BOOT MESSAGES (phase 3) ────────────────────────────────────────────
        if self._phase >= 3:
            msg_top = cy_globe + 245
            p.setFont(QFont("Consolas", 11))
            shown = min(self._msg_idx + 1, len(_BOOT_MSGS))
            for i in range(max(0, shown-5), shown):
                msg = _BOOT_MSGS[i]
                if i < self._msg_idx:
                    text = msg; col = QColor(120,100,55,130)
                else:
                    text = msg[:self._msg_chars]; col = QColor(249,115,22,255)
                p.setPen(QPen(col))
                row = i - max(0, shown-5)
                p.drawText(QRectF(cx-420, msg_top+row*24, 840, 24),
                           Qt.AlignmentFlag.AlignCenter, text)

        # ── PROGRESS BAR ──────────────────────────────────────────────────────
        if self._phase >= 2:
            bar_y  = int(H * 0.87)
            prog   = min(1.0, (self._t - 2.2) / 3.3)
            bar_w  = 580
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(40,20,5,90))
            p.drawRoundedRect(cx-bar_w//2, bar_y, bar_w, 10, 5, 5)
            fw = int(bar_w * prog)
            if fw > 0:
                gb = QLinearGradient(cx-bar_w//2, 0, cx+bar_w//2, 0)
                gb.setColorAt(0, C_ORG); gb.setColorAt(0.5, C_AMB); gb.setColorAt(1, C_GOLD)
                p.setBrush(QBrush(gb))
                p.drawRoundedRect(cx-bar_w//2, bar_y, fw, 10, 5, 5)
                # Leading glow
                p.setBrush(QColor(255,255,255,220))
                p.drawEllipse(QPointF(cx-bar_w//2+fw, bar_y+5), 5.5, 5.5)
            p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
            p.setPen(QPen(QColor(252,211,77,190)))
            p.drawText(QRectF(cx-bar_w//2, bar_y+16, bar_w, 20),
                       Qt.AlignmentFlag.AlignCenter,
                       f"CORE_INITIALIZATION  {int(prog*100):3d}%")

        # ── CORNERS ───────────────────────────────────────────────────────────
        self._draw_corners(p)

        # ── BOTTOM STRIP ──────────────────────────────────────────────────────
        p.setFont(QFont("Consolas", 8))
        p.setPen(QPen(QColor(249,115,22,55)))
        ts = f"TIMESTAMP: {self._t:06.2f}s  //  PHASE: {self._phase}"
        if self._ready_tracker:
            try:
                s = self._ready_tracker.get_summary()
                ts += f"  //  {s['ready']}/{s['total']} READY"
                if s['degraded']:
                    ts += f"  {s['degraded']} DEGRADED"
                if s['failed']:
                    ts += f"  {s['failed']} FAILED"
            except Exception:
                pass
        else:
            ts += "  //  INITIALIZING..."
        p.drawText(QRectF(0, H-22, W, 20), Qt.AlignmentFlag.AlignCenter, ts)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _draw_grid(self, p, W, H):
        p.setPen(QPen(QColor(249,115,22,14),1))
        sp  = 180
        off = (self._t * 20) % sp
        for x in range(int(-sp+off), W+sp, sp): p.drawLine(x,0,x,H)
        for y in range(int(-sp+off), H+sp, sp): p.drawLine(0,y,W,y)
        p.setPen(QPen(QColor(6,182,212,7),1))
        for i in range(-W, W+H, sp*2): p.drawLine(i,0,i+H,H)

    def _draw_corners(self, p):
        p.setPen(QPen(QColor(249,115,22,95),2.5))
        for corner in self._corners:
            for (x1,y1,x2,y2) in corner:
                p.drawLine(x1,y1,x2,y2)

    def _draw_wireframe_globe(self, p):
        p.setPen(QPen(QColor(249,115,22,32),1))
        size = 290; half = size//2
        for i in range(-5,6):
            lat = i*(size//6)
            r = math.sqrt(max(0, half*half-lat*lat))
            p.drawEllipse(QPointF(0,lat), r, r//3)
        angle_off = self._t * 0.5
        for i in range(6):
            angle = angle_off + i*(PI2/6)
            rw = math.sin(angle)*half
            p.drawEllipse(QPointF(0,0), rw, half)

    def _draw_hex_ring(self, p, r, angle, col, alpha):
        path = QPainterPath()
        for i in range(6):
            a = angle + i*PI2/6
            px, py = math.cos(a)*r, math.sin(a)*r
            if i==0: path.moveTo(px,py)
            else:    path.lineTo(px,py)
        path.closeSubpath()
        c = QColor(col); c.setAlpha(alpha)
        p.setPen(QPen(c,1.8)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
