# -*- coding: utf-8 -*-
"""
ui_widgets.py  –  All reusable custom widgets for the JARVIS Sovereign UI.
"""

import math, random
from PyQt6.QtWidgets import (QLabel, QPushButton, QWidget,
                              QHBoxLayout, QVBoxLayout, QSizePolicy)
from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve,
                           pyqtProperty, QPointF, QRectF)
from PyQt6.QtGui import (QColor, QFont, QPainter, QPen, QBrush,
                          QRadialGradient, QLinearGradient)

from ui.styles import Theme, get_color


# ─────────────────────────────────────────────────────────────────────────────
# Label factory
# ─────────────────────────────────────────────────────────────────────────────
def _lbl(text: str, font: str = "Segoe UI", size: int = 9,
         bold: bool = False, col: str = Theme.TEXT_PRIMARY,
         ls: float = 0) -> QLabel:
    w = QLabel(text)
    w.setFont(QFont(font, size, QFont.Weight.Bold if bold else QFont.Weight.Normal))
    ss = f"color:{col}; background:transparent;"
    if ls:
        ss += f" letter-spacing:{ls}px;"
    w.setStyleSheet(ss)
    return w


# ─────────────────────────────────────────────────────────────────────────────
# Reactor Icon  (top-bar animated rings)
# ─────────────────────────────────────────────────────────────────────────────
class ReactorIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self._t = 0.0
        t = QTimer(self); t.timeout.connect(self._tick); t.start(40)

    def _tick(self): self._t += 0.05; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        pulse = math.sin(self._t * 3)

        # Outer glow
        g = QRadialGradient(cx, cy, 22)
        g.setColorAt(0.0, QColor(0, 170, 255, 65))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 22, 22)

        # Three rotating rings
        configs = [(18, 40, 110), (13, -28, 160), (8, 60, 210)]
        for i, (r, spd, alpha) in enumerate(configs):
            rot = self._t * spd
            c = QColor(0, 212, 255) if i < 2 else QColor(0, 170, 255)
            c.setAlpha(alpha)
            p.setPen(QPen(c, 1.4 if i < 2 else 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if i == 2:
                p.drawEllipse(QPointF(cx, cy), r, r)
            else:
                span = 270 if i == 0 else 200
                p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2),
                          int(rot % 360) * 16, span * 16)

        # Bright core dot
        core = QRadialGradient(cx, cy, 5 + pulse * 1.0)
        core.setColorAt(0, QColor(255, 255, 255, 255))
        core.setColorAt(0.5, QColor(150, 230, 255, 200))
        core.setColorAt(1, QColor(0, 170, 255, 0))
        p.setBrush(QBrush(core)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5 + pulse * 1.0, 5 + pulse * 1.0)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry Block  (top-bar: label + value + spark-graph)
