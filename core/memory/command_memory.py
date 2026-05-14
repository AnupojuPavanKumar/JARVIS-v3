from __future__ import annotations

import threading

MAX_LEARNED = 100


class CommandMemory:
    def __init__(self):
        self._lock = threading.RLock()
        self.data: dict[str, list[str]] = {}

    def learn(self, command: str, steps: list[str]) -> None:
        key = command.lower().strip()
        with self._lock:
            self.data[key] = list(steps)
            while len(self.data) > MAX_LEARNED:
                self.data.pop(next(iter(self.data)))

    def recall(self, command: str) -> list[str] | None:
        key = command.lower().strip()
        with self._lock:
            if key in self.data:
                return list(self.data[key])
            return None
