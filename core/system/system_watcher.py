from __future__ import annotations

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

_shutdown = False


def signal_shutdown() -> None:
    global _shutdown
    _shutdown = True


class SystemWatcher:
    def __init__(self):
        self.running = False
        self._alert_callback = None

    def set_alert_callback(self, callback):
        self._alert_callback = callback

    def watch_process(self, *_args, **_kwargs):
        return None

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
