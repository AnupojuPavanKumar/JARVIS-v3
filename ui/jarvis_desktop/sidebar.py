# ui/jarvis_desktop/sidebar.py — JARVIS ANIMATED SIDEBAR
"""
Elegant vertical navigation sidebar with glowing icons and smooth hover animations.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal, QRectF
from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                          QPainterPath, QFont, QIcon, QPixmap, QTransform)


class SidebarIcon(QWidget):
    """A single glowing sidebar icon with hover animation."""
    clicked = pyqtSignal()

    def __init__(self, label: str, icon_char: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon_char = icon_char
        self._hover = 0.0
        self._active = False
        self._glow = 0.0
        self._t = 0.0
        self.setMinimumSize(44, 44)
        self.setMaximumSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_active(self, active: bool):
        self._active = active
        self._glow = 1.0 if active else 0.0
        self.update()

    def enterEvent(self, _):
        self._hover = 1.0

    def leaveEvent(self, _):
        self._hover = 0.0

    def mousePressEvent(self, _):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # Smooth hover animation
        self._glow += (1.0 if self._active else 0.0 - self._glow) * 0.1
        hover_a = int(self._hover * 30)
        glow_a = int(self._glow * 60)

        # Background highlight
        if self._glow > 0.01 or self._hover > 0.01:
            p.save()
            p.setOpacity((glow_a + hover_a) / 255 * 0.4)
            path = QPainterPath()
            path.addRoundedRect(QRectF(4, 4, w - 8, h - 8), 6, 6)
            p.fillPath(path, QBrush(QColor(0, 180, 255, 60)))
            p.restore()

        # Glow ring
        if self._glow > 0.01:
            p.save()
            p.setOpacity(glow_a / 255 * 0.5)
            pen = QPen(QColor(0, 200, 255, glow_a), 1.5)
            p.setPen(pen)
            p.drawRoundedRect(3, 3, w - 6, h - 6, 7, 7)
            p.restore()

        # Icon
        color = QColor(0, 220, 255, 200 + glow_a) if self._active else QColor(140, 170, 200, 180)
        p.save()
        font = QFont("Segoe MDL2 Assets", 16)
        font2 = QFont("Segoe UI Symbol", 14)
        p.setFont(font)
        p.setPen(color)
        p.drawText(int(cx - 8), int(cy + 5), self._icon_char)
        p.restore()

        # Label below icon
        p.save()
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Normal))
        p.setPen(QColor(120, 160, 200, 180 if self._active else 140))
        p.drawText(0, h - 2, w, 10, Qt.AlignmentFlag.AlignCenter, self._label)
        p.restore()


class AnimatedSidebar(QWidget):
    """
    Vertical sidebar with navigation items and bottom status.
    """
    navigation_changed = pyqtSignal(str)

    NAV_ITEMS = [
        ("Home", "\u2302"),          # Home
        ("Conversations", "\uE8BD"), # Chat
        ("Workflows", "\uE8A1"),     # Workflow
        ("Systems", "\uE770"),        # Systems
        ("Memory Core", "\uE8D4"),    # Memory
        ("Applications", "\uE8F1"),  # Apps
        ("Automations", "\uE777"),    # Auto
        ("Analytics", "\uE9D9"),     # Stats
        ("Settings", "\uE713"),        # Settings
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = "Home"
        self._icons = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        # Logo / branding at top
        self._logo_label = QLabel()
        self._logo_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self._logo_label.setStyleSheet("color: rgba(0,200,255,220); background: transparent;")
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_label.setText("J")
        self._logo_label.setFixedHeight(40)
        layout.addWidget(self._logo_label)

        layout.addSpacing(12)

        # Navigation icons
        for label, icon in self.NAV_ITEMS:
            icon_w = SidebarIcon(label, icon)
            # FIX: Use default argument to capture label properly
            icon_w.clicked.connect(lambda l=label: self._on_nav(l))
            if label == self._active:
                icon_w.set_active(True)
            self._icons[label] = icon_w
            layout.addWidget(icon_w)

        layout.addStretch()

        # Status indicator at bottom
        self._status = QLabel()
        self._status.setFont(QFont("Consolas", 7))
        self._status.setStyleSheet("color: rgba(0,200,150,180); background: transparent;")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setText("● ONLINE")
        layout.addWidget(self._status)

    def _on_nav(self, label: str):
        if label == self._active:
            return
        # Deactivate previous
        if self._active in self._icons:
            self._icons[self._active].set_active(False)
        # Activate new
        self._active = label
        if label in self._icons:
            self._icons[label].set_active(True)
        self.navigation_changed.emit(label)

    def set_active(self, label: str):
        self._on_nav(label)