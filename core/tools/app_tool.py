from __future__ import annotations


class AppTool:
    def open(self, app_name: str) -> str:
        return f"App launch requested: {app_name}"

    def close(self, app_name: str) -> str:
        return f"App close requested: {app_name}"
