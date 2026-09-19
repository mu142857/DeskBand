"""Camera + YOLO-World in its own thread. Publishes the latest frame and
detections; a slow inference step never touches the audio."""

import threading
import time
import cv2

from . import config as C


class Detection:
    __slots__ = ("name", "conf", "box")

    def __init__(self, name, conf, box):
        self.name, self.conf, self.box = name, conf, box


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


class Vision(threading.Thread):
    def __init__(self, cap=None):
        super().__init__(daemon=True)
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.detections = []
        self.last_seen = {}       # class -> (time, Detection) of the last sighting
        self.fps = 0.0
        self.infer_ms = 0.0
        self.ready = False
        self.error = None
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def run(self):
        try:
            from ultralytics import YOLO
            model = YOLO("yolov8s-worldv2.pt")
            model.set_classes(C.DETECT_CLASSES)
            cap = self.cap
        except Exception as e:      # surface to the UI instead of dying silently
            self.error = repr(e)
            return
        self.ready = True
        t_prev = time.time()
        while not self._halt.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            frame = cv2.flip(frame, 1)   # mirror, like a webcam preview
            t0 = time.time()
            res = model.predict(frame, device="mps", imgsz=C.DETECT_IMGSZ,
                                conf=C.DETECT_CONF, verbose=False)[0]
            self.infer_ms = 0.8 * self.infer_ms + 0.2 * (time.time() - t0) * 1000
            dets = []
            now = time.time()
            for cls, conf, xyxy in zip(res.boxes.cls, res.boxes.conf, res.boxes.xyxy):
                name = model.names[int(cls)]
                d = Detection(name, float(conf), [int(v) for v in xyxy.tolist()])
                dets.append(d)
                prev = self.last_seen.get(name)
                if prev is None or prev[0] < now or d.conf > prev[1].conf:
                    self.last_seen[name] = (now, d)
            with self.lock:
                self.frame = frame
                self.detections = dets
            self.fps = 0.9 * self.fps + 0.1 / max(1e-3, now - t_prev)
            t_prev = now
        cap.release()

    def snapshot(self):
        with self.lock:
            return self.frame, list(self.detections)

    def recent(self, within=0.5):
        """Best detection per class seen within the last `within` seconds."""
        now = time.time()
        return {n: d for n, (t, d) in self.last_seen.items() if now - t <= within}
