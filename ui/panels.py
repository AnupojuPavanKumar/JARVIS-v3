# -*- coding: utf-8 -*-
import datetime
import os
import random
import sqlite3
from PyQt6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QTextEdit,
    QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor
from ui.styles import Theme
from ui.ui_widgets import (
    _lbl, ReactorIcon, TelemetryBlock, NavButton,
    RingChart, StatusPill, QuickActionBtn, DockButton,
    MsgRow, WaveformWidget, section_header
)

_SETTING_KEYS = [
    "hud_dynamic_scaling", "neural_feed_verbosity", "glass_blur", "animations",
    "link_encryption", "biometric_auth", "local_only", "vibe_shield",
]

# ── Glass card helper ──────────────────────────────────────────────────────────
def _card(border="rgba(0,170,255,28)", radius=6):
    f = QFrame()
    f.setStyleSheet(
        f"QFrame{{background:rgba(2,12,26,210);"
        f"border:1px solid {border};"
        f"border-top:1px solid rgba(0,212,255,18);"
        f"border-radius:{radius}px;}}"
    )
    return f


# ═══════════════════════════════════════════════════════════════════════════════
# TOP BAR
# ═══════════════════════════════════════════════════════════════════════════════
def build_top_bar(parent=None):
    bar = QWidget(parent)
    bar.setFixedHeight(58)
    bar.setStyleSheet(
        "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        "stop:0 rgba(2,18,38,252),stop:1 rgba(2,12,26,248));"
        "border-bottom:1px solid rgba(0,170,255,40);"
    )
    L = QHBoxLayout(bar); L.setContentsMargins(12,0,12,0); L.setSpacing(0)

    # Reactor icon
    reactor = ReactorIcon()
    L.addWidget(reactor); L.addSpacing(8)

    # Logo (fixed width so clock/buttons never overflow)
    logo_w = QWidget(); logo_w.setFixedWidth(200)
    logo_w.setStyleSheet("background:transparent;")
    logo_l = QVBoxLayout(logo_w)
    logo_l.setContentsMargins(0,10,0,10); logo_l.setSpacing(1)
    t = _lbl("🤖 J.A.R.V.I.S", "Segoe UI", 14, True, "#ffffff", 2)
    t.setStyleSheet("color:#ffffff;background:transparent;letter-spacing:2px;")
    logo_l.addWidget(t)
    logo_l.addWidget(_lbl("SOVEREIGN ORCHESTRATOR","Segoe UI",6,True,Theme.BLUE2,2))
    L.addWidget(logo_w)

    def _sep():
        s = QFrame(); s.setFixedSize(1,30)
        s.setStyleSheet("background:rgba(0,170,255,28);"); return s

    L.addWidget(_sep()); L.addSpacing(14)

    # Telemetry blocks
    tele = QHBoxLayout(); tele.setSpacing(8)
    cpu_b = TelemetryBlock("💻 CPU");        tele.addWidget(cpu_b)
    ram_b = TelemetryBlock("🧠 RAM");        tele.addWidget(ram_b)
    gpu_b = TelemetryBlock("🎮 GPU");        tele.addWidget(gpu_b)
    net_b = TelemetryBlock("🌐 NET"," TB/s"); tele.addWidget(net_b)
    L.addLayout(tele); L.addStretch(1)

    # Clock (fixed width so right-side controls always stay visible)
    clk_w = QWidget(); clk_w.setFixedWidth(160)
    clk_w.setStyleSheet("background:transparent;")
    clk_l = QVBoxLayout(clk_w)
    clk_l.setContentsMargins(0,8,0,8); clk_l.setSpacing(1)
    clk_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
    clock_lbl = _lbl("00:00:00","Consolas",17,True,"#ffffff",2)
    clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    clock_lbl.setStyleSheet("color:#ffffff;background:transparent;letter-spacing:2px;")
    date_lbl = _lbl("—","Segoe UI",7,False,Theme.BLUE2,1)
    date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    clk_l.addWidget(clock_lbl); clk_l.addWidget(date_lbl)
    L.addWidget(clk_w); L.addStretch(1)
    L.addWidget(_sep()); L.addSpacing(12)

    # Vibe Shield pill with dot
    vibe_w = QWidget()
    vibe_w.setFixedHeight(26)
    vibe_w.setStyleSheet(
        "background:rgba(0,230,118,10);"
        "border:1px solid rgba(0,230,118,45);"
        "border-radius:13px;"
    )
    vl = QHBoxLayout(vibe_w); vl.setContentsMargins(8,3,10,3); vl.setSpacing(5)
    vdot = QLabel("●"); vdot.setFont(QFont("Segoe UI",6))
    vdot.setStyleSheet(f"color:{Theme.GREEN};background:transparent;")
    vtxt = _lbl("🛡️ VIBE SHIELD ACTIVE","Segoe UI",7,True,Theme.GREEN,1)
    vl.addWidget(vdot); vl.addWidget(vtxt)
    L.addWidget(vibe_w); L.addSpacing(10)

    L.addWidget(_sep()); L.addSpacing(8)

    # Control buttons — large, clearly readable
    search_btn = grid_btn = power_btn = None
    BTN_DEFS = [("🔍 SEARCH", False), ("🔳 GRID", False), ("⚡ POWER", True)]
    for label, danger in BTN_DEFS:
        b = QPushButton(label)
        b.setFixedSize(85, 30)
        b.setToolTip({
            "🔍 SEARCH": "Focus the direct command input.",
            "🔳 GRID": "Return to the dashboard grid.",
            "⚡ POWER": "Request a controlled shutdown.",
        }.get(label, label))
        if danger:
            b.setStyleSheet(
                "QPushButton{background:rgba(255,40,40,18);"
                "border:1.5px solid rgba(255,60,60,200);"
                "border-radius:5px;color:#ff5555;"
                "font-size:11px;font-weight:900;}"
                "QPushButton:hover{background:rgba(255,40,40,50);"
                "border-color:#ff2222;color:#ffffff;}"
            )
            power_btn = b
        else:
            b.setStyleSheet(
                f"QPushButton{{background:rgba(0,150,255,14);"
                f"border:1.5px solid rgba(0,170,255,180);"
                f"border-radius:5px;color:{Theme.BLUE2};"
                f"font-size:11px;font-weight:900;}}"
                f"QPushButton:hover{{background:rgba(0,170,255,35);"
                f"border-color:#00d4ff;color:#ffffff;}}"
            )
            if "SEARCH" in label:
                search_btn = b
            elif "GRID" in label:
                grid_btn = b
        L.addWidget(b)
        L.addSpacing(5)

    return bar, clock_lbl, date_lbl, cpu_b, ram_b, gpu_b, net_b, search_btn, grid_btn, power_btn



