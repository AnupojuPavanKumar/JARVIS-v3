from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication

from ui.main_ui import JarvisUI


def main() -> int:
    app = QApplication.instance() or QApplication([])
    ui = JarvisUI()

    names = [
        "Dashboard",
        "Core Systems",
        "Communications",
        "Subsystems",
        "Quick Actions",
        "AI Modules",
        "Data Vault",
        "Activity Log",
        "Settings",
    ]
    for idx, name in enumerate(names):
        ui._switch_view(idx, name)

    ui._focus_command_search()
    assert ui._stack.currentIndex() == 2

    for command in ui._get_qa_cmds().values():
        ui._apply_quick_action(command)

    for button in ui._dock_nav.values():
        button.click()

    ui._update_hardware()
    ui.close()
    app.quit()
    print("ui_navigation_smoke_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
