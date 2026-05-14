# gesture_engine.py  —  J.A.R.V.I.S  HAND GESTURE ENGINE  v3
# MediaPipe 0.10+ Tasks API — RunningMode.VIDEO (correct for live streams)
# RunningMode.IMAGE was wrong — it creates a new thread pool per detect() call
# VIDEO mode keeps one persistent thread pool for the entire session
#
# ── Gesture Map ───────────────────────────────────────────────────
#  ✋ Open palm  (5 fingers)  → IDLE
#  ☝  Index only             → LISTENING
#  ✌  Index + middle         → CODING MODE
#  3 fingers (I+M+R)         → STUDY MODE
#  4 fingers (no thumb)      → GAMING MODE
#  👊 Fist                   → DANGER
#  👍 Thumb only             → VOLUME UP
#  🤙 Thumb + pinky          → GOOD NIGHT
#  🤏 Pinch                  → CONFIRM
# ─────────────────────────────────────────────────────────────────

import cv2
import time
import os
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

# ── Gesture labels ────────────────────────────────────────────────
G_IDLE   = "IDLE"
G_LISTEN = "LISTENING"
G_CODING = "CODING_MODE"
G_STUDY  = "STUDY_MODE"
G_GAMING = "GAMING_MODE"
G_DANGER = "DANGER"
G_VOL_UP = "VOLUME_UP"
G_NIGHT  = "GOOD_NIGHT"
G_CONFIRM= "CONFIRM"
G_NONE   = "NONE"

HOLD_TIME  = 1.0   # seconds gesture must be held before firing
COOLDOWN   = 3.0   # seconds before same gesture can re-fire
MODEL_PATH = "hand_landmarker.task"
MODEL_URL  = ("https://storage.googleapis.com/mediapipe-models/"
              "hand_landmarker/hand_landmarker/float16/latest/"
              "hand_landmarker.task")

# ── MediaPipe import ──────────────────────────────────────────────
MP_OK = False
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    MP_OK = True
    print("[Gesture] MediaPipe Tasks API ready.")
except Exception as e:
    print(f"[Gesture] MediaPipe unavailable: {e}")


def _ensure_model() -> bool:
    if os.path.exists(MODEL_PATH):
        return True
    try:
        print("[Gesture] Downloading hand_landmarker.task (~15MB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("[Gesture] Model downloaded.")
        return True
    except Exception as e:
        print(f"[Gesture] Download failed: {e}")
        print(f"  Manual download: {MODEL_URL}")
        print(f"  Save as: {os.path.abspath(MODEL_PATH)}")
        return False


# ── Hand skeleton connections ─────────────────────────────────────
_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (0,9),(9,10),(10,11),(11,12),
    (0,13),(13,14),(14,15),(15,16),
    (0,17),(17,18),(18,19),(19,20),
    (5,9),(9,13),(13,17),
]