# ═══════════════════════════════════════════════════════════════════════════════
# LEFT SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
def build_left_sidebar():
    pnl = QFrame()
    pnl.setFixedWidth(195)
    pnl.setStyleSheet(
        "QFrame{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        "stop:0 rgba(2,14,30,240),stop:1 rgba(2,10,22,245));"
        "border-right:1px solid rgba(0,170,255,25);}"
    )
    L = QVBoxLayout(pnl); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

    # Identity card
    card = QWidget(); card.setFixedHeight(110)
    card.setStyleSheet(
        "background:rgba(0,120,255,8);"
        "border-bottom:1px solid rgba(0,170,255,28);"
    )
    cl = QVBoxLayout(card); cl.setContentsMargins(14,14,14,12); cl.setSpacing(4)
    row1 = QHBoxLayout(); row1.setSpacing(8)
    hex_ico = QLabel("⬡")
    hex_ico.setFont(QFont("Segoe UI",22))
    hex_ico.setStyleSheet(f"color:{Theme.BLUE2};background:transparent;")
    row1.addWidget(hex_ico)
    id_col = QVBoxLayout(); id_col.setSpacing(1)
    id_col.addWidget(_lbl("J.A.R.V.I.S",bold=True,size=10,col="#ffffff",ls=2))
    id_col.addWidget(_lbl("SYSTEM STATUS",size=7,col=Theme.TEXT_SECONDARY,ls=1))
    row1.addLayout(id_col); row1.addStretch()
    cl.addLayout(row1)
    ok_row = QHBoxLayout(); ok_row.setSpacing(4)
    ok_dot = QLabel("●"); ok_dot.setFont(QFont("Segoe UI",6))
    ok_dot.setStyleSheet(f"color:{Theme.GREEN};background:transparent;")
    ok_row.addWidget(ok_dot)
    ok_lbl = _lbl("ALL SYSTEMS OPERATIONAL",bold=True,size=6,col=Theme.GREEN)
    ok_lbl.setWordWrap(False)
    ok_row.addWidget(ok_lbl); ok_row.addStretch()
    cl.addLayout(ok_row)
    L.addWidget(card)

    # Nav items
    NAV = [
        ("⊞","Dashboard",True),("⚙","Core Systems",False),
        ("⌖","Communications",False),("▤","Subsystems",False),
        ("⚡","Quick Actions",False),("◈","AI Modules",False),
        ("⛁","Data Vault",False),("≡","Activity Log",False),
        ("⛭","Settings",False),
    ]
    nav_refs = {}
    for ico, txt, active in NAV:
        btn = NavButton(ico, txt, active)
        L.addWidget(btn); nav_refs[txt] = btn
    L.addStretch(1)

    # Protocol card
    proto = QWidget(); proto.setFixedHeight(98)
    proto.setStyleSheet(
        "background:rgba(0,100,200,7);"
        "border-top:1px solid rgba(0,170,255,22);"
    )
    pl = QVBoxLayout(proto); pl.setContentsMargins(14,10,14,10); pl.setSpacing(3)
    r1 = QHBoxLayout(); r1.setSpacing(5)
    r1.addWidget(_lbl("●",size=6,col=Theme.GREEN))
    r1.addWidget(_lbl("SOVEREIGN PROTOCOL",bold=True,size=7,col=Theme.BLUE2))
    r1.addStretch()
    pl.addLayout(r1)
    pl.addWidget(_lbl("ACTIVE",bold=True,size=7,col=Theme.GREEN))
    # Wireframe cube (text approximation)
    cube = _lbl("⬡  ⬡\n ⬡  ⬡",size=9,col=f"rgba(0,170,255,120)")
    cube.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pl.addWidget(cube)
    pl.addWidget(_lbl("BUILD 7.5.1",size=6,col=Theme.TEXT_MUTED))
    L.addWidget(proto)

    # Neural engine strip
    ne = QWidget(); ne.setFixedHeight(26)
    ne.setStyleSheet("background:rgba(2,6,14,230);border-top:1px solid rgba(255,255,255,6);")
    nel = QHBoxLayout(ne); nel.setContentsMargins(12,0,12,0); nel.setSpacing(5)
    dot = QLabel("●"); dot.setFont(QFont("Segoe UI",5))
    dot.setStyleSheet(f"color:{Theme.BLUE2};background:transparent;")
    nel.addWidget(dot)
    nel.addWidget(_lbl("NEURAL ENGINE · IDLE",bold=True,size=7,col=Theme.TEXT_SECONDARY,ls=1))
    nel.addStretch()
    L.addWidget(ne)

    return pnl, nav_refs


