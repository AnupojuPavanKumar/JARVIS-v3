"""
ui/auth_window.py - JARVIS authentication window.

Flow:
1. First run: create owner profile + PIN + Enroll Face.
2. Normal run: try FaceID + Mobile biometric handoff through auth_bridge.
3. If FaceID/mobile auth fails: fall back to PIN entry.
"""

import threading
import time
import cv2
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect, QPointF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from auth.auth_manager import AuthManager
from core import auth_bridge


from ui.styles import Theme, get_color

COL_YELLOW = get_color(Theme.AMBER)
COL_CYAN   = get_color(Theme.CYAN)
COL_BLUE   = get_color(Theme.ORANGE) # Using Orange as Primary instead of Blue
COL_RED    = get_color(Theme.RED)
COL_TEAL   = get_color(Theme.GREEN)

TIMEOUT_MS = 20_000
POLL_MS = 500


class ArcReactorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(300, 300)
        self._color = COL_BLUE
        self._mode = "idle"
        self._progress = 0.0
        self._pulse_alpha = 40
        self._pulse_dir = 1
        self._rotation = 0.0
        self._inner_rot = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(24) # Higher tick rate for smoothness

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode == "yellow":   self._color = COL_YELLOW
        elif mode == "cyan":   self._color = COL_CYAN
        elif mode == "red":    self._color = COL_RED
        elif mode == "teal":   self._color = COL_TEAL
        else:                  self._color = COL_BLUE
        self.update()

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, value))
        self.update()

    def _tick(self) -> None:
        self._rotation = (self._rotation + 1.5) % 360
        self._inner_rot = (self._inner_rot - 2.8) % 360
        self._pulse_alpha += 6 * self._pulse_dir
        if self._pulse_alpha >= 200 or self._pulse_alpha <= 40:
            self._pulse_dir *= -1
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() // 2, self.height() // 2
        radius = (self.width() - 60) // 2

        # 1. Subtle core glow
        glow = QRadialGradient(cx, cy, radius * 1.5)
        c = QColor(self._color); c.setAlpha(int(self._pulse_alpha * 0.25))
        glow.setColorAt(0.0, c); glow.setColorAt(1.0, QColor(0,0,0,0))
        p.setBrush(glow); p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius * 1.5, radius * 1.5)

        # 2. Main Shell
        p.setBrush(QColor(10, 5, 2, 220)); p.setPen(QPen(QColor(self._color).lighter(120), 1))
        p.drawEllipse(cx-radius, cy-radius, radius*2, radius*2)

        # 3. Rotating Outer Rings
        p.save(); p.translate(cx, cy); p.rotate(self._rotation)
        pen = QPen(QColor(self._color)); pen.setWidth(2); pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([15, 35]); p.setPen(pen)
        p.drawEllipse(-radius-15, -radius-15, (radius+15)*2, (radius+15)*2)
        p.restore()

        p.save(); p.translate(cx, cy); p.rotate(self._inner_rot)
        c = QColor(self._color); c.setAlpha(100)
        pen = QPen(c); pen.setWidth(1)
        p.setPen(pen)
        for i in range(8):
            p.rotate(45); p.drawLine(radius-10, 0, radius+5, 0)
        p.restore()

        # 4. Progress Arc
        span = int(self._progress * 360 * 16)
        if span > 0:
            arc_pen = QPen(self._color); arc_pen.setWidth(6); arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(arc_pen)
            p.drawArc(cx-radius-8, cy-radius-8, (radius+8)*2, (radius+8)*2, 90*16, -span)

        # 5. Core Symbol
        symbol = {"yellow":"M","cyan":"OK","red":"X","teal":"LINK","idle":"J"}.get(self._mode, "J")
        p.setPen(QColor(self._color))
        p.setFont(QFont("Segoe UI Semibold", 24, QFont.Weight.Bold))
        p.drawText(cx-60, cy-30, 120, 60, Qt.AlignmentFlag.AlignCenter, symbol)



