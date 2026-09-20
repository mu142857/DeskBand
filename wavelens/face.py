"""The mouth as an instrument: an open mouth in the picture is the Voices part.

MediaPipe's face landmarker finds the faces; only the largest one counts (the
person at the camera, not whoever walks past behind). "Open" takes two signals
agreeing: the jawOpen blendshape, which stays low for talking and for a smile
with teeth, and the lip gap against the mouth's width, which guards against the
blendshape misfiring. The gap alone is no good: it reads a face in profile as
wide open. Runs on the CPU in about 20 ms; the model file is Google's
face_landmarker.task (config.FACE_MODEL)."""

import os

import cv2

from . import config as C

LIP_TOP, LIP_BOTTOM, CORNER_L, CORNER_R = 13, 14, 61, 291      # inner lips, mouth corners
LIPS = (0, 17, 37, 39, 40, 61, 84, 91, 146, 181, 185, 267, 269, 270, 291, 314, 321, 375, 405, 409)


class Mouth:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        if not os.path.exists(C.FACE_MODEL):
            raise FileNotFoundError(f"{C.FACE_MODEL} (see README: face model)")
        self.mp = mp
        self.landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=C.FACE_MODEL, delegate=BaseOptions.Delegate.CPU),
            num_faces=3, output_face_blendshapes=True, min_face_detection_confidence=0.4))

    def look(self, frame):
        """(openness 0..1, mouth box) of the largest face, or None without a face.
        Openness is 0 unless both signals say open. Not thread-safe: hold Vision.model_lock."""
        h, w = frame.shape[:2]
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        res = self.landmarker.detect(image)
        if not res.face_landmarks:
            return None
        width = lambda lm: max(p.x for p in lm) - min(p.x for p in lm)
        i = max(range(len(res.face_landmarks)), key=lambda i: width(res.face_landmarks[i]))
        lm = res.face_landmarks[i]
        jaw = next((b.score for b in res.face_blendshapes[i] if b.category_name == "jawOpen"), 0.0)
        gap = abs(lm[LIP_BOTTOM].y - lm[LIP_TOP].y) * h
        span = ((lm[CORNER_R].x - lm[CORNER_L].x) ** 2 * w * w + (lm[CORNER_R].y - lm[CORNER_L].y) ** 2 * h * h) ** 0.5
        is_open = jaw >= C.MOUTH_JAW and span > 0 and gap / span >= C.MOUTH_GAP
        xs, ys = [lm[k].x * w for k in LIPS], [lm[k].y * h for k in LIPS]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        half = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.8         # some chin and nose around the lips
        box = [int(max(0, cx - half)), int(max(0, cy - half)), int(min(w, cx + half)), int(min(h, cy + half))]
        return (float(jaw) if is_open else 0.0), box