# ─────────────────────────────────────────────────────────────────────────────
class TelemetryBlock(QWidget):
    def __init__(self, label: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setFixedSize(95, 44)
        self._label = label
        self._unit  = unit
        self._value = 0.0
        # Pre-seed with small random values so bars are visible at startup
        self._hist  = [random.uniform(0, 5) for _ in range(20)]

    def set_value(self, v: float):
        self._value = v
        self._hist.append(v)
        if len(self._hist) > 20:
            self._hist.pop(0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        # Label row
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QColor(160, 210, 255, 140))
        p.drawText(0, 0, W, 14, Qt.AlignmentFlag.AlignLeft, self._label)

        # Value
        p.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        p.setPen(QColor("#ffffff"))
        val_str = (f"{self._value:.0f}" if self._unit == "%"
                   else f"{self._value:.1f}")
        p.drawText(0, 10, W, 22, Qt.AlignmentFlag.AlignLeft, val_str + self._unit)

        # Spark bars
        bar_y = H - 11; bar_h = 9
        bw = W / len(self._hist)
        mx = max(self._hist) or 1
        COLS = {"CPU":QColor(0,170,255),"RAM":QColor(255,215,64),
                "GPU":QColor(0,230,118),"NET":QColor(180,74,255)}
        
        # Match color by substring to support emojis in labels
        bar_c = QColor(0,170,255)
        for key, color in COLS.items():
            if key in self._label:
                bar_c = color
                break
        
        for i, v in enumerate(self._hist):
            fill = max(1, int((v / mx) * bar_h))
            c = QColor(bar_c); c.setAlpha(55 + int(v / mx * 160))
            p.fillRect(int(i * bw), bar_y + bar_h - fill,
                       max(1, int(bw - 1)), fill, c)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Nav Button  (left sidebar item)
# ─────────────────────────────────────────────────────────────────────────────
class NavButton(QPushButton):
    def __init__(self, icon: str, text: str, active: bool = False):
        super().__init__()
        self._icon   = icon
        self._text   = text
        self._active = active
        self._glow   = 1.0 if active else 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QPropertyAnimation(self, b"glow_val", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._apply()

    def get_glow_val(self): return self._glow
    def set_glow_val(self, v): self._glow = v; self._apply()
    glow_val = pyqtProperty(float, fget=get_glow_val, fset=set_glow_val)

    def enterEvent(self, e):
        self._anim.stop(); self._anim.setStartValue(self._glow)
        self._anim.setEndValue(1.0); self._anim.start()

    def leaveEvent(self, e):
        if not self._active:
            self._anim.stop(); self._anim.setStartValue(self._glow)
            self._anim.setEndValue(0.0); self._anim.start()

    def set_active(self, active: bool):
        self._active = active
        self._anim.stop()
        self._anim.setStartValue(self._glow)
        self._anim.setEndValue(1.0 if active else 0.0)
        self._anim.start()

    def _apply(self):
        g = self._glow
        self.setText(f"  {self._icon}   {self._text.upper()}")
        self.setStyleSheet(
            f"QPushButton{{"
            f"background:rgba(0,150,255,{int(5+22*g)});"
            f"border:none;"
            f"border-left:3px solid rgba(0,212,255,{int(55+200*g)});"
            f"color:rgba(200,232,255,{int(110+145*g)});"
            f"text-align:left; padding-left:14px;"
            f"font-size:9px; font-weight:700; letter-spacing:2px;"
            f"border-radius:0px;}}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Ring Chart  (System Monitor donut — 2×2 grid)
# ─────────────────────────────────────────────────────────────────────────────
class RingChart(QWidget):
    def __init__(self, label: str, accent: str, icon: str = "", parent=None):
        super().__init__(parent)
        self.setFixedSize(107, 104)
        self._label  = label
        self._accent = get_color(accent)
        self._v      = 0.0
        self._target = 0.0
        t = QTimer(self); t.timeout.connect(self._ease); t.start(50)

    def set_value(self, pct: float):
        self._target = max(0.0, min(100.0, pct))

    def _ease(self):
        if abs(self._v - self._target) > 0.2:
            self._v += (self._target - self._v) * 0.12
            self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx = W / 2
        # Ring sits in top 80% of widget; label in bottom 20%
        cy = H * 0.44
        r = 32; bw = 7

        # Subtle background disc
        bg = QRadialGradient(cx, cy, r + 6)
        bg.setColorAt(0, QColor(self._accent.red(), self._accent.green(),
                                self._accent.blue(), 12))
        bg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(bg)); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r + 8, r + 8)

        # Track ring
        p.setPen(QPen(QColor(255, 255, 255, 16), bw,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Filled arc (anticlockwise from top)
        if self._v > 0.5:
            c = QColor(self._accent); c.setAlpha(220)
            p.setPen(QPen(c, bw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            span = int(-(self._v / 100.0) * 360 * 16)
            p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 90 * 16, span)

        # Center label (short name like "CPU")
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        p.setPen(QColor(self._accent))
        p.drawText(QRectF(cx - r, cy - 18, r * 2, 14),
                   Qt.AlignmentFlag.AlignCenter, self._label)

        # Center percentage
        p.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        p.setPen(QColor(Theme.TEXT_PRIMARY))
        p.drawText(QRectF(cx - r, cy - 2, r * 2, 18),
                   Qt.AlignmentFlag.AlignCenter, f"{int(self._v)}%")

        # Bottom usage label
        p.setFont(QFont("Segoe UI", 6))
        p.setPen(QColor(Theme.TEXT_SECONDARY))
        p.drawText(QRectF(2, H - 16, W - 4, 14),
                   Qt.AlignmentFlag.AlignCenter, self._label + " USAGE")
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Status Pill  (Subsystems ONLINE / OFFLINE)
# ─────────────────────────────────────────────────────────────────────────────
class StatusPill(QWidget):
    def __init__(self, label: str, icon: str, online: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(6)

        self._icon_lbl = _lbl(icon, size=8, col="#7ab8d4")
        self._icon_lbl.setFixedWidth(14)

        self._name_lbl = _lbl(label.upper(), bold=True, size=7,
                               col="#c8e8ff", ls=0)

        self._pill = QLabel()
        self._pill.setFont(QFont("Segoe UI", 6, QFont.Weight.Bold))
        self._pill.setFixedHeight(16)

        lay.addWidget(self._icon_lbl)
        lay.addWidget(self._name_lbl, 1)
        lay.addWidget(self._pill)

        self.setStyleSheet(
            "QWidget{background:rgba(0,120,255,5);"
            "border-bottom:1px solid rgba(0,170,255,14);}"
        )
        self.set_online(online)

    def set_online(self, state: bool):
        txt = "ONLINE" if state else "OFFLINE"
        col = "#00e676" if state else "#ff3d3d"
        bg  = "rgba(0,230,118,15)" if state else "rgba(255,61,61,15)"
        brd = "rgba(0,230,118,40)" if state else "rgba(255,61,61,40)"
        self._pill.setText(f"  {txt}  ")
        self._pill.setStyleSheet(
            f"color:{col}; background:{bg};"
            f"border:1px solid {brd}; border-radius:8px;"
            f"letter-spacing:1px; padding:0 3px;"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Quick Action Button  (center bottom bar)
# ─────────────────────────────────────────────────────────────────────────────
class QuickActionBtn(QWidget):
    clicked = __import__('PyQt6.QtCore', fromlist=['pyqtSignal']).pyqtSignal()

    def __init__(self, icon: str, title: str, sub: str,
                 accent: str = Theme.ELECTRIC_BLUE, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        ac = get_color(accent)
        r, g, b = ac.red(), ac.green(), ac.blue()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)

        top_row = QHBoxLayout(); top_row.setSpacing(7)
        top_row.addWidget(_lbl(icon, "Segoe UI", 13, col=accent))
        top_row.addWidget(_lbl(title, bold=True, size=8,
                                col=Theme.TEXT_PRIMARY, ls=1))
        top_row.addStretch()
        lay.addLayout(top_row)
        lay.addWidget(_lbl(sub, size=7, col=Theme.TEXT_SECONDARY))

        self.setStyleSheet(
            f"QWidget{{background:rgba({r},{g},{b},7);"
            f"border:1px solid rgba({r},{g},{b},30);"
            f"border-top:1px solid rgba(255,255,255,7);"
            f"border-radius:3px;}}"
            f"QWidget:hover{{background:rgba({r},{g},{b},20);"
            f"border:1px solid rgba({r},{g},{b},80);}}"
        )

    def mousePressEvent(self, e): self.clicked.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Dock Button  (footer)
# ─────────────────────────────────────────────────────────────────────────────
class DockButton(QPushButton):
    def __init__(self, icon: str, core: bool = False, parent=None):
        super().__init__(icon, parent)
        s = 42 if core else 32
        self.setFixedSize(s, s)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if core:
            self.setStyleSheet(
                f"QPushButton{{background:rgba(0,150,255,30);"
                f"border:2px solid rgba(0,200,255,60);"
                f"border-radius:{s//2}px; color:#c8e8ff;"
                f"font-size:16px;}}"
                f"QPushButton:hover{{background:rgba(0,170,255,55);"
                f"border-color:#00d4ff;}}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton{{background:rgba(3,18,36,200);"
                f"border:1px solid rgba(0,170,255,22);"
                f"border-radius:8px; color:rgba(160,210,255,140);"
                f"font-size:13px;}}"
                f"QPushButton:hover{{background:rgba(0,150,255,18);"
                f"border-color:#00aaff;"
                f"color:#c8e8ff;}}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Message Row  (Communications feed)
# ─────────────────────────────────────────────────────────────────────────────
class MsgRow(QWidget):
    def __init__(self, text: str, ts: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(6)

        dot = QLabel("●")
        dot.setFont(QFont("Segoe UI", 6))
        dot.setStyleSheet(f"color:{Theme.GREEN}; background:transparent;")
        dot.setFixedWidth(10)

        msg = _lbl(text, size=8, col=Theme.TEXT_PRIMARY)
        ts_lbl = _lbl(ts, "Consolas", 7, col=Theme.TEXT_SECONDARY)
        ts_lbl.setFixedWidth(50)
        ts_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(dot)
        lay.addWidget(msg, 1)
        lay.addWidget(ts_lbl)

        self.setStyleSheet(
            "QWidget{border-bottom:1px solid rgba(255,255,255,5);"
            "background:transparent;}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Waveform Widget  (JARVIS ONLINE strip + Voice Interface)
# ─────────────────────────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    def __init__(self, color: str = Theme.ELECTRIC_BLUE,
                 height: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._color  = color
        self._active = True          # Always gently animating
        self._t      = 0.0
        self._bars   = 55
        t = QTimer(self); t.timeout.connect(self._tick); t.start(50)

    def set_active(self, v: bool): self._active = v

    def _tick(self): self._t += 0.08; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        mid = H / 2
        bw  = W / self._bars

        for i in range(self._bars):
            if self._active:
                amp = (math.sin(self._t + i * 0.32) * 0.5 +
                       math.sin(self._t * 1.6 + i * 0.18) * 0.35 +
                       random.uniform(-0.04, 0.04)) * (mid * 0.82)
            else:
                amp = math.sin(self._t * 0.35 + i * 0.22) * (mid * 0.12)

            c = QColor(self._color)
            c.setAlpha(int(55 + abs(amp) / max(mid, 1) * 160))
            p.setPen(QPen(c, max(1.0, bw - 1.2)))
            bx = i * bw + bw / 2
            p.drawLine(QPointF(bx, mid - abs(amp)), QPointF(bx, mid + abs(amp)))
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Section Header  (panel title strip)
# ─────────────────────────────────────────────────────────────────────────────
def section_header(icon: str, title: str,
                   accent: str = Theme.ELECTRIC_BLUE) -> QWidget:
    w = QWidget(); w.setFixedHeight(30)
    w.setStyleSheet(
        f"QWidget{{background:rgba(0,140,255,8);"
        f"border-bottom:1px solid rgba(0,170,255,26);"
        f"border-top:1px solid rgba(0,170,255,10);}}"
    )
    lay = QHBoxLayout(w); lay.setContentsMargins(10, 0, 10, 0); lay.setSpacing(6)
    lay.addWidget(_lbl(icon, size=9, col=accent))
    lay.addWidget(_lbl(title, bold=True, size=8, col="#c8e8ff", ls=2))
    lay.addStretch()
    return w
