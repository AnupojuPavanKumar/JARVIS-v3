from __future__ import annotations


class _EmptyCascade:
    def empty(self) -> bool:
        return False


class VisionEngine:
    """Legacy camera/vision facade backed by the newer worker when available."""

    CAM_INDEX = 0

    def __init__(self):
        self.cascade = _EmptyCascade()

    def describe_screen(self) -> str:
        try:
            from workers.vision_worker import get_vision_worker
            return get_vision_worker().analyse("screen").description
        except Exception as exc:
            return f"Vision unavailable: {exc}"

    def capture(self):
        return None