class GestureEngine(QThread):
    """
    Background thread using MediaPipe VIDEO mode.
    VIDEO mode = one persistent detector, proper timestamp-based tracking.
    No thread pool exhaustion, no "shutdown" crashes.

    Singleton: only one instance runs at a time (prevents double camera open).

    Signals:
        gesture_signal(str)  — confirmed gesture label
        frame_signal(bytes)  — annotated JPEG for HUD overlay
    """
    gesture_signal = pyqtSignal(str)
    frame_signal   = pyqtSignal(bytes)

    def __init__(self, cam: int = 0):
        super().__init__()
        self.cam      = cam
        self.running  = False
        self._cur     = G_NONE
        self._start   = 0.0
        self._last    = G_NONE
        self._last_t  = 0.0
        self._t_start = 0.0    # video timestamp base

    # ── finger detection ──────────────────────────────────────────
    @staticmethod
    def _fingers(lms, is_right: bool) -> list:
        """[thumb, index, middle, ring, pinky] True=extended."""
        f = []
        f.append(lms[4].x < lms[3].x if is_right else lms[4].x > lms[3].x)
        for tip, pip in [(8,6),(12,10),(16,14),(20,18)]:
            f.append(lms[tip].y < lms[pip].y)
        return f

    @staticmethod
    def _is_pinch(lms) -> bool:
        dx = lms[4].x - lms[8].x
        dy = lms[4].y - lms[8].y
        return (dx*dx + dy*dy)**0.5 < 0.06

    # ── classify ─────────────────────────────────────────────────
    def _classify(self, lms, is_right: bool) -> str:
        if self._is_pinch(lms):                                    return G_CONFIRM
        f = self._fingers(lms, is_right)
        if not any(f):                                             return G_DANGER
        if all(f):                                                 return G_IDLE
        if f[0] and not any(f[1:]):                                return G_VOL_UP
        if f[0] and f[4] and not f[1] and not f[2] and not f[3]:  return G_NIGHT
        if f[1] and not f[2] and not f[3] and not f[4]:            return G_LISTEN
        if f[1] and f[2] and not f[3] and not f[4]:                return G_CODING
        if f[1] and f[2] and f[3] and not f[4]:                    return G_STUDY
        if not f[0] and f[1] and f[2] and f[3] and f[4]:           return G_GAMING
        return G_NONE

    # ── hold confirmation ─────────────────────────────────────────
    def _confirm(self, g: str):
        now = time.time()
        if g != self._cur:
            self._cur   = g
            self._start = now
            return None
        if now - self._start < HOLD_TIME:
            return None
        if g == self._last and now - self._last_t < COOLDOWN:
            return None
        self._last   = g
        self._last_t = now
        self._start  = now
        return g

    # ── draw ─────────────────────────────────────────────────────
    @staticmethod
    def _draw_skeleton(frame, lms):
        h, w = frame.shape[:2]
        pts = [(int(lm.x*w), int(lm.y*h)) for lm in lms]
        for a, b in _CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (0,180,200), 1, cv2.LINE_AA)
        for x, y in pts:
            cv2.circle(frame, (x, y), 3, (0,229,255), -1)

    @staticmethod
    def _draw_hud(frame, g: str, ratio: float):
        h, w = frame.shape[:2]
        if g not in (G_NONE, ""):
            cv2.putText(frame, g.replace("_"," "),
                        (8, h-28), cv2.FONT_HERSHEY_SIMPLEX,
                        0.40, (0,229,255), 1, cv2.LINE_AA)
            bw = int((w-16)*min(ratio, 1.0))
            cv2.rectangle(frame, (8,h-15),(w-8,h-7), (0,40,60), -1)
            if bw > 0:
                cv2.rectangle(frame, (8,h-15),(8+bw,h-7), (0,229,255), -1)
        # HUD border
        cv2.rectangle(frame, (0,0),(w-1,h-1), (0,229,255), 1)
        # label
        cv2.putText(frame, "GESTURE", (4, 11),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0,229,255,120), 1)

    # ── main loop ─────────────────────────────────────────────────
    def run(self):
        if not MP_OK:
            print("[Gesture] MediaPipe unavailable — gestures disabled.")
            return
        if not _ensure_model():
            print("[Gesture] Model missing — gestures disabled.")
            return

        self.running  = True
        self._t_start = time.time()
        print("[Gesture] Starting hand tracking (VIDEO mode)...")

        # VIDEO mode: one persistent detector, uses monotonic timestamps
        base = mp_python.BaseOptions(model_asset_path=MODEL_PATH)
        opts = mp_vision.HandLandmarkerOptions(
            base_options                  = base,
            running_mode                  = mp_vision.RunningMode.VIDEO,
            num_hands                     = 1,
            min_hand_detection_confidence = 0.65,
            min_hand_presence_confidence  = 0.55,
            min_tracking_confidence       = 0.55,
        )

        from core.api.camera_manager import CameraManager
        cam = CameraManager.get_instance()

        if cam is None:
            print("[Gesture] Cannot open camera.")
            self.running = False
            return

        try:
            with mp_vision.HandLandmarker.create_from_options(opts) as det:
                print("[Gesture] Detector ready.")
                while self.running:
                    frame = cam.get_frame()
                    if frame is None:
                        self.msleep(50)   # QThread-safe: won't block event delivery
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    # VIDEO mode requires monotonically increasing timestamp_ms
                    ts_ms = int((time.time() - self._t_start) * 1000)

                    mp_img = mp.Image(
                        image_format=mp.ImageFormat.SRGB,
                        data=rgb
                    )

                    # detect_for_video — correct call for VIDEO mode
                    res = det.detect_for_video(mp_img, ts_ms)

                    out = frame.copy()
                    g   = G_NONE

                    if res.hand_landmarks:
                        lms      = res.hand_landmarks[0]
                        is_right = res.handedness[0][0].category_name == "Right"
                        g        = self._classify(lms, is_right)
                        conf     = self._confirm(g)
                        ratio    = ((time.time()-self._start)/HOLD_TIME
                                    if g != G_NONE else 0.0)
                        self._draw_skeleton(out, lms)
                        self._draw_hud(out, g, ratio)
                        if conf and conf != G_NONE:
                            self.gesture_signal.emit(conf)
                    else:
                        # no hand in frame — reset hold timer
                        self._cur   = G_NONE
                        self._start = 0.0
                        self._draw_hud(out, G_NONE, 0.0)

                    _, jpg = cv2.imencode(
                        ".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self.frame_signal.emit(bytes(jpg))

                    self.msleep(50)   # ~20 fps, QThread-native sleep

        except RuntimeError as e:
            if "shutdown" not in str(e).lower():
                print(f"[Gesture] Fatal error: {e}")
        except Exception as e:
            print(f"[Gesture] Fatal error: {e}")
        finally:
            print("[Gesture] Engine stopped.")

    def stop(self):
        self.running = False
        self.wait(3000)