DARK_STYLE = f"""
QWidget#AuthRoot {{
    background-color: {Theme.BG};
    border: 1px solid rgba(249, 115, 22, 40);
    border-radius: 14px;
}}
QLabel {{
    font-family: 'Segoe UI', sans-serif;
}}
QLabel#title {{
    color: {Theme.ORANGE};
    font-size: 22px;
    font-weight: 600;
    letter-spacing: 4px;
}}
QLabel#subtitle {{
    color: {Theme.MUTED};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QLabel#status {{
    color: {Theme.CYAN};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#hint {{
    color: {Theme.MUTED};
    font-size: 9px;
    letter-spacing: 1px;
}}
QLineEdit {{
    background: rgba(249, 115, 22, 10);
    border: 1px solid rgba(249, 115, 22, 30);
    border-radius: 8px;
    color: {Theme.TEXT};
    font-size: 15px;
    padding: 10px 14px;
}}
QLineEdit#pin_input {{
    font-size: 18px;
    letter-spacing: 12px;
    font-weight: bold;
}}
QLineEdit:focus {{
    border: 1px solid {Theme.ORANGE};
    background: rgba(249, 115, 22, 20);
}}
QPushButton#pin_btn {{
    background: transparent;
    border: 1px solid {Theme.ORANGE};
    border-radius: 8px;
    color: {Theme.ORANGE};
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 2px;
    padding: 10px 18px;
}}
QPushButton#pin_btn:hover {{
    background: rgba(249, 115, 22, 0.12);
    color: {Theme.GOLD};
    border-color: {Theme.GOLD};
}}
"""


