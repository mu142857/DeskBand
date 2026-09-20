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


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def on_edge(box, shape, margin=2):
    """Does the box run off the picture? Those are cut-off objects, the detector's weakest guesses."""
    h, w = shape[:2]
    return box[0] <= margin or box[1] <= margin or box[2] >= w - margin or box[3] >= h - margin


def sliver(box, shape):
    """A thin strip along the frame edge: a sleeve or a chair arm read as glasses or a phone."""
    return on_edge(box, shape) and min(box[2] - box[0], box[3] - box[1]) < C.SLIVER_PX


def confirm(dets, other, shape):
    """Keep the sure detections; a weak one stays only if the other pass saw the
    same thing in the same place (it need not have been confident about it)."""
    kept = []
    for d in dets:
        if d.conf < C.DETECT_SURE:
            need = C.CONFIRM_EDGE if on_edge(d.box, shape) else C.CONFIRM_CONF
            if not any(o.name == d.name and o.conf >= need and iou(o.box, d.box) > 0.5 for o in other):
                continue
        kept.append(d)
    return kept


def echoes(d, current):
    """Is this remembered detection just an earlier reading of something in `current`?
    The object may have moved since, so this is looser than same_thing: similar size
    and mostly overlapping. A pen on a book is far smaller than the book and passes."""
    return any(inside(d.box, k.box) > 0.5 and min(area(d.box), area(k.box)) > 0.4 * max(area(d.box), area(k.box))
               for k in current)


def open_camera():
    """Open the webcam. Must be called on the main thread: macOS only shows
    the camera permission prompt for a request made from there."""
    cap = cv2.VideoCapture(C.CAMERA_INDEX)
    if not cap.isOpened():
        cap.release()
        return None
    # Keep the device's native frame/aspect ratio. Continuity Camera can crop
    # when a 16:9 capture mode is requested from its wider camera feed.
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
        self.face = None          # face.Mouth, or None when MediaPipe / its model is missing
        self.jaw = None           # last openness reading of the largest face, for the debug line
        self.frame = None
        self.frame_id = 0
        self.detections = []
        self.last_seen = {}       # part -> (time, Detection) of the last sighting
        self.fps = 0.0            # detector rate
        self.cam_fps = 0.0
        self.infer_ms = 0.0
        self.error = None
        self.failed = False       # the model could not be read: nothing more is coming
        self._halt = threading.Event()

    @property
    def loading(self):
        """True until the first frame arrives (the model is read before the
        camera loop starts), or until the model gives up. The App waits for this
        to end before starting the music, so nothing plays over the loading screen."""
        return self.frame is None and not self.failed

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
            if C.MIRROR_CAMERA:
                frame = cv2.flip(frame, 1)
            with self.lock:
                self.frame = frame
                self.frame_id += 1
            now = time.time()
            self.cam_fps = 0.9 * self.cam_fps + 0.1 / max(1e-3, now - t_prev)
            t_prev = now
        self.cap.release()

    # ---------------------------------------------------------- detection
    def detect(self, frame, imgsz, conf=None, merge=True):
        """Run the model once. Safe to call from any thread."""
        with self.model_lock:
            res = self.model.predict(frame, device="mps", imgsz=imgsz,
                                     conf=conf or C.DETECT_CONF, verbose=False)[0]
        dets = []
        for cls, conf, xyxy in zip(res.boxes.cls, res.boxes.conf, res.boxes.xyxy):
            alias = self.model.names[int(cls)]
            box = [int(v) for v in xyxy.tolist()]
            if not sliver(box, frame.shape):
                dets.append(Detection(C.ALIASES[alias], float(conf), box, alias))
        return merge_duplicates(dets) if merge else dets

    def mouth(self, frame):
        """[Detection] for an open mouth on the largest face, else []."""
        if self.face is None:
            return []
        with self.model_lock:
            seen = self.face.look(frame)
        self.jaw = seen[0] if seen else None
        return [Detection("mouth", seen[0], seen[1])] if seen and seen[0] > 0 else []

    def careful(self, frame):
        """The look that decides a photo: two passes at different sizes over the
        frozen frame. False positives rarely survive a change of scale, real
        objects do, so weak detections must show up in both."""
        a = self.detect(frame, C.DETECT_IMGSZ, C.DETECT_FLOOR, merge=False)   # unmerged: a one-pass fluke must
        b = self.detect(frame, C.SHOOT_IMGSZ, C.DETECT_FLOOR, merge=False)    # not outrank a reading both agree on
        sure = [d for d in a if d.conf >= C.DETECT_CONF], [d for d in b if d.conf >= C.DETECT_CONF]
        return merge_duplicates(confirm(sure[0], b, frame.shape) + confirm(sure[1], a, frame.shape)) + self.mouth(frame)

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
            self.failed = True
            return
        try:
            from .face import Mouth
            self.face = Mouth()
        except Exception as e:      # no MediaPipe: everything but the mouth still works
            print("[face] unavailable:", repr(e), flush=True)
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
            dets = self.detect(frame, C.DETECT_IMGSZ) + self.mouth(frame)
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
