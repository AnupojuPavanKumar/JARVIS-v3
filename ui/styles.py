# -*- coding: utf-8 -*-
from PyQt6.QtGui import QColor

class Theme:
    # ── Backgrounds ───────────────────────────────────────────────────
    BG          = "#020c17"
    PANEL       = "rgba(3,15,30,200)"
    PANEL_LIGHT = "rgba(5,20,40,170)"
    DIM         = "#010509"
    GLASS       = "rgba(0,150,255,8)"

    # ── Border glows ──────────────────────────────────────────────────
    BORDER_GLOW  = "rgba(0,170,255,22)"
    BORDER_BLUE  = "rgba(0,170,255,35)"
    BORDER_LIGHT = "rgba(255,255,255,8)"
    BORDER_AMBER = "rgba(255,107,26,20)"

    # ── Core accents ──────────────────────────────────────────────────
    ELECTRIC_BLUE = "#00aaff"
    BLUE2         = "#00d4ff"
    CYAN          = "#00d4ff"
    AMBER         = "#ff6b1a"
    ORANGE        = "#ffaa44"
    GOLD          = "#ffd740"
    PURPLE        = "#b44aff"
    RED           = "#ff3d3d"
    GREEN         = "#00e676"
    TEAL          = "#00bfa5"
    BLUE          = "#0077dd"
    YELLOW        = "#ffd740"

    # ── Text ─────────────────────────────────────────────────────────
    TEXT_PRIMARY   = "#c8e8ff"
    TEXT_SECONDARY = "rgba(160,210,255,140)"
    TEXT_MUTED     = "rgba(100,160,210,100)"
    TEXT_AMBER     = "#ffcc88"

    # ── Aliases ───────────────────────────────────────────────────────
    TEXT      = TEXT_PRIMARY
    MUTED     = TEXT_SECONDARY
    BLUE2     = "#00d4ff"       # bright cyan-blue (same as CYAN)
    TEXT_MUTED = "rgba(100,160,210,100)"  # very dim blue-grey

    # ── State colors ──────────────────────────────────────────────────
    STATE_COLORS = {
        "idle":      "#334455",
        "listening": "#00aaff",
        "thinking":  "#b44aff",
        "speaking":  "#ff6b1a",
        "danger":    "#ff3d3d",
        "boot":      "#ffd740",
        "success":   "#00e676",
    }


def get_color(c: str) -> QColor:
    if c.startswith("rgba"):
        parts = c.replace("rgba(", "").replace(")", "").split(",")
        return QColor(int(parts[0].strip()), int(parts[1].strip()),
                      int(parts[2].strip()), int(float(parts[3].strip())))
    return QColor(c)


STYLE_SHEET = f"""
QWidget {{
    background: transparent;
    color: {Theme.TEXT_PRIMARY};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 11px;
}}
QLabel {{ background: transparent; }}

/* ── Scrollbars ──────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent; width: 3px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,170,255,55); min-height: 24px; border-radius: 1px;
}}
QScrollBar::handle:vertical:hover {{ background: {Theme.ELECTRIC_BLUE}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollArea {{ border: none; background: transparent; }}

/* ── Terminal / Neural Feed ──────────────────────────────────── */
QTextEdit {{
    background: rgba(0,8,18,215);
    border: 1px solid rgba(0,150,255,18);
    color: {Theme.CYAN};
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 9px;
    padding: 8px;
    border-radius: 0px;
}}

/* ── Command input ───────────────────────────────────────────── */
QLineEdit {{
    background: rgba(0,150,255,8);
    border: 1px solid rgba(0,170,255,30);
    color: {Theme.TEXT_PRIMARY};
    font-size: 11px;
    padding: 7px 12px;
    border-radius: 3px;
}}
QLineEdit:focus {{
    border: 1px solid {Theme.ELECTRIC_BLUE};
    background: rgba(0,170,255,14);
}}
QLineEdit::placeholder {{
    color: {Theme.TEXT_MUTED};
}}

/* ── Buttons ─────────────────────────────────────────────────── */
QPushButton {{
    background: rgba(0,170,255,10);
    border: 1px solid rgba(0,170,255,38);
    color: {Theme.ELECTRIC_BLUE};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 5px 12px;
    border-radius: 3px;
}}
QPushButton:hover {{
    background: rgba(0,170,255,24);
    border-color: {Theme.ELECTRIC_BLUE};
    color: #ffffff;
}}
QPushButton:pressed {{
    background: rgba(0,170,255,42);
}}
"""
