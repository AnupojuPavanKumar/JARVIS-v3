import cv2
import threading
import time

# Consecutive read failures before giving up on the camera
_MAX_READ_FAILURES = 10
_READ_FAIL_SLEEP   = 0.1  # seconds between failed reads (prevents busy-loop crash)


class CameraManager:
    _instance = None
    _lock = threading.Lock()   # guards singleton creation

    def __init__(self):
        self._available = False
        self.frame      = None
        self.running    = False
        self.lock       = threading.Lock()
        self.subscribers: list = []

        # Try to open camera — fail gracefully if not present
        try:
            self.cap = cv2.VideoCapture(0)
            if self.cap.isOpened():
                # Verify we can actually read a frame
                ret, _ = self.cap.read()
                if ret:
                    self._available = True
                    self.running    = True
                    self.thread = threading.Thread(
                        target=self._capture_loop, daemon=True, name="CameraCapture"
                    )
                    self.thread.start()
                else:
                    print("[CameraManager] Camera opened but can't read frames — disabled.")
                    self.cap.release()
            else:
                print("[CameraManager] No camera found at index 0 — gestures disabled.")
        except Exception as e:
            print(f"[CameraManager] Camera init error: {e} — gestures disabled.")
            self._available = False

    @classmethod
    def get_instance(cls):
        """Return singleton CameraManager. Creates it on first call."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = CameraManager()
        return cls._instance if cls._instance._available else None

    @property
    def is_available(self) -> bool:
        return self._available

    def _capture_loop(self):
        failures = 0
        while self.running:
            try:
                ret, frame = self.cap.read()
                if not ret:
                    failures += 1
                    if failures >= _MAX_READ_FAILURES:
                        print("[CameraManager] Too many read failures — stopping capture.")
                        self._available = False
                        self.running    = False
                        break
                    time.sleep(_READ_FAIL_SLEEP)  # CRITICAL: prevents tight busy-loop crash
                    continue
                failures = 0
                with self.lock:
                    self.frame = frame.copy()

                # push to subscribers
                for callback in self.subscribers:
                    try:
                        callback(frame)
                    except Exception:
                        pass

                time.sleep(0.033)  # ~30fps cap — prevents CPU hammering

            except Exception as e:
                print(f"[CameraManager] Capture error: {e}")
                time.sleep(0.5)

    def get_frame(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def subscribe(self, callback):
        self.subscribers.append(callback)

    def stop(self):
        self.running     = False
        self._available  = False
        try:
            if hasattr(self, 'thread'):
                self.thread.join(timeout=2.0)
        except Exception:
            pass
        try:
            if hasattr(self, 'cap'):
                self.cap.release()
        except Exception:
            pass