# ═══════════════════════════════════════════════════════════════════════════════
# CENTER OVERLAYS (DASHBOARD)
# ═══════════════════════════════════════════════════════════════════════════════
def build_dashboard_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

    # JARVIS ONLINE strip
    strip = QWidget(); strip.setFixedHeight(46)
    strip.setStyleSheet(
        "background:rgba(2,10,24,175);"
        "border-bottom:1px solid rgba(0,170,255,28);"
    )
    sl = QHBoxLayout(strip); sl.setContentsMargins(14,0,14,0); sl.setSpacing(10)
    dot = QLabel("●"); dot.setFont(QFont("Segoe UI",7))
    dot.setStyleSheet(f"color:{Theme.BLUE2};background:transparent;")
    sl.addWidget(dot)
    scol = QVBoxLayout(); scol.setSpacing(1)
    t1 = _lbl("JARVIS ONLINE",bold=True,size=10,col="#ffffff",ls=3)
    t1.setStyleSheet("color:#ffffff;background:transparent;letter-spacing:3px;")
    scol.addWidget(t1)
    scol.addWidget(_lbl("SOVEREIGN CORE ORCHESTRATOR",size=7,col=Theme.TEXT_SECONDARY,ls=2))
    sl.addLayout(scol); sl.addSpacing(12)
    waveform_top = WaveformWidget(Theme.ELECTRIC_BLUE, 34)
    sl.addWidget(waveform_top, 1)
    L.addWidget(strip)

    # Middle body — left floating column + reactor spacer
    body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)

    left_w = QWidget(); left_w.setFixedWidth(210)
    left_w.setStyleSheet("background:transparent;")
    lc = QVBoxLayout(left_w); lc.setContentsMargins(7,7,4,7); lc.setSpacing(6)

    # System Monitor card
    sm = _card(); sm_l = QVBoxLayout(sm); sm_l.setContentsMargins(0,0,0,4); sm_l.setSpacing(0)
    sm_l.addWidget(section_header("◈","SYSTEM MONITOR"))
    r1 = QHBoxLayout(); r1.setSpacing(1)
    rc_cpu = RingChart("CPU", Theme.CYAN,   "CPU");  rc_cpu.setFixedSize(99,98)
    rc_ram = RingChart("RAM", Theme.GOLD,   "RAM");  rc_ram.setFixedSize(99,98)
    r1.addWidget(rc_cpu); r1.addWidget(rc_ram); sm_l.addLayout(r1)
    r2 = QHBoxLayout(); r2.setSpacing(1)
    rc_gpu  = RingChart("GPU",  Theme.GREEN,  "GPU");  rc_gpu.setFixedSize(99,98)
    rc_disk = RingChart("DISK", Theme.PURPLE, "DISK"); rc_disk.setFixedSize(99,98)
    rc_disk.set_value(47)
    r2.addWidget(rc_gpu); r2.addWidget(rc_disk); sm_l.addLayout(r2)
    lc.addWidget(sm)

    # Subsystems card
    ss = _card(); ss_l = QVBoxLayout(ss); ss_l.setContentsMargins(0,0,0,4); ss_l.setSpacing(0)
    ss_l.addWidget(section_header("▤","SUBSYSTEMS"))
    dot_ollama = StatusPill("OLLAMA",       "⚙",True)
    dot_voice  = StatusPill("VOICE ENGINE", "♪",True)
    dot_vision = StatusPill("VISION ENGINE","◎",True)
    dot_docker = StatusPill("DOCKER",       "⊞",False)
    for pill in (dot_ollama, dot_voice, dot_vision, dot_docker):
        ss_l.addWidget(pill)
    lc.addWidget(ss)

    # NEW: Workspace Health Card
    wh = _card(); wh_l = QVBoxLayout(wh); wh_l.setContentsMargins(0,0,0,6); wh_l.setSpacing(1)
    wh_l.addWidget(section_header("📁","WORKSPACE HEALTH"))
    ws_proj_lbl = _lbl("Projects: 0", size=7, col=Theme.TEXT_SECONDARY)
    ws_size_lbl = _lbl("Size: 0.0 MB", size=7, col=Theme.TEXT_SECONDARY)
    ws_path_lbl = _lbl("Path: C:/Users/Pavan...", size=6, col=Theme.TEXT_MUTED)
    for l in (ws_proj_lbl, ws_size_lbl, ws_path_lbl):
        l.setContentsMargins(12, 2, 12, 2)
        wh_l.addWidget(l)
    lc.addWidget(wh)

    # NEW: VRAM Orchestrator Card
    vram_c = _card(); vram_l = QVBoxLayout(vram_c); vram_l.setContentsMargins(0,0,0,6); vram_l.setSpacing(1)
    vram_l.addWidget(section_header("🧠","VRAM ORCHESTRATOR"))
    vram_model_lbl = _lbl("Hot: None", bold=True, size=7, col=Theme.CYAN)
    vram_pinned_lbl = _lbl("Pinned: None", size=7, col=Theme.AMBER)
    for l in (vram_model_lbl, vram_pinned_lbl):
        l.setContentsMargins(12, 2, 12, 2)
        vram_l.addWidget(l)
    lc.addWidget(vram_c)
    
    lc.addStretch()

    body.addWidget(left_w)
    body.addStretch(1)
    L.addLayout(body, 1)

    # Quick Actions bar
    qa_bar = QWidget(); qa_bar.setFixedHeight(96)
    qa_bar.setStyleSheet(
        "background:rgba(2,8,20,195);"
        "border-top:1px solid rgba(0,170,255,28);"
    )
    ql = QVBoxLayout(qa_bar); ql.setContentsMargins(12,6,12,6); ql.setSpacing(5)
    qh = QHBoxLayout()
    qh.addWidget(_lbl("⚡",size=9,col=Theme.AMBER))
    qh.addWidget(_lbl("QUICK ACTIONS",bold=True,size=8,col=Theme.TEXT_PRIMARY,ls=2))
    qh.addStretch(); ql.addLayout(qh)
    qr = QHBoxLayout(); qr.setSpacing(6)
    ACTIONS = [
        ("⟨/⟩","CODE MODE","Activate",Theme.ELECTRIC_BLUE),
        ("📖","STUDY MODE","Activate",Theme.GOLD),
        ("🎮","GAMING MODE","Activate",Theme.AMBER),
        ("☾","NIGHT MODE","Activate",Theme.PURPLE),
        ("⚙","DIAGNOSTICS","Run Scan",Theme.GREEN),
        ("🧹","SYSTEM CLEANUP","Optimize",Theme.BLUE2),
    ]
    qa_btns = {}
    for ico, title, sub, acc in ACTIONS:
        btn = QuickActionBtn(ico, title, sub, acc)
        qr.addWidget(btn, 1); qa_btns[title] = btn
    ql.addLayout(qr)
    L.addWidget(qa_bar)

    return (w, waveform_top,
            rc_cpu, rc_ram, rc_gpu, rc_disk,
            dot_ollama, dot_voice, dot_vision, dot_docker,
            qa_btns, ws_proj_lbl, ws_size_lbl, ws_path_lbl,
            vram_model_lbl, vram_pinned_lbl)

