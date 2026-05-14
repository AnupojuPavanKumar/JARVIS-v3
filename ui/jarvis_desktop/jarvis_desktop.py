# ui/jarvis_desktop/jarvis_desktop.py — JARVIS NEXT-GEN DESKTOP
"""
JARVIS v3 Desktop OS - A futuristic AI-powered productivity workspace

Design Philosophy:
- Workflow-focused, dense, operationally intelligent
- Not a cinematic hologram showcase
- Premium AI operating system from 2045
"""
import math
import datetime
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSizePolicy, QFrame, QScrollArea, QTextEdit,
    QLineEdit, QPushButton, QSplitter
)
from PyQt6.QtCore import Qt, QTimer, QPointF, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient,
    QRadialGradient, QFont, QPainterPath, QCursor,
    QPalette, QGradient
)

from ui.styles import STYLE_SHEET, Theme
from ui.jarvis_desktop.glassmorphic_panel import GlassPanel


class CompactNavItem(QWidget):
    """Compact navigation item with glow indicator."""
    clicked = pyqtSignal(str)

    def __init__(self, label: str, icon: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._icon = icon
        self._active = False
        self._hover = False
        self.setFixedHeight(48)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit(self._label)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        bg_alpha = 25 if self._hover else (60 if self._active else 0)
        p.fillRect(0, 0, w, h, QColor(0, 200, 255, bg_alpha))

        if self._active:
            p.fillRect(0, 0, 3, h, QColor(0, 220, 255, 220))
            p.fillRect(3, 0, 1, h, QColor(0, 180, 255, 60))

        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        color = QColor(200, 230, 255) if self._active else QColor(150, 180, 210)
        p.setPen(color)
        p.drawText(36, h // 2 + 4, self._label)

        p.setFont(QFont("Segoe UI Symbol", 14))
        p.drawText(8, h // 2 + 5, self._icon)


class LeftSidebar(QWidget):
    """Compact intelligent left sidebar navigation."""
    nav_changed = pyqtSignal(str)

    NAV_ITEMS = [
        ("conversations", "\uE8BD"),
        ("workflows", "\uE8A1"),
        ("memory", "\uE8D4"),
        ("projects", "\uE8F1"),
        ("automations", "\uE777"),
        ("runtime", "\uE770"),
        ("analytics", "\uE9D9"),
        ("settings", "\uE713"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = "conversations"
        self._items = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)

        logo = QLabel("J")
        logo.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        logo.setStyleSheet("color: #00DCFF; background: transparent;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedHeight(36)
        layout.addWidget(logo)

        layout.addSpacing(12)

        for label, icon in self.NAV_ITEMS:
            item = CompactNavItem(label, icon)
            item.clicked.connect(self._on_click)
            if label == self._active:
                item.set_active(True)
            self._items[label] = item
            layout.addWidget(item)

        layout.addStretch()

        status = QLabel("● ONLINE")
        status.setFont(QFont("Consolas", 8))
        status.setStyleSheet("color: #00CC88;")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status)

    def _on_click(self, label):
        if label != self._active and label in self._items:
            self._items[self._active].set_active(False)
            self._active = label
            self._items[label].set_active(True)
            self.nav_changed.emit(label)

    def set_active(self, label):
        self._on_click(label)


class ChatMessage(QWidget):
    """Compact chat message bubble."""
    def __init__(self, text: str, is_jarvis: bool, timestamp: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._is_jarvis = is_jarvis
        self._timestamp = timestamp
        self.setMinimumWidth(200)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        bg = QColor(0, 180, 255, 20) if self._is_jarvis else QColor(40, 50, 65, 180)
        p.fillRect(0, 0, w, h, bg)

        if self._is_jarvis:
            p.fillRect(0, 0, 2, h, QColor(0, 200, 255, 150))

        p.setFont(QFont("Segoe UI", 9))
        p.setPen(QColor(200, 220, 240))
        p.drawText(12, 24, w - 24, h - 36, Qt.TextFlag.TextWordWrap, self._text)

        p.setFont(QFont("Consolas", 7))
        p.setPen(QColor(100, 130, 160))
        p.drawText(12, h - 8, self._timestamp)


class ConversationPanel(QWidget):
    """Live conversation workspace."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("CONVERSATION")
        header.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        header.setStyleSheet("color: #00DCFF; background: transparent; letter-spacing: 2px;")
        header.setFixedHeight(32)
        layout.addWidget(header)

        self._chat_area = QScrollArea()
        self._chat_area.setWidgetResizable(True)
        self._chat_area.setStyleSheet("background: transparent; border: none;")
        self._chat_widget = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_widget)
        self._chat_layout.setSpacing(8)
        self._chat_layout.addStretch()
        self._chat_area.setWidget(self._chat_widget)
        layout.addWidget(self._chat_area)

    def add_message(self, text: str, is_jarvis: bool):
        ts = datetime.datetime.now().strftime("%H:%M")
        msg = ChatMessage(text, is_jarvis, ts)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, msg)


class TaskCard(QWidget):
    """Active task card widget."""
    def __init__(self, title: str, status: str, progress: int, parent=None):
        super().__init__(parent)
        self._title = title
        self._status = status
        self._progress = progress
        self.setFixedHeight(56)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(30, 40, 55, 200))
        p.fillRect(w - 3, 0, 3, h, QColor(0, 200, 255, 80))

        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        p.setPen(QColor(220, 240, 255))
        p.drawText(12, 20, self._title)

        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(100, 150, 200))
        p.drawText(12, 36, self._status)

        pg = self._progress / 100.0
        p.fillRect(12, 44, int((w - 24) * pg), 3, QColor(0, 200, 255, 150))


class RuntimePanel(QWidget):
    """Runtime visualization and topology."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = [
            ("JARVIS Core", True),
            ("Voice Engine", True),
            ("Memory", True),
            ("Agent", True),
            ("Skills", True),
            ("Ollama", True),
        ]
        self._anim_offset = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def _tick(self):
        self._anim_offset = (self._anim_offset + 1) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2

        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(100, 130, 160))
        p.drawText(cx - 40, 16, "RUNTIME TOPOLOGY")

        for i, (name, active) in enumerate(self._nodes):
            angle = (i * 60 + self._anim_offset) * math.pi / 180
            r = min(w, h) * 0.35
            nx = cx + r * math.cos(angle)
            ny = cy + r * math.sin(angle)

            color = QColor(0, 220, 255, 200) if active else QColor(100, 100, 100, 100)
            p.setBrush(QBrush(color))
            p.setPen(QPen(color, 2))
            p.drawEllipse(int(nx) - 8, int(ny) - 8, 16, 16)

            p.setPen(QColor(180, 200, 220))
            p.drawText(int(nx - 30), int(ny + 24), name)

            if i > 0:
                prev_angle = ((i - 1) * 60 + self._anim_offset) * math.pi / 180
                px = cx + r * math.cos(prev_angle)
                py = cy + r * math.sin(prev_angle)
                p.setPen(QPen(QColor(0, 180, 255, 60), 1))
                p.drawLine(int(px), int(py), int(nx), int(ny))


class StatusIndicator(QWidget):
    """Runtime status indicator."""
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self.setMinimumHeight(28)

    def set_value(self, value: str):
        self._value = value
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()

        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(100, 130, 160))
        p.drawText(0, 12, self._label)

        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        p.setPen(QColor(0, 220, 255))
        p.drawText(0, 24, self._value)


class RightSidecar(QWidget):
    """AI intelligence layer - right sidecar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("INTELLIGENCE")
        header.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        header.setStyleSheet("color: #00DCFF; letter-spacing: 2px;")
        layout.addWidget(header)

        self._conf = StatusIndicator("CONFIDENCE", "98.5%")
        layout.addWidget(self._conf)

        self._memory = StatusIndicator("MEMORY", "256 items")
        layout.addWidget(self._memory)

        self._tasks = StatusIndicator("ACTIVE TASKS", "3 running")
        layout.addWidget(self._tasks)

        self._queue = StatusIndicator("QUEUE", "2 pending")
        layout.addWidget(self._queue)

        layout.addSpacing(8)
        suggestions = QLabel("SUGGESTIONS")
        suggestions.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        suggestions.setStyleSheet("color: #00DCFF; letter-spacing: 2px;")
        layout.addWidget(suggestions)

        for s in ["Analyze code quality", "Check memory", "Update context"]:
            lbl = QLabel(f"• {s}")
            lbl.setFont(QFont("Segoe UI", 8))
            lbl.setStyleSheet("color: #A0B8D0;")
            layout.addWidget(lbl)

        layout.addStretch()


class CommandBar(QWidget):
    """Premium command interface - bottom command layer."""
    command_entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._mic_btn = QPushButton("\uE720")
        self._mic_btn.setFont(QFont("Segoe UI Symbol", 16))
        self._mic_btn.setFixedSize(40, 40)
        self._mic_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 180, 255, 20);
                border: 1px solid rgba(0, 200, 255, 60);
                border-radius: 20px;
                color: #00DCFF;
            }
            QPushButton:hover {
                background: rgba(0, 180, 255, 40);
                border: 1px solid rgba(0, 200, 255, 100);
            }
        """)
        layout.addWidget(self._mic_btn)

        self._input = QLineEdit()
        self._input.setFont(QFont("Segoe UI", 11))
        self._input.setPlaceholderText("Command JARVIS...")
        self._input.setStyleSheet("""
            QLineEdit {
                background: rgba(30, 40, 55, 200);
                border: 1px solid rgba(0, 200, 255, 40);
                border-radius: 8px;
                padding: 8px 12px;
                color: #E0F0FF;
            }
            QLineEdit:focus {
                border: 1px solid rgba(0, 200, 255, 100);
            }
            QLineEdit::placeholder {
                color: #607080;
            }
        """)
        self._input.returnPressed.connect(self._on_submit)
        layout.addWidget(self._input)

        self._send_btn = QPushButton("\uE724")
        self._send_btn.setFont(QFont("Segoe UI Symbol", 14))
        self._send_btn.setFixedSize(40, 40)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: rgba(0, 200, 255, 30);
                border: 1px solid rgba(0, 200, 255, 80);
                border-radius: 20px;
                color: #00DCFF;
            }
            QPushButton:hover {
                background: rgba(0, 200, 255, 60);
            }
        """)
        self._send_btn.clicked.connect(self._on_submit)
        layout.addWidget(self._send_btn)

    def _on_submit(self):
        text = self._input.text().strip()
        if text:
            self.command_entered.emit(text)
            self._input.clear()


class JarvisDesktop(QWidget):
    """JARVIS Next-Gen Desktop OS Interface."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS OS")
        self.setMinimumSize(1200, 800)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._sidebar = LeftSidebar()
        self._sidebar.setFixedWidth(160)
        self._sidebar.nav_changed.connect(self._on_nav_changed)
        main_layout.addWidget(self._sidebar)

        center_splitter = QSplitter(Qt.Orientation.Vertical)

        workspace = QWidget()
        ws_layout = QHBoxLayout(workspace)
        ws_layout.setContentsMargins(8, 8, 8, 8)
        ws_layout.setSpacing(8)

        self._conversation = ConversationPanel()
        ws_layout.addWidget(self._conversation, 2)

        right_panel = QWidget()
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(0, 0, 0, 0)

        self._runtime = RuntimePanel()
        rp_layout.addWidget(self._runtime, 1)

        rp_layout.addSpacing(8)

        tasks = QLabel("ACTIVE TASKS")
        tasks.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        tasks.setStyleSheet("color: #00DCFF; letter-spacing: 2px;")
        rp_layout.addWidget(tasks)

        for title, status, prog in [
            ("Code Analysis", "Scanning...", 45),
            ("Memory Index", "Building", 70),
            ("Context Update", "Syncing", 25),
        ]:
            card = TaskCard(title, status, prog)
            rp_layout.addWidget(card)

        ws_layout.addWidget(right_panel, 1)

        center_splitter.addWidget(workspace)

        self._command_bar = CommandBar()
        self._command_bar.setFixedHeight(60)
        self._command_bar.command_entered.connect(self._on_command)
        center_splitter.addWidget(self._command_bar)

        center_splitter.setSizes([self.height() - 60, 60])
        main_layout.addWidget(center_splitter, 1)

        self._sidecar = RightSidecar()
        self._sidecar.setFixedWidth(180)
        main_layout.addWidget(self._sidecar)

    def _on_nav_changed(self, section):
        print(f"[Nav] Switched to: {section}")

    def _on_command(self, cmd):
        print(f"[Command] {cmd}")
        self._conversation.add_message(cmd, False)

    def add_response(self, text: str):
        self._conversation.add_message(text, True)

    def set_status(self, status: str):
        pass