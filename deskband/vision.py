"""Camera and YOLO-World, each in its own thread.

The capture thread keeps the newest frame available at camera rate so the
preview stays smooth; the detector thread works on whatever frame is newest
(a large open-vocabulary model only manages a few frames a second). Neither
ever touches the audio. When a photo is taken, `detect()` can be called once
more on the frozen frame at full resolution."""

import os
import threading
import time
import cv2

from . import config as C


class Detection:
    """name = the instrument's object (config key); alias = the prompt that fired."""
    __slots__ = ("name", "conf", "box", "alias")

    def __init__(self, name, conf, box, alias=None):
        self.name, self.conf, self.box, self.alias = name, conf, box, alias or name

    @property
    def shown(self):
        """What to call it on screen: a tablet is a tablet, not a laptop."""
        return C.SHOW_AS.get(self.alias, self.alias)


def iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def inside(a, b):
    """How much of the smaller box lies within the other, 0..1."""
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def same_thing(a, b):
    """Are these two boxes one physical object?
    Same instrument: overlapping boxes ("cup" and "mug", or two passes over the
    picture), or one box swallowed by the other (the whole cup and its handle).
    Different instruments: only when the boxes nearly coincide, i.e. one object
    read two ways (a cup that is also called a bottle). A pen lying on a book is
    inside the book's box but nowhere near the same box, so both survive."""
    if a.name == b.name:
        return iou(a.box, b.box) > 0.5 or inside(a.box, b.box) > 0.75
    return iou(a.box, b.box) > 0.6


def merge_duplicates(dets):
    """One object, one box: the most confident reading wins."""
    kept = []
    for d in sorted(dets, key=lambda d: -d.conf):
        if not any(same_thing(k, d) for k in kept):
            kept.append(d)
    return kept


def open_camera():
    """Open the webcam. Must be called on the main thread: macOS only shows
    the camera permission prompt for a request made from there."""
    cap = cv2.VideoCapture(C.CAMERA_INDEX)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


def model_path():
    """Preferred model if its weights are here, else the small one."""
    for name in (C.DETECT_MODEL, C.DETECT_MODEL_FALLBACK):
        path = os.path.join(C.ROOT, name)
        if os.path.exists(path):
            return path
    return C.DETECT_MODEL_FALLBACK          # ultralytics downloads it


class Vision(threading.Thread):
    def __init__(self, cap=None):
        super().__init__(daemon=True)
        self.cap = cap
        self.lock = threading.Lock()           # frame / detections
        self.model_lock = threading.Lock()     # one inference at a time
        self.model = None
        self.model_name = ""
        self.frame = None
        self.frame_id = 0
        self.detections = []
        self.last_seen = {}       # part -> (time, Detection) of the last sighting
        self.fps = 0.0            # detector rate
        self.cam_fps = 0.0
        self.infer_ms = 0.0
        self.error = None
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    # ---------------------------------------------------------- capture
    def _capture_loop(self):
        t_prev = time.time()
        while not self._halt.is_set():
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)       # mirror, like a webcam preview
            with self.lock:
                self.frame = frame
                self.frame_id += 1
            now = time.time()
            self.cam_fps = 0.9 * self.cam_fps + 0.1 / max(1e-3, now - t_prev)
            t_prev = now
        self.cap.release()

    # ---------------------------------------------------------- detection
    def detect(self, frame, imgsz):
        """Run the model once. Safe to call from any thread."""
        with self.model_lock:
            res = self.model.predict(frame, device="mps", imgsz=imgsz,
                                     conf=C.DETECT_CONF, verbose=False)[0]
        dets = []
        for cls, conf, xyxy in zip(res.boxes.cls, res.boxes.conf, res.boxes.xyxy):
            alias = self.model.names[int(cls)]
            dets.append(Detection(C.ALIASES[alias], float(conf), [int(v) for v in xyxy.tolist()], alias))
        return merge_duplicates(dets)

    def run(self):
        try:
            from ultralytics import YOLO
            path = model_path()
            model = YOLO(path)
            model.set_classes(C.DETECT_CLASSES)
            self.model_name = os.path.basename(path)
            self.model = model
        except Exception as e:      # surface to the UI instead of dying silently
            self.error = repr(e)
            return
        threading.Thread(target=self._capture_loop, daemon=True).start()
        seen_id = -1
        t_prev = time.time()
        while not self._halt.is_set():
            with self.lock:
                frame, fid = self.frame, self.frame_id
            if frame is None or fid == seen_id:
                time.sleep(0.005)
                continue
            seen_id = fid
            t0 = time.time()
            dets = self.detect(frame, C.DETECT_IMGSZ)
            now = time.time()
            self.infer_ms = 0.8 * self.infer_ms + 0.2 * (now - t0) * 1000
            for d in dets:
                prev = self.last_seen.get(d.name)
                if prev is None or prev[0] < now or d.conf > prev[1].conf:
                    self.last_seen[d.name] = (now, d)
            with self.lock:
                self.detections = dets
            self.fps = 0.9 * self.fps + 0.1 / max(1e-3, now - t_prev)
            t_prev = now

    def snapshot(self):
        with self.lock:
            return self.frame, list(self.detections)

    def recent(self, within=0.5):
        """Best detection per part seen within the last `within` seconds."""
        now = time.time()
        return {n: d for n, (t, d) in self.last_seen.items() if now - t <= within}