def build_generic_view(title, icon, description):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,30,30,30); L.setSpacing(20)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl(icon, size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl(title.upper(), bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)
    
    L.addWidget(_lbl(description, size=10, col=Theme.TEXT_SECONDARY))
    
    content = _card()
    cl = QVBoxLayout(content); cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cl.addWidget(_lbl("MODULE ONLINE", bold=True, size=12, col=Theme.BLUE2, ls=2))
    cl.addWidget(_lbl(description, size=8, col=Theme.TEXT_MUTED))
    L.addWidget(content, 1)
    
    return w

def build_core_systems_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("⚙", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("CORE SYSTEMS", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)
    
    # Grid of charts
    grid_w = QWidget(); grid = QHBoxLayout(grid_w); grid.setSpacing(20)
    
    c1 = _card(); c1l = QVBoxLayout(c1); c1l.addWidget(section_header("◈","CPU PERFORMANCE"))
    rc_cpu = RingChart("CPU", Theme.CYAN, "CPU"); rc_cpu.setFixedSize(160,160)
    c1l.addWidget(rc_cpu, 0, Qt.AlignmentFlag.AlignCenter); c1l.addStretch()
    
    c2 = _card(); c2l = QVBoxLayout(c2); c2l.addWidget(section_header("◈","MEMORY ALLOCATION"))
    rc_ram = RingChart("RAM", Theme.GOLD, "RAM"); rc_ram.setFixedSize(160,160)
    c2l.addWidget(rc_ram, 0, Qt.AlignmentFlag.AlignCenter); c2l.addStretch()

    c3 = _card(); c3l = QVBoxLayout(c3); c3l.addWidget(section_header("◈","GPU UTILIZATION"))
    rc_gpu = RingChart("GPU", Theme.GREEN, "GPU"); rc_gpu.setFixedSize(160,160)
    c3l.addWidget(rc_gpu, 0, Qt.AlignmentFlag.AlignCenter); c3l.addStretch()
    
    grid.addWidget(c1); grid.addWidget(c2); grid.addWidget(c3)
    L.addWidget(grid_w, 1)
    
    details = _card(); dl = QVBoxLayout(details)
    dl.addWidget(section_header("≡", "SYSTEM PROCESSES"))
    try:
        import psutil
        procs = sorted(
            (
                p.info for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"])
                if p.info.get("name")
            ),
            key=lambda item: (item.get("cpu_percent") or 0) + (item.get("memory_percent") or 0),
            reverse=True,
        )[:6]
    except Exception:
        procs = [{"name": "Telemetry unavailable", "cpu_percent": 0}]
    for proc in procs:
        row = QHBoxLayout()
        name = str(proc.get("name", "process"))[:28]
        row.addWidget(_lbl(name, size=9, col=Theme.TEXT_PRIMARY))
        row.addStretch()
        row.addWidget(_lbl(f"{float(proc.get('cpu_percent') or 0):.1f}% CPU", size=8, col=Theme.CYAN))
        dl.addLayout(row)
    L.addWidget(details, 1)
    
    return w, rc_cpu, rc_ram, rc_gpu

def build_subsystems_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("▤", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("SUBSYSTEMS", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)

    # Subsystem list
    list_w = QWidget(); list_l = QVBoxLayout(list_w); list_l.setSpacing(10)
    SUBS = [
        ("OLLAMA SERVICE", "⚙", True),
        ("VOICE RECOGNITION", "♪", True),
        ("VISION ENGINE", "◎", True),
        ("DOCKER SANDBOX", "⊞", False),
        ("GESTURE CONTROL", "✋", True),
        ("M.C.P. BRIDGE", "◈", False),
        ("KOKORO TTS", "🗣", True),
    ]
    pills = {}
    for name, ico, state in SUBS:
        row = _card(); rl = QHBoxLayout(row)
        pill = StatusPill(name, ico, state)
        rl.addWidget(pill, 1)
        btn = QPushButton("RESTART")
        btn.setFixedSize(80, 24)
        btn.setToolTip(f"Run a soft restart check for {name}.")
        btn.clicked.connect(lambda checked=False, p=pill, b=btn: (p.set_online(True), b.setText("READY")))
        rl.addWidget(btn)
        list_l.addWidget(row)
        pills[name] = pill
    
    scr = QScrollArea(); scr.setWidgetResizable(True); scr.setWidget(list_w)
    L.addWidget(scr, 1)
    
    return w, pills

def build_communications_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("⌖", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("COMMUNICATIONS", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)
    
    chat_box = _card(); cl = QVBoxLayout(chat_box)
    cl.addWidget(section_header("◈", "NEURAL LINK HISTORY"))
    
    big_chat = QTextEdit(); big_chat.setReadOnly(True)
    big_chat.setStyleSheet(
        f"QTextEdit{{background:rgba(2,12,28,180); border:none;"
        f"color:{Theme.TEXT_PRIMARY}; font-size:11px; padding:15px;}}"
    )
    cl.addWidget(big_chat, 1)
    
    L.addWidget(chat_box, 1)
    
    return w, big_chat

def build_quick_actions_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("⚡", size=24, col=Theme.AMBER))
    hdr.addWidget(_lbl("QUICK ACTIONS", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)

    grid_w = QWidget(); grid = QVBoxLayout(grid_w); grid.setSpacing(12)
    ACTIONS = [
        ("⟨/⟩","CODE MODE","Initialize secure development environment", Theme.ELECTRIC_BLUE),
        ("📖","STUDY MODE","Optimize cognitive load for learning", Theme.GOLD),
        ("🎮","GAMING MODE","Allocate maximum VRAM to primary display", Theme.AMBER),
        ("☾","NIGHT MODE","Dim interface and quiet noncritical alerts", Theme.PURPLE),
        ("⚙","DIAGNOSTICS","Run comprehensive hardware audit", Theme.GREEN),
        ("🧹","SYSTEM CLEANUP","Purge temporary buffers and optimize DB", Theme.BLUE2),
    ]
    btns = {}
    for ico, title, desc, acc in ACTIONS:
        b = QuickActionBtn(ico, title, desc, acc)
        b.setFixedHeight(80)
        grid.addWidget(b)
        btns[title] = b
        
    scr = QScrollArea(); scr.setWidgetResizable(True); scr.setWidget(grid_w)
    L.addWidget(scr, 1)
    
    return w, btns

def build_ai_modules_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("◈", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("AI MODULES", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)
    
    # Module Grid
    grid_w = QWidget(); grid = QHBoxLayout(grid_w); grid.setSpacing(20)
    
    try:
        from core.providers.model_router import get_router
        routed_code = get_router().route("write a python tool")
        routed_chat = get_router().route("hello jarvis")
    except Exception:
        routed_code = "qwen2.5-coder:7b"
        routed_chat = "llama3.2"

    # LLM Core
    m1 = _card(); m1l = QVBoxLayout(m1); m1l.addWidget(section_header("⚙", "LLM CORE"))
    m1l.addWidget(_lbl(f"CODE: {routed_code}", bold=True, size=9, col=Theme.CYAN))
    m1l.addWidget(_lbl(f"CHAT: {routed_chat}", size=7, col=Theme.TEXT_SECONDARY))
    m1l.addStretch()
    m1l.addWidget(_lbl("ROUTER: active", size=7, col=Theme.TEXT_MUTED))
    grid.addWidget(m1)

    # Voice Engine
    m2 = _card(); m2l = QVBoxLayout(m2); m2l.addWidget(section_header("♪", "VOICE ENGINE"))
    m2l.addWidget(_lbl("TTS: Kokoro / pyttsx3 fallback", bold=True, size=9, col=Theme.GOLD))
    m2l.addWidget(_lbl("STT: compatibility listener online", size=7, col=Theme.TEXT_SECONDARY))
    m2l.addStretch()
    m2l.addWidget(_lbl("LATENCY: 120ms (Local)", size=7, col=Theme.TEXT_MUTED))
    grid.addWidget(m2)

    # Vision Core
    m3 = _card(); m3l = QVBoxLayout(m3); m3l.addWidget(section_header("◎", "VISION CORE"))
    m3l.addWidget(_lbl("SCREEN: screenshot + OCR/VLM", bold=True, size=9, col=Theme.GREEN))
    m3l.addWidget(_lbl("CAMERA: managed single-frame capture", size=7, col=Theme.TEXT_SECONDARY))
    m3l.addStretch()
    m3l.addWidget(_lbl("FPS: 30 (Stabilized)", size=7, col=Theme.TEXT_MUTED))
    grid.addWidget(m3)

    L.addWidget(grid_w, 0)

    # cognitive params
    params = _card(); pl = QVBoxLayout(params)
    pl.addWidget(section_header("⚡", "COGNITIVE PARAMETERS"))
    import random
    for p, v in [("Temperature", "0.72"), ("Top-P", "0.90"), ("Repetition Penalty", "1.15"), ("Max Tokens", "4096")]:
        row = QHBoxLayout(); row.addWidget(_lbl(p, size=9, col=Theme.TEXT_PRIMARY))
        row.addStretch(); row.addWidget(_lbl(v, size=9, col=Theme.BLUE2))
        pl.addLayout(row)
    L.addWidget(params, 1)
    
    return w

def build_data_vault_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("⛁", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("DATA VAULT", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)
    
    def _db_count(path: str, table: str) -> int:
        try:
            if not os.path.exists(path):
                return 0
            with sqlite3.connect(path) as conn:
                return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except Exception:
            return 0

    state_db = "memory/jarvis_state.db"
    auth_db = "jarvis_auth.db"
    state_size = os.path.getsize(state_db) / (1024 * 1024) if os.path.exists(state_db) else 0
    auth_size = os.path.getsize(auth_db) / (1024 * 1024) if os.path.exists(auth_db) else 0
    conversation_count = _db_count(state_db, "conversation_history")
    telemetry_count = _db_count(state_db, "telemetry")
    memory_files = []
    if os.path.isdir("memory"):
        memory_files = sorted(os.listdir("memory"))[:8]

    # Top Row: Stats
    stats_w = QWidget(); sl = QHBoxLayout(stats_w); sl.setSpacing(15)
    
    # Vector DB
    vdb = _card(); vdbl = QVBoxLayout(vdb); vdbl.addWidget(section_header("◈", "VECTOR DB (CHROMA)"))
    vdbl.addWidget(_lbl(f"CONVERSATIONS: {conversation_count}", bold=True, size=9, col=Theme.CYAN))
    vdbl.addWidget(_lbl(f"TELEMETRY EVENTS: {telemetry_count}", size=7, col=Theme.TEXT_SECONDARY))
    vdbl.addStretch(); sl.addWidget(vdb)

    # SQL DB
    sdb = _card(); sdbl = QVBoxLayout(sdb); sdbl.addWidget(section_header("◈", "SYSTEM SQL"))
    sdbl.addWidget(_lbl("DB: jarvis_state.db", bold=True, size=9, col=Theme.GOLD))
    sdbl.addWidget(_lbl(f"STATE: {state_size:.2f} MB | AUTH: {auth_size:.2f} MB", size=7, col=Theme.TEXT_SECONDARY))
    sdbl.addStretch(); sl.addWidget(sdb)

    L.addWidget(stats_w, 0)

    # Episodic Memory List
    mem = _card(); ml = QVBoxLayout(mem)
    ml.addWidget(section_header("≡", "MEMORY ARTIFACTS"))
    if not memory_files:
        memory_files = ["No memory files found"]
    for item in memory_files:
        row = QHBoxLayout()
        path = os.path.join("memory", item)
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        row.addWidget(_lbl(item[:32], size=8, col=Theme.TEXT_PRIMARY))
        row.addStretch()
        row.addWidget(_lbl(f"{size / 1024:.1f} KB", size=7, col=Theme.TEXT_MUTED))
        ml.addLayout(row)
    L.addWidget(mem, 1)
    
    return w

def build_activity_log_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)
    
    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("≡", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("ACTIVITY LOG", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    clear_btn = QPushButton("CLEAR LOG")
    clear_btn.setFixedSize(100, 30)
    hdr.addWidget(clear_btn)
    L.addLayout(hdr)
    
    log_view = QTextEdit()
    log_view.setReadOnly(True)
    log_view.setStyleSheet(
        f"QTextEdit{{background:rgba(0,6,16,220); border:1px solid {Theme.BORDER_GLOW};"
        f"color:{Theme.CYAN}; font-family:'Cascadia Code',monospace; font-size:10px; padding:15px;}}"
    )
    clear_btn.clicked.connect(log_view.clear)
    L.addWidget(log_view, 1)
    
    return w, log_view

def build_settings_view():
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    L = QVBoxLayout(w); L.setContentsMargins(30,20,30,20); L.setSpacing(15)

    hdr = QHBoxLayout(); hdr.setSpacing(15)
    hdr.addWidget(_lbl("⛭", size=24, col=Theme.BLUE2))
    hdr.addWidget(_lbl("SETTINGS", bold=True, size=18, col="#ffffff", ls=4))
    hdr.addStretch()
    L.addLayout(hdr)

    # Load persisted settings from SystemDB
    try:
        from core.system.db import get_db
        db = get_db()
    except Exception:
        db = None

    scr_w = QWidget(); sl = QVBoxLayout(scr_w); sl.setSpacing(15)

    def _load_setting(key: str, default: bool = True) -> bool:
        if db is None: return default
        try:
            v = db.get_setting(f"ui_{key}", str(default).lower())
            return v == "true"
        except Exception:
            return default

    def _toggle_button(key: str, label: str = "ENABLED", default: bool = True) -> QPushButton:
        initial = _load_setting(key, default)
        btn = QPushButton("ENABLED" if initial else "DISABLED")
        btn.setCheckable(True)
        btn.setChecked(initial)
        btn.setFixedSize(80, 22)
        btn.setStyleSheet(
            f"QPushButton{{color:{Theme.GREEN};background:rgba(0,230,118,14);"
            f"border:1px solid rgba(0,230,118,45);border-radius:4px;font-size:7px;font-weight:bold;}}"
            f"QPushButton:!checked{{color:{Theme.TEXT_MUTED};background:rgba(255,255,255,8);"
            f"border:1px solid rgba(255,255,255,18);}}"
        )
        def _save(checked: bool, k=key, b=btn):
            b.setText("ENABLED" if checked else "DISABLED")
            if db:
                try: db.set_setting(f"ui_{k}", str(checked).lower())
                except Exception: pass
        btn.toggled.connect(_save)
        return btn

    # Interface settings
    ui = _card(); uil = QVBoxLayout(ui); uil.addWidget(section_header("◈", "INTERFACE CONFIGURATION"))
    INTERFACE_KEYS = ["hud_dynamic_scaling", "neural_feed_verbosity", "glass_blur", "animations"]
    INTERFACE_LABELS = ["HUD Dynamic Scaling", "Neural Feed Verbosity", "Glass Background Blur", "Animations (60 FPS)"]
    for key, label in zip(INTERFACE_KEYS, INTERFACE_LABELS):
        row = QHBoxLayout(); row.addWidget(_lbl(label, size=9, col=Theme.TEXT_PRIMARY))
        row.addStretch(); row.addWidget(_toggle_button(key))
        uil.addLayout(row)
    sl.addWidget(ui)

    # Security settings
    sec = _card(); secl = QVBoxLayout(sec); secl.addWidget(section_header("◈", "SECURITY & PRIVACY"))
    SEC_KEYS = ["link_encryption", "biometric_auth", "local_only", "vibe_shield"]
    SEC_LABELS = ["Sovereign Link Encryption", "Biometric Authentication", "Local-Only Inference", "Vibe Shield Aggression"]
    for key, label in zip(SEC_KEYS, SEC_LABELS):
        row = QHBoxLayout(); row.addWidget(_lbl(label, size=9, col=Theme.TEXT_PRIMARY))
        row.addStretch(); row.addWidget(_toggle_button(key, "ACTIVE", default=False))
        secl.addLayout(row)
    sl.addWidget(sec)

    # Context Intelligence settings
    ctx = _card(); ctxl = QVBoxLayout(ctx)
    ctxl.addWidget(section_header("◈", "CONTEXT INTELLIGENCE"))
    ctx_lbl = _lbl("Privacy controls for workspace awareness and suggestions.", size=8, col=Theme.TEXT_MUTED)
    ctxl.addWidget(ctx_lbl)

    try:
        from core.context.privacy import get_privacy_controls
        pc = get_privacy_controls()
    except Exception:
        pc = None

    CTX_KEYS = ["workspace_tracking", "workflow_detection", "suggestions", "idle_detection"]
    CTX_LABELS = ["Active Window Tracking", "Workflow Detection", "Proactive Suggestions", "Idle Detection"]
    for key, label in zip(CTX_KEYS, CTX_LABELS):
        enabled = pc.is_feature_enabled(key) if pc else True
        row = QHBoxLayout()
        row.addWidget(_lbl(label, size=9, col=Theme.TEXT_PRIMARY))
        row.addStretch()
        btn = QPushButton("ON" if enabled else "OFF")
        btn.setCheckable(True); btn.setChecked(enabled)
        btn.setFixedSize(50, 22)

        def _make_style(on):
            gc = Theme.GREEN if on else Theme.TEXT_MUTED
            bg = "rgba(0,230,118,14)" if on else "rgba(255,255,255,8)"
            bd = "rgba(0,230,118,45)" if on else "rgba(255,255,255,18)"
            return (
                f"QPushButton{{color:{gc};background:{bg};"
                f"border:1px solid {bd};border-radius:4px;font-size:7px;font-weight:bold;}}"
                f"QPushButton:!checked{{color:{Theme.TEXT_MUTED};background:rgba(255,255,255,8);"
                f"border:1px solid rgba(255,255,255,18);}}"
            )

        btn.setStyleSheet(_make_style(enabled))

        def _toggle_ctx(checked: bool, k=key, b=btn):
            b.setText("ON" if checked else "OFF")
            b.setStyleSheet(_make_style(checked))
            if pc:
                try: pc.set_feature(k, checked)
                except Exception: pass
        btn.toggled.connect(_toggle_ctx)
        row.addWidget(btn)
        ctxl.addLayout(row)

    # Global pause toggle
    p_row = QHBoxLayout()
    p_row.addWidget(_lbl("Global Privacy Pause", bold=True, size=9, col=Theme.TEXT_PRIMARY))
    p_row.addStretch()
    p_btn = QPushButton("RESUME")
    p_btn.setFixedSize(70, 22)
    def _toggle_pause():
        if pc:
            new_state = pc.toggle()
            p_btn.setText("PAUSE" if not new_state else "RESUME")
    p_btn.clicked.connect(_toggle_pause)
    p_row.addWidget(p_btn)
    ctxl.addLayout(p_row)
    sl.addWidget(ctx)

    scr = QScrollArea(); scr.setWidgetResizable(True); scr.setWidget(scr_w)
    L.addWidget(scr, 1)
    
    return w


# ═══════════════════════════════════════════════════════════════════════════════
# BOTTOM DOCK
# ═══════════════════════════════════════════════════════════════════════════════
def build_bottom_dock():
    dock = QWidget(); dock.setFixedHeight(52)
    dock.setStyleSheet(
        "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        "stop:0 rgba(2,10,26,240),stop:1 rgba(2,8,20,250));"
        "border-top:1px solid rgba(0,170,255,25);"
    )
    dl = QHBoxLayout(dock); dl.setContentsMargins(0,0,0,0)
    dl.setAlignment(Qt.AlignmentFlag.AlignCenter); dl.setSpacing(8)
    buttons = {}
    tips = {
        "shield": "Open security and privacy settings.",
        "terminal": "Open the full activity log.",
        "core": "Return to the main dashboard.",
        "vault": "Open memory and database status.",
        "ai": "Open model and AI module status.",
        "files": "Open quick actions.",
        "comms": "Open communications history.",
    }
    for key, ico in [("shield", "⛨"), ("terminal", "⎔")]:
        btn = DockButton(ico)
        btn.setToolTip(tips[key])
        buttons[key] = btn
        dl.addWidget(btn)
    core_btn = DockButton("◎", core=True)
    core_btn.setToolTip(tips["core"])
    buttons["core"] = core_btn
    dl.addWidget(core_btn)
    for key, ico in [("vault", "⛁"), ("ai", "🌐"), ("files", "📁"), ("comms", "⌖")]:
        btn = DockButton(ico)
        btn.setToolTip(tips[key])
        buttons[key] = btn
        dl.addWidget(btn)
    return dock, core_btn, buttons


# ═══════════════════════════════════════════════════════════════════════════════
# RIGHT SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
def build_right_sidebar():
    pnl = QFrame(); pnl.setFixedWidth(272)
    pnl.setStyleSheet(
        "QFrame{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
        "stop:0 rgba(2,14,30,240),stop:1 rgba(2,10,22,245));"
        "border-left:1px solid rgba(0,170,255,25);}"
    )
    L = QVBoxLayout(pnl); L.setContentsMargins(0,0,0,0); L.setSpacing(0)

    # Communications header
    comm_hdr = QWidget(); comm_hdr.setFixedHeight(34)
    comm_hdr.setStyleSheet(
        "background:rgba(0,120,255,9);"
        "border-bottom:1px solid rgba(0,170,255,28);"
    )
    ch = QHBoxLayout(comm_hdr); ch.setContentsMargins(10,0,10,0); ch.setSpacing(6)
    ch.addWidget(_lbl("◈",size=9,col=Theme.BLUE2))
    ch.addWidget(_lbl("COMMUNICATIONS",bold=True,size=8,col=Theme.TEXT_PRIMARY,ls=2))
    ch.addStretch()
    badge = QLabel("+4 NEW")
    badge.setStyleSheet(
        f"color:{Theme.GREEN};background:rgba(0,230,118,12);"
        f"border:1px solid rgba(0,230,118,40);border-radius:7px;"
        f"padding:0 5px;font-size:7px;font-weight:bold;"
    )
    ch.addWidget(badge)
    L.addWidget(comm_hdr)

    # Chat scroll
    chat_w = QWidget(); chat_w.setStyleSheet("background:transparent;")
    chat_lay = QVBoxLayout(chat_w)
    chat_lay.setContentsMargins(0,0,0,0); chat_lay.setSpacing(0)
    chat_lay.addStretch()
    scr = QScrollArea(); scr.setWidgetResizable(True)
    scr.setWidget(chat_w); scr.setFixedHeight(124)
    scr.setStyleSheet("QScrollArea{background:rgba(2,8,18,120);border:none;}")
    L.addWidget(scr)

    # Voice Interface
    L.addWidget(section_header("♪","VOICE INTERFACE",Theme.BLUE2))
    voice_w = QWidget(); voice_w.setFixedHeight(70)
    voice_w.setStyleSheet("background:rgba(2,10,24,140);")
    vl = QHBoxLayout(voice_w); vl.setContentsMargins(10,6,10,6); vl.setSpacing(10)
    mic_btn = QPushButton("🎙"); mic_btn.setFixedSize(50,50)
    mic_btn.setStyleSheet(
        f"QPushButton{{background:rgba(0,150,255,22);"
        f"border:2px solid rgba(0,170,255,55);"
        f"border-radius:25px;color:{Theme.TEXT_PRIMARY};font-size:19px;}}"
        f"QPushButton:hover{{background:rgba(0,170,255,40);"
        f"border-color:{Theme.BLUE2};}}"
    )
    vl.addWidget(mic_btn)
    vc = QVBoxLayout(); vc.setSpacing(2)
    wv = WaveformWidget(Theme.ELECTRIC_BLUE, 24)
    vc.addWidget(wv)
    vc.addWidget(_lbl("Listening...",bold=True,size=8,col=Theme.BLUE2))
    vc.addWidget(_lbl("Tap to speak",size=7,col=Theme.TEXT_SECONDARY))
    vl.addLayout(vc,1)
    L.addWidget(voice_w)

    # Context Awareness Strip
    ctx_w = QWidget(); ctx_w.setFixedHeight(46)
    ctx_w.setStyleSheet(
        "background:rgba(0,100,180,8);"
        "border-top:1px solid rgba(0,170,255,14);"
        "border-bottom:1px solid rgba(0,170,255,14);"
    )
    ctx_l = QHBoxLayout(ctx_w); ctx_l.setContentsMargins(10,4,10,4); ctx_l.setSpacing(8)

    ctx_ico = _lbl("◈",size=10,col=Theme.ELECTRIC_BLUE)
    ctx_lbl = _lbl("idle",size=8,col=Theme.TEXT_SECONDARY)
    ctx_wf_lbl = _lbl("",size=7,col=Theme.TEXT_MUTED)
    ctx_l.addWidget(ctx_ico); ctx_l.addWidget(ctx_lbl); ctx_l.addWidget(ctx_wf_lbl)
    ctx_l.addStretch()

    # Focus indicator dot
    focus_dot = QLabel("●"); focus_dot.setFont(QFont("Segoe UI",7))
    focus_dot.setStyleSheet(f"color:{Theme.GREEN};background:transparent;")
    focus_lbl = _lbl("active",size=7,col=Theme.GREEN)
    ctx_l.addWidget(focus_dot); ctx_l.addWidget(focus_lbl)

    L.addWidget(ctx_w)

    # Core Directives
    L.addWidget(section_header("◈","CORE DIRECTIVES",Theme.BLUE2))
    for txt in ["Ensure System Integrity","Optimize Performance",
                "Secure All Protocols","Assist & Automate"]:
        row = QWidget(); row.setFixedHeight(28)
        row.setStyleSheet(
            "background:rgba(0,120,255,4);"
            "border-bottom:1px solid rgba(0,170,255,12);"
        )
        rl = QHBoxLayout(row); rl.setContentsMargins(12,0,12,0)
        rl.addWidget(_lbl(txt,size=8,col=Theme.TEXT_PRIMARY))
        rl.addStretch()
        pill = QLabel("  ACTIVE  "); pill.setFont(QFont("Segoe UI",6,QFont.Weight.Bold))
        pill.setStyleSheet(
            f"color:{Theme.GREEN};background:rgba(0,230,118,12);"
            f"border:1px solid rgba(0,230,118,38);border-radius:8px;"
            f"letter-spacing:1px;"
        )
        rl.addWidget(pill)
        L.addWidget(row)

    # Neural Feed
    L.addWidget(section_header("⚡","NEURAL FEED",Theme.AMBER))
    term = QTextEdit(); term.setReadOnly(True)
    term.setStyleSheet(
        f"QTextEdit{{background:rgba(0,6,16,220);border:none;"
        f"color:{Theme.CYAN};"
        f"font-family:'Cascadia Code','Consolas',monospace;"
        f"font-size:9px;padding:8px;}}"
    )
    L.addWidget(term,1)

    # Command input
    inp_w = QWidget(); inp_w.setFixedHeight(44)
    inp_w.setStyleSheet(
        "background:rgba(2,8,20,230);"
        "border-top:1px solid rgba(0,170,255,22);"
    )
    il = QHBoxLayout(inp_w); il.setContentsMargins(8,5,8,5); il.setSpacing(6)
    cmd = QLineEdit(); cmd.setPlaceholderText("Direct command input...")
    cmd.setFixedHeight(34)
    send = QPushButton("SEND"); send.setFixedSize(52,34)
    send.setStyleSheet(
        f"QPushButton{{background:{Theme.ELECTRIC_BLUE};"
        f"border:none;border-radius:3px;"
        f"color:#020c17;font-weight:900;font-size:9px;letter-spacing:1.5px;}}"
        f"QPushButton:hover{{background:{Theme.BLUE2};}}"
    )
    il.addWidget(cmd,1); il.addWidget(send)
    L.addWidget(inp_w)

    return pnl, chat_lay, scr, term, cmd, send, mic_btn, wv, ctx_lbl, ctx_wf_lbl, focus_lbl


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS BAR
# ═══════════════════════════════════════════════════════════════════════════════
def build_status_bar():
    bar = QWidget(); bar.setFixedHeight(26)
    bar.setStyleSheet(
        "background:rgba(2,6,16,238);"
        "border-top:1px solid rgba(0,170,255,18);"
    )
    bl = QHBoxLayout(bar); bl.setContentsMargins(18,0,18,0); bl.setSpacing(8)
    uptime = _lbl("UPTIME: 00:00:00","Consolas",7,col=Theme.TEXT_SECONDARY)
    bl.addWidget(uptime)
    for col in [Theme.BLUE2, Theme.GREEN]:
        d = QLabel("●"); d.setFont(QFont("Segoe UI",5))
        d.setStyleSheet(f"color:{col};background:transparent;")
        bl.addWidget(d)
    bl.addStretch()
    bl.addWidget(_lbl("●",size=6,col=Theme.GREEN))
    bl.addWidget(_lbl("SECURE CHANNEL",bold=True,size=7,col=Theme.GREEN))
    return bar, uptime
