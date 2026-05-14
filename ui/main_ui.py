# -*- coding: utf-8 -*-
"""
main_ui.py  –  JarvisUI  –  SOVEREIGN ORCHESTRATOR
Top-level QWidget: assembles all panels, wires signals, manages timers.

Layering strategy:
  center_w (QWidget, fills body)
    ├── HUDBackground  (child, no layout, lower()ed behind overlays)
    └── overlays       (child, VBoxLayout fills center_w)
"""

import datetime, time, threading
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QGraphicsOpacityEffect, QStackedWidget
)
from PyQt6.QtCore import (Qt, QTimer, pyqtSignal,
                           QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import QTextCursor

from ui.styles    import STYLE_SHEET, Theme
from ui.hud_bg    import HUDBackground
from ui.panels    import (build_top_bar, build_left_sidebar,
                           build_dashboard_view,
                           build_core_systems_view, build_communications_view,
                           build_subsystems_view, build_quick_actions_view,
                           build_ai_modules_view, build_data_vault_view,
                           build_activity_log_view, build_settings_view,
                           build_right_sidebar, build_bottom_dock, build_status_bar)
from ui.ui_widgets import MsgRow, _lbl

log = logging.getLogger("JarvisUI")


class JarvisUI(QWidget):
    # ── Public signals ────────────────────────────────────────────────
    _ui_result_signal        = pyqtSignal(str)
    request_speak_signal     = pyqtSignal(str)
    command_requested_signal = pyqtSignal(str)
    system_status_signal     = pyqtSignal(str)
    vibe_shield_alert_signal = pyqtSignal(str)
    shutdown_signal          = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("JarvisMain")
        self.setWindowTitle("J.A.R.V.I.S — SOVEREIGN ORCHESTRATOR")
        self.resize(1680, 960)
        self.setMinimumSize(1280, 720)
        self.setStyleSheet(
            f"QWidget#JarvisMain{{background:#020c17;}}" + STYLE_SHEET
        )
        self.mode      = "idle"
        self._t0       = 0.0
        self._uptime_s = 0

        self._build()

        # ── Signal wiring ─────────────────────────────────────────────
        self._ui_result_signal.connect(self._on_result)
        self.system_status_signal.connect(
            lambda t: self._add_msg("SYSTEM", f"[{t}]"),
            Qt.ConnectionType.QueuedConnection
        )

        # ── Timers ────────────────────────────────────────────────────
        clk = QTimer(self); clk.timeout.connect(self._tick_clock); clk.start(1000)
        self._tick_clock()

        hw = QTimer(self); hw.timeout.connect(self._update_hardware); hw.start(2500)
        upt = QTimer(self); upt.timeout.connect(self._tick_uptime); upt.start(1000)

        # Context strip updater (every 5s)
        ctx = QTimer(self); ctx.timeout.connect(self._update_context_strip); ctx.start(5000)
        self._tick_context_strip()

    # ─────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Top bar
        (bar, self._clk, self._dt,
         self._cpu_b, self._ram_b, self._gpu_b, self._net_b,
         search_btn, grid_btn, pwr) = build_top_bar(self)
        pwr.clicked.connect(self.shutdown_signal.emit)
        search_btn.clicked.connect(self._focus_command_search)
        grid_btn.clicked.connect(lambda: self._switch_view(0, "Dashboard"))
        root.addWidget(bar)

        # 2. Body row
        body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)

        # LEFT
        self._lpanel, self._nav = build_left_sidebar()
        body.addWidget(self._lpanel)

        # CENTER  ── key layering fix ──
        self._center_w = QWidget()
        self._center_w.setObjectName("CenterW")
        self._center_w.setStyleSheet("QWidget#CenterW{background:#020c17;}")

        self._hud = HUDBackground(self._center_w)
        self._hud.lower()

        self._stack = QStackedWidget(self._center_w)
        self._stack.setStyleSheet("background:transparent;")

        # Build initial view (Dashboard)
        (self._v_dash, self._wv_top,
         self._rc_cpu, self._rc_ram, self._rc_gpu, self._rc_disk,
         self._dot_ollama, self._dot_voice, self._dot_vision, self._dot_docker,
         self._qa_btns, self._ws_proj_lbl, self._ws_size_lbl, self._ws_path_lbl,
         self._vram_model_lbl, self._vram_pinned_lbl) = build_dashboard_view()
        self._stack.addWidget(self._v_dash)

        # Lazy view placeholders
        self._v_core = None; self._v_comm = None; self._v_subs = None
        self._v_qact = None; self._v_aimo = None; self._v_data = None
        self._v_log  = None; self._v_sett = None

        ov_lay = QVBoxLayout(self._center_w)
        ov_lay.setContentsMargins(0, 0, 0, 0)
        ov_lay.addWidget(self._stack)

        body.addWidget(self._center_w, 1)

        # RIGHT
        (self._rpanel,
         self._chat_lay, self._chat_scr,
         self._term,
         self._cmd, self._send_btn,
         self._mic_btn, self._wv_voice,
         self._ctx_lbl, self._ctx_wf_lbl,
         self._focus_lbl) = build_right_sidebar()
        self._cmd.returnPressed.connect(self._handle_cmd)
        self._send_btn.clicked.connect(self._handle_cmd)
        self._mic_btn.clicked.connect(self._handle_mic)

        # ── Pre-warm gemma2:2b in background ──────────────────────────
        from core.agent.model_prewarmer import get_prewarmer
        get_prewarmer().start()
        body.addWidget(self._rpanel)

        body_w = QWidget(); body_w.setLayout(body)
        root.addWidget(body_w, 1)

        # 3. Bottom dock
        dock, self._core_btn, self._dock_nav = build_bottom_dock()
        root.addWidget(dock)

        # 4. Status bar
        self._sbar, self._uptime_lbl = build_status_bar()
        root.addWidget(self._sbar)

        # Wire navigation buttons
        NAV_MAP = {
            "Dashboard": 0, "Core Systems": 1, "Communications": 2,
            "Subsystems": 3, "Quick Actions": 4, "AI Modules": 5,
            "Data Vault": 6, "Activity Log": 7, "Settings": 8
        }
        for name, idx in NAV_MAP.items():
            if name in self._nav:
                # Use a default argument in the lambda to capture the current loop values
                self._nav[name].clicked.connect(
                    lambda checked, i=idx, n=name: self._switch_view(i, n))

        DOCK_MAP = {
            "shield": ("Settings", 8),
            "terminal": ("Activity Log", 7),
            "core": ("Dashboard", 0),
            "vault": ("Data Vault", 6),
            "ai": ("AI Modules", 5),
            "files": ("Quick Actions", 4),
            "comms": ("Communications", 2),
        }
        for key, (name, idx) in DOCK_MAP.items():
            if key in self._dock_nav:
                self._dock_nav[key].clicked.connect(
                    lambda checked=False, i=idx, n=name: self._switch_view(i, n))

        # Wire quick-action buttons
        for label, cmd in self._get_qa_cmds().items():
            # Original dashboard buttons
            if label in self._qa_btns:
                self._qa_btns[label].clicked.connect(
                    lambda c=cmd: self._handle_quick(c))

        # Seed boot messages after event loop starts
        QTimer.singleShot(300, self._seed_boot)

    # ─────────────────────────────────────────────────────────────────
    # resizeEvent: keep HUD background filling center_w
    # ─────────────────────────────────────────────────────────────────
    def _sync_hud(self):
        if hasattr(self, '_hud') and hasattr(self, '_center_w'):
            self._hud.setGeometry(
                0, 0,
                self._center_w.width(),
                self._center_w.height()
            )

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._sync_hud)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_hud()

    # ─────────────────────────────────────────────────────────────────
    # Boot seed messages
    # ─────────────────────────────────────────────────────────────────
    def _seed_boot(self):
        now = datetime.datetime.now()
        MSGS = [
            ("Neural Pathways Linked",     now - datetime.timedelta(seconds=9)),
            ("Sovereign Core Online",      now - datetime.timedelta(seconds=6)),
            ("Welcome back, Pavan",        now - datetime.timedelta(seconds=3)),
            ("What shall we build today?", now),
        ]
        for txt, t in MSGS:
            row = MsgRow(txt, t.strftime("%H:%M:%S"))
            self._chat_lay.insertWidget(
                max(0, self._chat_lay.count() - 1), row)

        self._log("[SYS] Listening",                          "sys")
        self._log("Agentic core online. Neural pathways linked.", "ok")
        self._log("[SYS] Welcome back, Pavan.",               "sys")
        self._log("[SYS] What are we building today? ▌",      "sys")

    # ─────────────────────────────────────────────────────────────────
    # Clock / uptime
    # ─────────────────────────────────────────────────────────────────
    def _tick_clock(self):
        n = datetime.datetime.now()
        self._clk.setText(n.strftime("%H:%M:%S"))
        self._dt.setText(n.strftime("%A, %d %B %Y").upper())

    def _tick_uptime(self):
        self._uptime_s += 1
        h, rem = divmod(self._uptime_s, 3600)
        m, s   = divmod(rem, 60)
        self._uptime_lbl.setText(f"UPTIME: {h:02d}:{m:02d}:{s:02d}")

    # ─────────────────────────────────────────────────────────────────
    # Hardware telemetry
    # ─────────────────────────────────────────────────────────────────
    def _update_hardware(self):
        try:
            from core.system.hardware_sentinel import get_hardware_sentinel
            s   = get_hardware_sentinel().get_stats()
            cpu = s.get('cpu', 0); ram = s.get('ram', 0)
            self._cpu_b.set_value(cpu); self._rc_cpu.set_value(cpu)
            self._ram_b.set_value(ram); self._rc_ram.set_value(ram)
            if hasattr(self, '_core_rc_cpu'):
                self._core_rc_cpu.set_value(cpu)
            if hasattr(self, '_core_rc_ram'):
                self._core_rc_ram.set_value(ram)
            
            ollama_ok = s.get('ollama_online', False)
            docker_ok = s.get('docker_online', False)
            self._dot_ollama.set_online(ollama_ok)
            self._dot_docker.set_online(docker_ok)
            
            if hasattr(self, '_sub_pills'):
                if "OLLAMA SERVICE" in self._sub_pills:
                    self._sub_pills["OLLAMA SERVICE"].set_online(ollama_ok)
                if "DOCKER SANDBOX" in self._sub_pills:
                    self._sub_pills["DOCKER SANDBOX"].set_online(docker_ok)
        except Exception as e:
            log.debug(f"[UI] Hardware telemetry error: {e}")

        # ── Update Workspace Stats ──
        try:
            from core.system.workspace_manager import get_workspace_manager
            ws = get_workspace_manager()
            import os
            items = os.listdir(ws.desktop_root)
            projs = len([i for i in items if os.path.isdir(os.path.join(ws.desktop_root, i))])
            self._ws_proj_lbl.setText(f"Projects: {projs}")
            self._ws_path_lbl.setText(f"Path: {ws.desktop_root[:25]}...")
        except Exception as e:
            log.debug(f"[UI] Workspace stats error: {e}")

        # ── Update VRAM Stats ──
        try:
            from core.system.vram_orchestrator import get_vram_orchestrator
            vram = get_vram_orchestrator()
            hot = vram.get_active_model() or "None"
            pinned = getattr(vram, "_pinned_model", "None") or "None"
            self._vram_model_lbl.setText(f"Hot: {hot.split(':')[0]}")
            self._vram_pinned_lbl.setText(f"Pinned: {pinned.split(':')[0]}")
        except Exception as e:
            log.debug(f"[UI] VRAM stats error: {e}")

        try:
            from core.system.gpu_probe import get_gpu_stats
            gs = get_gpu_stats()
            if gs:
                v = gs.get('util_pct', 0)
                self._gpu_b.set_value(v)
                self._rc_gpu.set_value(gs.get('used_pct', 0))
                if hasattr(self, '_core_rc_gpu'):
                    self._core_rc_gpu.set_value(v)
        except Exception as e:
            log.debug(f"[UI] GPU stats error: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Messaging helpers
    # ─────────────────────────────────────────────────────────────────
    def _add_msg(self, sender: str, text: str):
        try:
            ts  = datetime.datetime.now().strftime("%H:%M:%S")
            row = MsgRow(f"{sender}: {text}", ts)
            self._chat_lay.insertWidget(
                max(0, self._chat_lay.count() - 1), row)
            QTimer.singleShot(60, self._scroll_bottom)

            if hasattr(self, '_big_chat'):
                html = f'<div style="margin-bottom:8px;">' \
                       f'<b style="color:{Theme.BLUE2};">[{ts}] {sender}:</b> ' \
                       f'<span style="color:{Theme.TEXT_PRIMARY};">{text}</span>' \
                       f'</div>'
                self._big_chat.append(html)
        except RuntimeError:
            pass

    def _scroll_bottom(self):
        try:
            sb = self._chat_scr.verticalScrollBar()
            sb.setValue(sb.maximum())
        except RuntimeError:
            pass

    def _log(self, msg: str, kind: str = "sys"):
        try:
            ts  = datetime.datetime.now().strftime("%H:%M:%S")
            col = {"sys": Theme.CYAN, "ok": Theme.GREEN,
                   "err": Theme.RED,  "ai": Theme.AMBER
                   }.get(kind, Theme.TEXT_SECONDARY)
            html = f'<span style="color:{col};">[{ts}] {msg}</span>'
            self._term.append(html)
            self._term.moveCursor(QTextCursor.MoveOperation.End)
            
            if hasattr(self, '_full_log'):
                self._full_log.append(html)
                self._full_log.moveCursor(QTextCursor.MoveOperation.End)
        except RuntimeError:
            pass

    # ─────────────────────────────────────────────────────────────────
    # Context awareness strip
    # ─────────────────────────────────────────────────────────────────
    def _tick_context_strip(self):
        """Initial context strip update."""
        self._update_context_strip()

    def _update_context_strip(self):
        """Update the context awareness strip with current workspace state."""
        try:
            from core.context.workspace import get_workspace_observer
            from core.context.attention import get_attention_model
            from core.context.privacy import get_privacy_controls

            ws = get_workspace_observer()
            am = get_attention_model()
            pc = get_privacy_controls()

            if pc.is_paused():
                if hasattr(self, "_ctx_lbl"):
                    self._ctx_lbl.setText("paused")
                    self._ctx_lbl.setStyleSheet(f"color:{Theme.TEXT_MUTED};background:transparent;font-size:8px;")
                    self._ctx_wf_lbl.setText("")
                    self._focus_lbl.setText("privacy")
                    self._focus_lbl.setStyleSheet(f"color:{Theme.TEXT_MUTED};background:transparent;font-size:7px;")
                return

            ctx = ws.get_context_summary()
            cat = ctx.get("category", "idle") or "idle"
            workflow = ctx.get("workflow") or ""
            app = ctx.get("app", "") or ""
            short_app = app[:15] if app else ""

            if hasattr(self, "_ctx_lbl"):
                label = f"{cat.title()}"
                if short_app:
                    label = f"{short_app} · {cat.title()}"
                self._ctx_lbl.setText(label)
                self._ctx_lbl.setStyleSheet(f"color:{Theme.BLUE2};background:transparent;font-size:8px;")

            if hasattr(self, "_ctx_wf_lbl"):
                wf = workflow.replace("_", " ").title() if workflow else ""
                self._ctx_wf_lbl.setText(wf)
                self._ctx_wf_lbl.setStyleSheet(f"color:{Theme.GREEN};background:transparent;font-size:7px;")

            state = am.state
            focus_col = {Theme.GREEN: "active", Theme.AMBER: "relaxed",
                         Theme.RED: "focused", Theme.TEXT_MUTED: "idle"}.get(
                Theme.GREEN if state.level in ("active", "relaxed") else
                Theme.AMBER if state.level == "focused" else Theme.TEXT_MUTED, "active"
            )
            if hasattr(self, "_focus_lbl"):
                self._focus_lbl.setText(state.level)
                fc = {"active": Theme.GREEN, "relaxed": Theme.AMBER,
                      "focused": Theme.RED, "idle": Theme.TEXT_MUTED,
                      "absent": Theme.TEXT_MUTED}.get(state.level, Theme.TEXT_SECONDARY)
                self._focus_lbl.setStyleSheet(f"color:{fc};background:transparent;font-size:7px;")
        except Exception as e:
            log.debug(f"[UI] Context strip error: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Command handling
    # ─────────────────────────────────────────────────────────────────
    def _handle_mic(self):
        """Mic button: activate voice listening UI, then submit."""
        self.set_status("Listening")
        self._wv_voice.set_active(True)
        self._log("VOICE > Microphone activated", "sys")
        self._add_msg("YOU", "[voice input]")

    def _handle_cmd(self):
        raw = self._cmd.text().strip()
        if not raw: return
        self._cmd.clear()
        self._add_msg("YOU", raw)
        self._log(f"CMD > {raw}")
        self._t0 = time.time()
        
        # Phase 3: Human Friction Analysis
        # Detect manual overrides, abandonments, and corrections.
        lower_cmd = raw.lower()
        if any(w in lower_cmd for w in ["stop", "cancel", "abort", "quit"]):
            from core.analytics.failure_journal import get_failure_journal
            get_failure_journal().log_friction("abandoned_execution", raw, 0)
        elif any(w in lower_cmd for w in ["no", "wrong", "not that", "incorrect"]):
            from core.analytics.failure_journal import get_failure_journal
            get_failure_journal().log_friction("corrected_output", raw, 0)
            
        self.command_requested_signal.emit(raw)

    def _handle_quick(self, cmd: str):
        self._add_msg("YOU", cmd)
        self._log(f"QA  > {cmd}")
        self._t0 = time.time()
        self._apply_quick_action(cmd)
        self.command_requested_signal.emit(cmd)

    def _focus_command_search(self):
        self._switch_view(2, "Communications")
        self._cmd.setPlaceholderText("Search, ask, or type a direct command...")
        self._cmd.setFocus()
        self._log("SEARCH > Command input focused", "sys")

    def _apply_quick_action(self, cmd: str):
        lowered = cmd.lower().strip()
        if lowered.endswith("mode"):
            self.mode = lowered.replace(" ", "_")
            self.set_status(f"{cmd.title()} Active")
            if lowered == "code mode":
                self._switch_view(5, "AI Modules")
            elif lowered == "study mode":
                self._switch_view(6, "Data Vault")
            elif lowered == "gaming mode":
                self._switch_view(1, "Core Systems")
            elif lowered == "night mode":
                self._wv_top.set_active(False)
                self._wv_voice.set_active(False)
            self._log(f"MODE > {cmd.title()} engaged", "ok")
            return

        if lowered == "run diagnostics":
            self._update_hardware()
            self._switch_view(1, "Core Systems")
            self.set_status("Diagnostics Complete")
            self._log("DIAG > Hardware telemetry refreshed", "ok")
            return

        if lowered == "system cleanup":
            try:
                from core.system.db import get_db
                summary = get_db().vacuum(prune_telemetry_days=7)
                self._log(f"CLEANUP > {summary}", "ok")
                self.set_status("Cleanup Complete")
            except Exception as exc:
                self._log(f"CLEANUP > {exc}", "err")

    def _on_result(self, result: str):
        try:
            if result in ("STOP", "EXIT", ""): return
            self._add_msg("JARVIS", result)
            self._log(f"AI  > {result[:70]}", "ai")
            self.request_speak_signal.emit(result)
            self._wv_voice.set_active(True)
            QTimer.singleShot(8000, lambda: self._wv_voice.set_active(False))
        except RuntimeError:
            pass

    # ─────────────────────────────────────────────────────────────────
    # Public API (called by main.py)
    # ─────────────────────────────────────────────────────────────────
    def set_result(self, text: str):
        self._ui_result_signal.emit(text)

    def set_status(self, status: str):
        self._log(f"SYS > {status}")
        self._wv_voice.set_active(status == "Listening")

    def set_speaking(self, speaking: bool):
        self._wv_voice.set_active(speaking)

    def reveal_ui(self):
        self._log("Interface online.", "ok")
        self.show(); self.raise_()
        eff  = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(1000); anim.setStartValue(0.0); anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic); anim.start()
        self._reveal_anim = anim

    # ─────────────────────────────────────────────────────────────────
    # Navigation
    # ─────────────────────────────────────────────────────────────────
    def _switch_view(self, index: int, name: str):
        # Lazy initialization
        if name == "Core Systems" and self._v_core is None:
            (self._v_core, self._core_rc_cpu,
             self._core_rc_ram, self._core_rc_gpu) = build_core_systems_view()
            self._stack.insertWidget(1, self._v_core)
            
        elif name == "Communications" and self._v_comm is None:
            self._v_comm, self._big_chat = build_communications_view()
            self._stack.insertWidget(2, self._v_comm)
            
        elif name == "Subsystems" and self._v_subs is None:
            self._v_subs, self._sub_pills = build_subsystems_view()
            self._stack.insertWidget(3, self._v_subs)
            
        elif name == "Quick Actions" and self._v_qact is None:
            self._v_qact, self._view_qa_btns = build_quick_actions_view()
            self._stack.insertWidget(4, self._v_qact)
            # Wire new buttons
            for label, cmd in self._get_qa_cmds().items():
                if label in self._view_qa_btns:
                    self._view_qa_btns[label].clicked.connect(
                        lambda c=cmd: self._handle_quick(c))
            
        elif name == "AI Modules" and self._v_aimo is None:
            self._v_aimo = build_ai_modules_view()
            self._stack.insertWidget(5, self._v_aimo)
            
        elif name == "Data Vault" and self._v_data is None:
            self._v_data = build_data_vault_view()
            self._stack.insertWidget(6, self._v_data)
            
        elif name == "Activity Log" and self._v_log is None:
            self._v_log, self._full_log = build_activity_log_view()
            self._stack.insertWidget(7, self._v_log)
            
        elif name == "Settings" and self._v_sett is None:
            self._v_sett = build_settings_view()
            self._stack.insertWidget(8, self._v_sett)

        self._stack.setCurrentIndex(index)
        for n, btn in self._nav.items():
            btn.set_active(n == name)
        self._log(f"Switched to {name.upper()}", "sys")

    def _get_qa_cmds(self):
        return {
            "CODE MODE":     "code mode",
            "STUDY MODE":    "study mode",
            "GAMING MODE":   "gaming mode",
            "NIGHT MODE":    "night mode",
            "DIAGNOSTICS":   "run diagnostics",
            "SYSTEM CLEANUP":"system cleanup",
        }