class AuthWindow(QWidget):
    auth_success = pyqtSignal()

    def __init__(self, identity_manager, auto_start: bool = True):
        super().__init__()
        self.setObjectName("AuthRoot")
        self.setWindowTitle("JARVIS - Access")
        self.setFixedSize(400, 560)
        self.setStyleSheet(DARK_STYLE)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.id_manager = identity_manager
        self.secure_auth = AuthManager()
        self._poll_timer: QTimer | None = None
        self._cam_timer: QTimer | None = None
        self._countdown: QTimer | None = None
        self._elapsed_ms = 0
        self._face_detected = False

        self._build_ui()

        if auto_start:
            QTimer.singleShot(300, self.start_auth)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)

        bg_frame = QFrame()
        bg_frame.setObjectName("AuthRoot")
        main_layout.addWidget(bg_frame)

        root = QVBoxLayout(bg_frame)
        root.setContentsMargins(32, 28, 32, 32)
        root.setSpacing(14)

        title = QLabel("J A R V I S")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("SECURE OWNER AUTHENTICATION")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")

        # Page 0: Face Recognition
        page_face = QWidget()
        face_layout = QVBoxLayout(page_face)
        face_layout.setSpacing(10)
        self.face_preview = QLabel()
        self.face_preview.setFixedSize(280, 210)
        self.face_preview.setStyleSheet("background: #000; border: 1px solid #1E293B; border-radius: 8px;")
        fp_row = QHBoxLayout()
        fp_row.addStretch(); fp_row.addWidget(self.face_preview); fp_row.addStretch()
        self.face_status = QLabel("INITIALIZING CAMERA")
        self.face_status.setObjectName("status")
        self.face_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        face_layout.addLayout(fp_row)
        face_layout.addWidget(self.face_status)
        face_layout.addStretch()

        # Page 1: Mobile verification
        page_mobile = QWidget()
        mobile_layout = QVBoxLayout(page_mobile)
        mobile_layout.setSpacing(10)
        self.reactor = ArcReactorWidget()
        reactor_row = QHBoxLayout()
        reactor_row.addStretch(); reactor_row.addWidget(self.reactor); reactor_row.addStretch()
        self.status_lbl = QLabel("INITIALIZING")
        self.status_lbl.setObjectName("status"); self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_lbl = QLabel(""); self.hint_lbl.setObjectName("hint"); self.hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mobile_layout.addLayout(reactor_row)
        mobile_layout.addWidget(self.status_lbl); mobile_layout.addWidget(self.hint_lbl)

        # Page 2: PIN
        page_pin = QWidget()
        pin_layout = QVBoxLayout(page_pin)
        pin_layout.setContentsMargins(0, 30, 0, 30); pin_layout.setSpacing(12)
        pin_label = QLabel("MANUAL OVERRIDE REQUIRED"); pin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pin_label.setStyleSheet("color: #F59E0B; font-size: 11px; font-weight: bold; letter-spacing: 2px;")
        self.pin_input = QLineEdit(); self.pin_input.setObjectName("pin_input")
        self.pin_input.setPlaceholderText("* * * *"); self.pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin_input.setAlignment(Qt.AlignmentFlag.AlignCenter); self.pin_input.setMaxLength(8)
        self.pin_input.returnPressed.connect(self._check_pin)
        self.pin_btn = QPushButton("AUTHORIZE"); self.pin_btn.setObjectName("pin_btn"); self.pin_btn.clicked.connect(self._check_pin)
        self.pin_status = QLabel(""); self.pin_status.setObjectName("status"); self.pin_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pin_layout.addWidget(pin_label); pin_layout.addWidget(self.pin_input); pin_layout.addWidget(self.pin_btn); pin_layout.addWidget(self.pin_status); pin_layout.addStretch()

        # Page 3: Setup
        page_setup = QWidget()
        setup_layout = QVBoxLayout(page_setup)
        setup_layout.setContentsMargins(0, 20, 0, 20); setup_layout.setSpacing(12)
        setup_label = QLabel("FIRST RUN OWNER SETUP"); setup_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        setup_label.setStyleSheet("color: #22D3EE; font-size: 11px; font-weight: bold; letter-spacing: 2px;")
        self.name_input = QLineEdit(); self.name_input.setPlaceholderText("Owner name")
        self.name_input.setAlignment(Qt.AlignmentFlag.AlignCenter); self.name_input.setMaxLength(32)
        self.setup_pin_input = QLineEdit(); self.setup_pin_input.setObjectName("pin_input")
        self.setup_pin_input.setPlaceholderText("Create PIN"); self.setup_pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_pin_input.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setup_pin_input.setMaxLength(8)
        self.setup_pin_confirm = QLineEdit(); self.setup_pin_confirm.setObjectName("pin_input")
        self.setup_pin_confirm.setPlaceholderText("Confirm PIN"); self.setup_pin_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.setup_pin_confirm.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setup_pin_confirm.setMaxLength(8)
        self.setup_btn = QPushButton("ENROLL FACE & FINISH"); self.setup_btn.setObjectName("pin_btn"); self.setup_btn.clicked.connect(self._submit_setup)
        self.setup_status = QLabel(""); self.setup_status.setObjectName("status"); self.setup_status.setAlignment(Qt.AlignmentFlag.AlignCenter); self.setup_status.setWordWrap(True)
        setup_layout.addWidget(setup_label); setup_layout.addWidget(self.name_input); setup_layout.addWidget(self.setup_pin_input); setup_layout.addWidget(self.setup_pin_confirm); setup_layout.addWidget(self.setup_btn); setup_layout.addWidget(self.setup_status); setup_layout.addStretch()

        self.stack.addWidget(page_face)    # 0
        self.stack.addWidget(page_mobile)  # 1
        self.stack.addWidget(page_pin)     # 2
        self.stack.addWidget(page_setup)   # 3

        root.addWidget(title); root.addWidget(subtitle); root.addSpacing(4); root.addWidget(self.stack)

    def start_auth(self):
        self.id_manager.load_profile()
        if self.id_manager.requires_initial_setup():
            self._show_setup()
            return
        self._begin_face_auth()

    def _begin_face_auth(self):
        self.stack.setCurrentIndex(0)
        self.face_status.setText("SEARCHING FOR OWNER")
        from core.api.camera_manager import CameraManager
        self._cam = CameraManager.get_instance()
        self._cam_timer = QTimer(self)
        self._cam_timer.timeout.connect(self._process_face_frame)
        self._cam_timer.start(50)
        # Timeout face ID after 10 seconds and go to mobile/PIN
        QTimer.singleShot(10000, self._on_face_timeout)

    def _process_face_frame(self):
        frame = self._cam.get_frame()
        if frame is None: return
        
        # Quick check
        status, conf = self.id_manager.auth.quick_check(frame)
        
        # Display preview
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.face_preview.setPixmap(QPixmap.fromImage(img).scaled(280, 210, Qt.AspectRatioMode.KeepAspectRatio))
        
        if status == "owner":
            self.face_status.setText(f"OWNER DETECTED (Conf: {conf:.0f})")
            self.face_status.setStyleSheet("color: #2CD4BF;")
            self._cam_timer.stop()
            self._finish_success("Biometric identification successful.")

    def _on_face_timeout(self):
        if self._cam_timer and self._cam_timer.isActive():
            self._cam_timer.stop()
            self.face_status.setText("FACE ID TIMEOUT")
            QTimer.singleShot(1000, self._begin_mobile_auth)

    def _begin_mobile_auth(self):
        self.stack.setCurrentIndex(1)
        self._elapsed_ms = 0
        self.status_lbl.setStyleSheet("color: #22D3EE;") # Cyan for neural link
        self.status_lbl.setText("MOBILE FACEAUTH CHALLENGE")
        
        from core.providers.ntfy_launcher import NTFY_URL
        self.hint_lbl.setText("Awaiting biometric handshake from your device...")
        self.reactor.set_mode("teal") # Teal for biometric mode
        self.reactor.set_progress(0.0)

        if not auth_bridge.ping_sync():
            self.status_lbl.setStyleSheet("color: #F87171;")
            self.status_lbl.setText("MOBILE AUTH UNAVAILABLE")
            self.hint_lbl.setText("Falling back to PIN verification.")
            QTimer.singleShot(1000, self._show_pin)
            return

        auth_bridge.start_session(timeout_sec=TIMEOUT_MS/1000)
        self._countdown = QTimer(self)
        self._countdown.timeout.connect(self._update_progress)
        self._countdown.start(100)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_auth_state)
        self._poll_timer.start(POLL_MS)

    def _update_progress(self):
        self._elapsed_ms += 100
        self.reactor.set_progress(min(1.0, self._elapsed_ms / TIMEOUT_MS))

    def _poll_auth_state(self):
        if auth_bridge.is_verified:
            self._finish_success("Remote identity verified.")
        elif auth_bridge.is_timed_out:
            self._show_pin()

    def _stop_auth_timers(self):
        for timer in (self._poll_timer, self._countdown, self._cam_timer):
            if timer and timer.isActive():
                timer.stop()

    def _show_pin(self):
        self._stop_auth_timers()
        self.stack.setCurrentIndex(2)
        self.pin_status.setText("")
        self.pin_input.clear(); self.pin_input.setFocus()
        self.reactor.set_mode("red")

    def _show_setup(self):
        self.stack.setCurrentIndex(3)
        self.setup_status.setText("")
        self.name_input.setFocus()

    def _finish_success(self, message: str):
        self._stop_auth_timers()
        self.id_manager.mark_authenticated()
        self.id_manager.identity = "owner"
        # UI Feedback
        if self.stack.currentIndex() != 1: # If not on reactor page, show it for success
            self.stack.setCurrentIndex(1)
        self.status_lbl.setStyleSheet("color: #2CD4BF;")
        self.status_lbl.setText("ACCESS GRANTED")
        self.hint_lbl.setText(message)
        self.reactor.set_mode("cyan")
        self.reactor.set_progress(1.0)
        QTimer.singleShot(1500, self.auth_success.emit)
        QTimer.singleShot(1600, self.close)

    def _check_pin(self):
        pin = self.pin_input.text().strip()
        if not pin: return
        success, message = self.id_manager.verify_pin(pin)
        if success:
            self.pin_status.setStyleSheet("color: #2CD4BF;")
            self.pin_status.setText("PIN ACCEPTED.")
            self._finish_success("Manual override accepted.")
        else:
            self.pin_status.setStyleSheet("color: #F87171;")
            self.pin_status.setText(message.upper())
            self.pin_input.clear()

    def _submit_setup(self):
        owner_name = self.name_input.text().strip()
        pin = self.setup_pin_input.text().strip()
        confirm = self.setup_pin_confirm.text().strip()

        if not owner_name:
            self.setup_status.setText("Enter an owner name.")
            return
        if len(pin) < 4:
            self.setup_status.setText("PIN must be 4+ digits.")
            return
        if pin != confirm:
            self.setup_status.setText("PINs do not match.")
            return

        self.setup_status.setText("ENROLLING FACE... LOOK AT CAMERA")
        # Run enrollment in thread to avoid UI freeze
        def _enroll():
            try:
                if self.id_manager.auth.enroll_owner():
                    self.id_manager.setup_owner(owner_name, pin)
                    QTimer.singleShot(0, lambda: self._finish_success("Owner profile and FaceID established."))
                else:
                    QTimer.singleShot(0, lambda: self.setup_status.setText("Face enrollment failed. Try again."))
            except Exception as e:
                QTimer.singleShot(0, lambda: self.setup_status.setText(f"Error: {e}"))

        threading.Thread(target=_enroll, daemon=True).start()

    def closeEvent(self, event):
        self._stop_auth_timers()
        super().closeEvent(event)
