import cv2
import os
import numpy as np
import time

# ─────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────
MODEL_PATH       = "memory/face_model.yml"
SAMPLES_DIR      = "memory/face_samples"
ENROLL_TARGET    = 25          # number of samples to collect
CONFIDENCE_THRESH = 70         # LBPH: lower = better. <70 means strong match
VOTE_FRAMES      = 60          # frames to sample during auth
VOTE_WIN_RATIO   = 0.45        # fraction of frames that must vote "owner"
MIN_VOTES        = 4           # minimum absolute "owner" votes needed
FACE_SIZE        = (200, 200)


def _preprocess(gray_face: np.ndarray) -> np.ndarray:
    """Normalize lighting with CLAHE and resize."""
    face = cv2.resize(gray_face, FACE_SIZE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(face)


def _get_cascade():
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )


def _detect_best_face(gray: np.ndarray, cascade):
    """Return the largest face ROI found, or None."""
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80))
    if len(faces) == 0:
        return None
    # pick biggest face
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces[0]
    return gray[y:y + h, x:x + w], (x, y, w, h)


class FaceAuth:

    def __init__(self):
        print("[FaceAuth] Loading Haar Cascade...")
        self.cascade = _get_cascade()
        self._recognizer = None   # lazy-loaded
        print("[FaceAuth] Init complete.")

    # ─── LAZY LOAD recognizer ────────────────────────
    def _load_recognizer(self):
        if self._recognizer is not None:
            return True
        if not os.path.exists(MODEL_PATH):
            return False
        try:
            r = cv2.face.LBPHFaceRecognizer_create()
            r.read(MODEL_PATH)
            self._recognizer = r
            return True
        except Exception as e:
            print(f"[FaceAuth] Failed to load model: {e}")
            # Model might be corrupted - remove it so user can re-enroll
            try:
                os.remove(MODEL_PATH)
                print("[FaceAuth] Corrupted model removed. Please re-enroll.")
            except Exception:
                pass
            return False

    # ═══════════════ ENROLL OWNER ════════════════════
    def enroll_owner(self):
        """
        Collect ENROLL_TARGET face samples, train an LBPH model, save it.
        Also saves sample images for debugging.
        """
        os.makedirs(SAMPLES_DIR, exist_ok=True)

        from core.api.camera_manager import CameraManager
        cam = CameraManager.get_instance()

        print(f"[ENROLL] Look at the camera — collecting {ENROLL_TARGET} samples...")
        print("[ENROLL] Move your head slowly side-to-side for variety.")

        samples = []
        collected = 0
        last_capture = 0
        CAPTURE_INTERVAL = 0.3   # seconds between samples

        while collected < ENROLL_TARGET:
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.03)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            result = _detect_best_face(gray, self.cascade)

            # HUD overlay
            display = frame.copy()
            bar_w = int((collected / ENROLL_TARGET) * frame.shape[1])
            cv2.rectangle(display, (0, frame.shape[0] - 20), (bar_w, frame.shape[0]), (0, 200, 80), -1)
            cv2.putText(display, f"Enrolling: {collected}/{ENROLL_TARGET}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 120), 2)

            if result is not None:
                face_roi, (x, y, w, h) = result
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 80), 2)

                now = time.time()
                if now - last_capture > CAPTURE_INTERVAL:
                    processed = _preprocess(face_roi)
                    samples.append(processed)

                    # Save sample image
                    cv2.imwrite(f"{SAMPLES_DIR}/sample_{collected:02d}.jpg", processed)
                    collected += 1
                    last_capture = now
                    print(f"[ENROLL] Sample {collected}/{ENROLL_TARGET} captured")
            else:
                cv2.putText(display, "No face detected", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 255), 2)

            cv2.imshow("JARVIS — Owner Enrollment", display)
            if cv2.waitKey(1) & 0xFF == 27:
                print("[ENROLL] Cancelled.")
                cv2.destroyAllWindows()
                return False

        cv2.destroyAllWindows()

        # ─── Train LBPH ────────────────────────────
        print("[ENROLL] Training face model...")
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        labels = [0] * len(samples)   # owner = label 0
        recognizer.train(samples, np.array(labels))
        recognizer.save(MODEL_PATH)
        self._recognizer = recognizer
        print(f"[ENROLL] Model saved → {MODEL_PATH}")
        return True

    # ═══════════════ RE-ENROLL / UPDATE ══════════════
    def update_enrollment(self):
        """Collect more samples and update (not replace) the existing model."""
        if not self._load_recognizer():
            print("[ENROLL] No existing model — running full enrollment.")
            return self.enroll_owner()

        os.makedirs(SAMPLES_DIR, exist_ok=True)

        from core.api.camera_manager import CameraManager
        cam = CameraManager.get_instance()

        print("[ENROLL] Collecting 15 update samples...")
        samples, collected = [], 0
        last_capture = 0

        while collected < 15:
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.03)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            result = _detect_best_face(gray, self.cascade)

            if result is not None:
                face_roi, _ = result
                now = time.time()
                if now - last_capture > 0.3:
                    samples.append(_preprocess(face_roi))
                    collected += 1
                    last_capture = now

            time.sleep(0.03)

        labels = [0] * len(samples)
        self._recognizer.update(samples, np.array(labels))
        self._recognizer.save(MODEL_PATH)
        print("[ENROLL] Model updated.")
        return True

    # ═══════════════ AUTHENTICATE ════════════════════
    def authenticate(self) -> str:
        """
        Returns:
            'owner'      — face matched with high confidence
            'guest'      — face not matched / low votes
            'no_profile' — model not enrolled yet
        """
        if not os.path.exists(MODEL_PATH):
            return "no_profile"

        if not self._load_recognizer():
            return "no_profile"

        from core.api.camera_manager import CameraManager
        cam = CameraManager.get_instance()

        owner_votes = 0
        total_votes = 0
        confidence_sum = 0.0
        frame_count = 0
        deadline = time.time() + 5.0   # 5-second window

        while frame_count < VOTE_FRAMES and time.time() < deadline:
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.03)
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            result = _detect_best_face(gray, self.cascade)
            frame_count += 1

            if result is None:
                time.sleep(0.03)
                continue

            face_roi, _ = result
            processed = _preprocess(face_roi)

            label, confidence = self._recognizer.predict(processed)
            total_votes += 1
            confidence_sum += confidence

            print(f"[AUTH] Frame {frame_count}: label={label}, confidence={confidence:.1f}")

            if label == 0 and confidence < CONFIDENCE_THRESH:
                owner_votes += 1

            # Early exit if we have enough confident votes
            if owner_votes >= MIN_VOTES and total_votes >= 6:
                vote_ratio = owner_votes / total_votes
                if vote_ratio >= VOTE_WIN_RATIO:
                    avg_conf = confidence_sum / total_votes
                    print(f"[AUTH] Early pass — votes={owner_votes}/{total_votes} avg_conf={avg_conf:.1f}")
                    return "owner"

            time.sleep(0.03)

        # ─── Final verdict ──────────────────────────
        if total_votes == 0:
            print("[AUTH] No face detected during window.")
            return "guest"

        vote_ratio = owner_votes / total_votes
        avg_conf = confidence_sum / total_votes
        print(f"[AUTH] Result: votes={owner_votes}/{total_votes} ({vote_ratio:.0%}), avg_conf={avg_conf:.1f}")

        if owner_votes >= MIN_VOTES and vote_ratio >= VOTE_WIN_RATIO:
            return "owner"

        return "guest"

    # ═══════════════ QUICK CHECK (non-blocking) ══════
    def quick_check(self, frame: np.ndarray) -> tuple[str, float]:
        """
        Single-frame check. Returns (label_str, confidence).
        Used by auth_window for live feedback.
        """
        if not self._load_recognizer():
            return ("no_profile", 999.0)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result = _detect_best_face(gray, self.cascade)

        if result is None:
            return ("no_face", 999.0)

        face_roi, _ = result
        processed = _preprocess(face_roi)
        label, confidence = self._recognizer.predict(processed)

        if label == 0 and confidence < CONFIDENCE_THRESH:
            return ("owner", confidence)
        return ("guest", confidence)