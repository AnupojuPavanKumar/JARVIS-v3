from __future__ import annotations

import psutil


class SystemTool:
    def status(self) -> str:
        return f"CPU {psutil.cpu_percent()}%, RAM {psutil.virtual_memory().percent}%"
