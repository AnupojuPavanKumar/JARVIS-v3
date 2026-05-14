from __future__ import annotations

import threading
import time


class SystemMonitor:
    def __init__(self):
        self.running = True
        self.alert_message = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SystemMonitor")
        self._thread.start()

    def _loop(self):
        while self.running:
            time.sleep(0.2)

    def get_alert(self):
        with self._lock:
            msg = self.alert_message
            self.alert_message = None
            return msg
