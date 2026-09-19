"""DeskBand - put things on the desk, shoot a photo, they become a band."""

import math
import os
import sys
import time

# python.org builds ship without a CA bundle; point urllib at certifi so the
# first-run model download works.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

import cv2
import numpy as np

from deskband import config as C
from deskband import ui
from deskband.music import Composer
from deskband.synth import Engine
from deskband.vision import Vision

WINDOW = "DeskBand"
W, H = 1280, 720
PREVIEW, SHOW = "preview", "show"


class Box:
    """A smoothed on-screen box for one object class (preview mode)."""

    def __init__(self, det):
        self.xyxy = np.array(det.box, np.float32)
        self.alpha = 0.0
        self.seen = time.time()
        self.det = det


class App:
    def __init__(self):
        self.composer = Composer()
        self.engine = Engine(self.composer)
        self.vision = Vision()
        self.base = ui.Base(W, H)
        self.state = PREVIEW
        self.captured = None            # (frame, [Detection]) once shot
        self.preview_boxes = {}         # class -> Box
        self.flash = 0.0
        self.debug = False
        self.fullscreen = False
        self.mouse = (-1, -1)
        self.shutter = (W // 2, H - 64, 26)
        self.t_prev = time.time()
        self.disp_fps = 0.0

    # ------------------------------------------------------------ actions
    def shoot(self):
        frame, dets = self.vision.snapshot()
        if frame is None:
            return
        names = {d.name for d in dets}
        for name, d in self.vision.recent(0.5).items():   # smooth over flicker
            if name not in names:
                dets.append(d)
                names.add(name)
        self.captured = (frame.copy(), dets)
        self.state = SHOW
        self.flash = 1.0
        for name in C.INSTRUMENTS:
            self.engine.set_active(name, name in names)

    def retake(self):
        self.state = PREVIEW
        self.captured = None
        for name in C.INSTRUMENTS:
            self.engine.set_active(name, False)

    def toggle(self):
        if self.state == PREVIEW:
            self.shoot()
        else:
            self.retake()

    def on_mouse(self, event, x, y, flags, param):
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            cx, cy, r = self.shutter
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 8) ** 2:
                self.toggle()

    # ------------------------------------------------------------ drawing
    def glow(self, name):
        """0..1: how recently this part played a note."""
        hit = self.engine.hits.get(name)
        if hit is None:
            return 0.0
        age = (self.engine.pos - hit) / C.SAMPLE_RATE
        return math.exp(-max(age, 0) / 0.22)

    def draw_box(self, out, frame, det, alpha, lit, glow):
        x0, y0, x1, y1 = det.box
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        s = 1 + 0.025 * glow
        w, h = (x1 - x0) * s, (y1 - y0) * s
        x0, y0 = int(max(cx - w / 2, 0)), int(max(cy - h / 2, 0))
        x1, y1 = int(min(cx + w / 2, W - 1)), int(min(cy + h / 2, H - 1))
        r = 10
        if lit:
            ui.keep_colour(out, frame, x0, y0, x1, y1, r, alpha * (0.85 + 0.15 * glow))
        ui.outline(out, x0, y0, x1, y1, r, alpha * (0.55 + 0.45 * glow))
        spec = C.INSTRUMENTS[det.name]
        ty = y0 - 26 if y0 > 34 else y1 + 8
        adv = ui.text(out, det.name, x0 + 2, ty, 17, alpha * 0.95, "Medium")
        ui.text(out, "  ·  " + spec["label"], x0 + 2 + adv, ty, 17, alpha * 0.7, "Light")

    def draw_preview(self, out, frame, dets, dt):
        now = time.time()
        best = {}
        for d in dets:
            if d.name not in best or d.conf > best[d.name].conf:
                best[d.name] = d
        for name, d in best.items():
            b = self.preview_boxes.get(name)
            if b is None:
                b = self.preview_boxes[name] = Box(d)
            b.xyxy = ui.ease(b.xyxy, np.array(d.box, np.float32), dt, 0.12)
            b.seen = now
            b.det = d
        for name in list(self.preview_boxes):
            b = self.preview_boxes[name]
            target = 1.0 if now - b.seen < 0.4 else 0.0
            b.alpha = ui.ease(b.alpha, target, dt, 0.15)
            if b.alpha < 0.02 and target == 0:
                del self.preview_boxes[name]
                continue
            d = b.det
            d.box = [int(v) for v in b.xyxy]
            self.draw_box(out, frame, d, 0.45 * b.alpha, lit=False, glow=0.0)

    def draw_card(self, out, members):
        """Bottom-left frosted card: who is in the band right now."""
        rows = [(n, C.INSTRUMENTS[n]["label"]) for n in C.INSTRUMENTS if n in members]
        x0, y0 = 28, H - 28 - (58 + 30 * max(len(rows), 1))
        x1 = x0 + 320
        ui.frosted(out, x0, y0, x1, H - 28)
        title = "Band" if self.state == SHOW else "On the desk"
        ui.text(out, title, x0 + 20, y0 + 16, 20, 0.95, "Semibold")
        ui.text(out, self.composer.chord_name, x1 - 20, y0 + 20, 15, 0.55, "Light", align="right")
        y = y0 + 54
        if not rows:
            ui.text(out, "nothing yet", x0 + 20, y, 16, 0.5, "Light")
        for name, label in rows:
            g = self.glow(name) if self.state == SHOW else 0.0
            ui.circle(out, x0 + 26, y + 10, 4, 0.35 + 0.65 * g, thickness=-1)
            ui.text(out, name, x0 + 42, y, 16, 0.9, "Regular")
            ui.text(out, label, x1 - 20, y, 16, 0.6, "Light", align="right")
            y += 30

    def draw_shutter(self, out):
        cx, cy, r = self.shutter
        mx, my = self.mouse
        hover = (mx - cx) ** 2 + (my - cy) ** 2 <= (r + 8) ** 2
        ui.circle(out, cx, cy, r, 0.9 if hover else 0.7, thickness=2)
        if self.state == PREVIEW:
            ui.circle(out, cx, cy, r - 6, 0.95 if hover else 0.8, thickness=-1)
            hint = "space  ·  shoot"
        else:
            s = r - 12
            m = ui.rounded_mask(2 * s, 2 * s, 4).astype(np.float32) / 255.0
            ui._blend(out, m, ui.WHITE, 0.9 if hover else 0.75, cx - s, cy - s)
            hint = "space  ·  retake"
        ui.text(out, hint, cx, cy + r + 10, 13, 0.55, "Light", align="center")

    def render(self, dt):
        if self.state == SHOW:
            frame, dets = self.captured
        else:
            frame, dets = self.vision.snapshot()
        if frame is None:
            out = np.zeros((H, W, 3), np.uint8)
            out[:] = ui.TONE_DARK.astype(np.uint8)
            msg = self.vision.error or "starting camera and model…"
            ui.text(out, msg, W // 2, H // 2 - 10, 18, 0.7, "Light", align="center")
            ui.text(out, "DeskBand", 28, 22, 22, 0.9, "Semibold")
            return out
        if frame.shape[1] != W or frame.shape[0] != H:
            frame = cv2.resize(frame, (W, H))
        out = self.base.render(frame, dim=0.12 if self.state == PREVIEW else 0.0)
        if self.state == SHOW:
            for d in dets:
                self.draw_box(out, frame, d, 1.0, lit=True, glow=self.glow(d.name))
            members = {d.name for d in dets}
        else:
            self.draw_preview(out, frame, dets, dt)
            members = set(self.preview_boxes)
        ui.text(out, "DeskBand", 28, 22, 22, 0.9, "Semibold")
        if self.state == PREVIEW:
            ui.text(out, "put things on the desk, then shoot", 28, 52, 15, 0.5, "Light")
        self.draw_card(out, members)
        self.draw_shutter(out)
        if self.flash > 0.01:
            f = self.flash * 0.85
            out[:] = np.clip(out * (1 - f) + 255 * f, 0, 255).astype(np.uint8)
            self.flash *= math.exp(-dt / 0.10)
        if self.debug:
            self.draw_debug(out)
        return out

    def draw_debug(self, out):
        e, v = self.engine, self.vision
        lines = [
            f"display {self.disp_fps:4.1f} fps   vision {v.fps:4.1f} fps / {v.infer_ms:3.0f} ms   audio {e.cpu * 100:3.0f}%",
            f"chord {self.composer.chord_name}   step {e.step % C.STEPS_PER_PHRASE:2d}   phrase {e.step // C.STEPS_PER_PHRASE}",
            "  ".join(f"{d.name} {d.conf:.2f}" for d in self.vision.snapshot()[1]) or "no detections",
            "  ".join(f"{n}:{p.gain:.2f}" for n, p in e.parts.items() if p.gain > 0.01),
            "loaded: " + ", ".join(sorted(e.loaded)),
        ]
        y = 90
        for s in lines:
            ui.text(out, s, 28, y, 13, 0.75, "Regular")
            y += 20

    # -------------------------------------------------------------- loop
    def run(self):
        self.engine.start()
        self.vision.start()
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        try:
            while True:
                t0 = time.time()
                dt = min(max(t0 - self.t_prev, 1e-3), 0.1)
                self.t_prev = t0
                self.disp_fps = 0.9 * self.disp_fps + 0.1 / dt
                cv2.imshow(WINDOW, self.render(dt))
                wait = max(1, int(33 - (time.time() - t0) * 1000))
                k = cv2.waitKey(wait) & 0xFF
                if k in (ord("q"), 27):
                    break
                elif k == ord(" "):
                    self.toggle()
                elif k == ord("d"):
                    self.debug = not self.debug
                elif k == ord("f"):
                    self.fullscreen = not self.fullscreen
                    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN if self.fullscreen else cv2.WINDOW_NORMAL)
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            self.vision.stop()
            self.engine.stop()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    App().run()
