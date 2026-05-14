# identity/liveness.py — JARVIS LIVENESS DETECTOR v2
# ──────────────────────────────────────────────────────────────────────────────
# BUG FIXES v2:
#   1. CRITICAL: Old version returned True if ANY frame had EAR < 0.21
#      A photo with closed eyes or sleepy expression would pass.
#      Fixed: Now requires a proper OPEN → CLOSED → OPEN blink transition.
#   2. Added max_num_faces=1 + min_detection_confidence for speed.
#   3. FaceMesh never closed — added __del__ to release resources.
#   4. Added blink counter + reset() method for multi-attempt auth.
# ──────────────────────────────────────────────────────────────────────────────

import cv2
import numpy as np

try:
    import mediapipe as mp
except Exception:
    mp = None

_EAR_CLOSED_THRESH = 0.21   # below this → eye is closed
_EAR_OPEN_THRESH   = 0.26   # above this → eye is open
_MIN_BLINK_FRAMES  = 1      # at least N consecutive closed frames for a valid blink


class LivenessDetector:
    """
    Detects a real blink via EAR state machine: OPEN → CLOSED → OPEN.
    A static photo with always-closed eyes will NOT pass because we require
    the transition from open → closed → open.
    """

    def __init__(self):
        if mp is None:
            raise RuntimeError("MediaPipe is not installed.")

        solutions = getattr(mp, "solutions", None)
        if solutions is None or not hasattr(solutions, "face_mesh"):
            raise RuntimeError("MediaPipe FaceMesh API unavailable.")

        self.mp_face   = solutions.face_mesh
        self.face_mesh = self.mp_face.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

        # State machine: OPEN → CLOSED → OPEN = valid blink
        self._was_open      = False   # whether eyes were open before this frame
        self._closed_count  = 0       # consecutive frames with eyes closed
        self._blink_count   = 0       # total confirmed blinks this session

    # ── EAR (Eye Aspect Ratio) ──────────────────────────────────────────────
    @staticmethod
    def _ear(eye: np.ndarray) -> float:
        """Six-point EAR: (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)"""
        a = np.linalg.norm(eye[1] - eye[5])
        b = np.linalg.norm(eye[2] - eye[4])
        c = np.linalg.norm(eye[0] - eye[3])
        return (a + b) / (2.0 * c + 1e-6)   # 1e-6 avoids div-by-zero

    # ── Public API ──────────────────────────────────────────────────────────
    def detect_blink(self, frame: np.ndarray) -> bool:
        """
        Returns True ONCE when a complete blink cycle is detected:
          1. Eyes must have been OPEN first (EAR > _EAR_OPEN_THRESH)
          2. Eyes close (EAR < _EAR_CLOSED_THRESH) for ≥ _MIN_BLINK_FRAMES
          3. Eyes reopen (EAR > _EAR_OPEN_THRESH)
        This prevents a static closed-eye photo from passing.
        """
        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.face_mesh.process(rgb)

        if not result.multi_face_landmarks:
            return False

        h, w  = frame.shape[:2]
        lm    = result.multi_face_landmarks[0].landmark

        L_IDX = [33,  160, 158, 133, 153, 144]
        R_IDX = [362, 385, 387, 263, 373, 380]

        left  = np.array([[lm[i].x * w, lm[i].y * h] for i in L_IDX])
        right = np.array([[lm[i].x * w, lm[i].y * h] for i in R_IDX])

        ear = (self._ear(left) + self._ear(right)) / 2.0

        if ear > _EAR_OPEN_THRESH:
            if self._was_open and self._closed_count >= _MIN_BLINK_FRAMES:
                # Completed: open → closed → open  ✓
                self._closed_count = 0
                self._blink_count += 1
                return True
            # Eyes are open — start watching for a close
            self._was_open     = True
            self._closed_count = 0

        elif ear < _EAR_CLOSED_THRESH:
            if self._was_open:
                self._closed_count += 1

        return False

    def reset(self):
        """Reset state machine for a new auth attempt."""
        self._was_open     = False
        self._closed_count = 0

    @property
    def blink_count(self) -> int:
        return self._blink_count

    def __del__(self):
        try:
            self.face_mesh.close()
        except Exception:
            pass
