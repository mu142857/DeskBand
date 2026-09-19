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
from deskband.remote import Remote
from deskband.shelf import Shelf
from deskband.synth import Engine
from deskband.vision import Vision, merge_duplicates, open_camera

WINDOW = "DeskBand"
W, H = 1280, 720
PREVIEW, SHOW = "preview", "show"
TILE, TILE_GAP, TILE_R = 72, 12, 14            # shelf slots, down the right edge


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
        self.manual = {}                # part -> True/False, forced from the remote port
        self.shelf = Shelf(C.SHELF_DIR, C.INSTRUMENTS)   # saved instruments; the selected ones are the band
        self.on = set()                 # parts playing now
        self.slots = list(C.INSTRUMENTS)
        self.dock_x = W - 28 - TILE
        self.dock_y = (H - (len(self.slots) * (TILE + TILE_GAP) - TILE_GAP)) // 2
        self.tile_mask = ui.rounded_mask(TILE, TILE, TILE_R).astype(np.float32) / 255.0
        self.remote = Remote(self.state_dict)

    # ------------------------------------------------------------ actions
    def shoot(self):
        frame, dets = self.vision.snapshot()
        if frame is None:
            return
        if self.vision.model is not None:                  # one careful look at the frozen frame
            dets = merge_duplicates(dets + self.vision.detect(frame, C.SHOOT_IMGSZ))
        names = {d.name for d in dets}
        for name, d in self.vision.recent(0.5).items():   # smooth over flicker
            if name not in names:
                dets.append(d)
                names.add(name)
        self.captured = (frame.copy(), dets)
        self.save_frame(frame, "shot")
        self.state = SHOW
        self.flash = 1.0
        for d in sorted(dets, key=lambda d: d.conf):       # best box of each object last, so it wins
            if self.shelf.add(d.name, d.shown, d.conf, frame, d.box):
                self.shelf.select(d.name, True)
        self.apply_parts()

    def apply_parts(self):
        """Band = the instruments selected on the shelf, plus/minus anything forced remotely."""
        selected = self.shelf.selected()
        self.on = {n for n in C.INSTRUMENTS if self.manual.get(n, n in selected)}
        for name in C.INSTRUMENTS:
            self.engine.set_active(name, name in self.on)

    def select(self, name, on=None):
        self.shelf.select(name, on)
        self.apply_parts()

    def forget(self, name):
        self.shelf.remove(name)
        self.apply_parts()

    def silence(self):
        self.shelf.clear_selection()
        self.apply_parts()

    # ------------------------------------------------------------ remote port
    def state_dict(self):
        e = self.engine
        heard = max(0, e.pos - int(e.latency * C.SAMPLE_RATE))       # what is audible now
        step_f = heard / e.step_len
        beat_f = step_f / C.STEPS_PER_BEAT
        dets = self.captured[1] if self.captured else self.vision.snapshot()[1]
        return {
            "type": "state", "mode": self.state, "bpm": e.bpm,
            "bar": int(step_f // C.STEPS_PER_BAR), "step": int(step_f) % C.STEPS_PER_BAR,
            "beat": int(beat_f) % 4, "beat_phase": round(beat_f % 1.0, 3),
            "chord": self.composer.chord_name, "chord_index": self.composer.chord_index,
            "parts": {n: {"on": e.parts[n].target > 0, "glow": round(self.glow(n), 3)} for n in C.INSTRUMENTS},
            "detected": sorted({d.shown for d in dets}),
            "saved": [n for n in self.slots if n in self.shelf.entries],
            "selected": [n for n in self.slots if n in self.shelf.selected()],
        }

    def handle_command(self, msg):
        cmd = msg.get("cmd")
        if cmd == "shoot" and self.state == PREVIEW:
            self.shoot()
        elif cmd == "retake" and self.state == SHOW:
            self.retake()
        elif cmd == "toggle":
            self.toggle()
        elif cmd == "part" and msg.get("name") in C.INSTRUMENTS:
            if msg.get("on") is None:
                self.manual.pop(msg["name"], None)
            else:
                self.manual[msg["name"]] = bool(msg["on"])
            self.apply_parts()
        elif cmd == "select" and msg.get("name") in C.INSTRUMENTS:
            self.select(msg["name"], msg.get("on"))
        elif cmd == "silence":
            self.silence()
        elif cmd == "sfx" and os.path.isfile(str(msg.get("file"))):
            self.engine.play_file(msg["file"], msg.get("gain", 0.6))
        elif cmd == "bpm":
            self.engine.set_bpm(msg.get("value", C.BPM))
        elif cmd == "style":
            self.composer.request_style(msg["chords"])
            if msg.get("bpm"):
                self.engine.set_bpm(msg["bpm"])
        elif cmd == "fpga_mode":
            if msg.get("bpm"):
                self.engine.set_bpm(msg["bpm"])
            self.engine.set_fpga_mode(msg.get("on", True), msg.get("lookahead_steps", 2))
        elif cmd == "fpga_event":
            self.engine.queue_fpga_event(msg["tick"], msg["step"], msg["events"], msg["active"])
        elif cmd == "fpga_controls":
            self.engine.set_fpga_controls(msg["levels"], msg["lfos"])

    def process_commands(self):
        while not self.remote.commands.empty():
            try:
                self.handle_command(self.remote.commands.get_nowait())
            except Exception as e:                     # a bad packet must never stop the show
                print("remote command failed:", repr(e), flush=True)

    def save_frame(self, frame, prefix):
        """Keep the raw picture: tools/eval_prompts.py replays these to tune detection."""
        os.makedirs(C.SHOTS_DIR, exist_ok=True)
        path = os.path.join(C.SHOTS_DIR, f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.jpg")
        cv2.imwrite(path, frame)
        print("saved", path, flush=True)

    def retake(self):
        """Back to the camera. The band keeps playing: it lives on the shelf now."""
        self.state = PREVIEW
        self.captured = None

    def toggle(self):
        if self.state == PREVIEW:
            self.shoot()
        else:
            self.retake()

    def slot_at(self, x, y):
        """Name of the shelf slot under a point, or None."""
        if not self.dock_x <= x < self.dock_x + TILE:
            return None
        i, rest = divmod(y - self.dock_y, TILE + TILE_GAP)
        return self.slots[i] if 0 <= i < len(self.slots) and rest < TILE else None

    def on_mouse(self, event, x, y, flags, param):
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            cx, cy, r = self.shutter
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 8) ** 2:
                self.toggle()
            elif self.slot_at(x, y):
                self.select(self.slot_at(x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and self.slot_at(x, y):
            self.forget(self.slot_at(x, y))

    # ------------------------------------------------------------ drawing
    def glow(self, name):
        """0..1: how recently this part played a note."""
        hit = self.engine.hits.get(name)
        if hit is None:
            return 0.0
        age = (self.engine.pos - hit) / C.SAMPLE_RATE - self.engine.latency
        if age < 0:                       # queued but not audible yet
            return 0.0
        return math.exp(-age / 0.22)

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
        adv = ui.text(out, det.shown, x0 + 2, ty, 17, alpha * 0.95, "Medium")
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

    def draw_card(self, out, desk):
        """Bottom-left frosted card: the band, then whatever else is in view."""
        rows = []
        for n in C.INSTRUMENTS:
            entry = self.shelf.entries.get(n)
            if n in self.on:
                rows.append((n, entry.shown if entry else desk.get(n, n), True))
            elif n in desk:
                rows.append((n, desk[n], False))
        x0, y0 = 28, H - 28 - (58 + 30 * max(len(rows), 1))
        x1 = x0 + 320
        ui.frosted(out, x0, y0, x1, H - 28)
        ui.text(out, "Band", x0 + 20, y0 + 16, 20, 0.95, "Semibold")
        ui.text(out, self.composer.chord_name, x1 - 20, y0 + 20, 15, 0.55, "Light", align="right")
        y = y0 + 54
        if not rows:
            ui.text(out, "nothing yet", x0 + 20, y, 16, 0.5, "Light")
        for name, shown, playing in rows:
            if playing:
                ui.circle(out, x0 + 26, y + 10, 4, 0.35 + 0.65 * self.glow(name), thickness=-1)
            else:
                ui.circle(out, x0 + 26, y + 10, 4, 0.35, thickness=1)
            dim = 1.0 if playing else 0.55
            ui.text(out, shown, x0 + 42, y, 16, 0.9 * dim, "Regular")
            ui.text(out, C.INSTRUMENTS[name]["label"], x1 - 20, y, 16, 0.6 * dim, "Light", align="right")
            y += 30

    def draw_dock(self, out):
        """The shelf: one slot per instrument. Lit = in the band."""
        x = self.dock_x
        hover = self.slot_at(*self.mouse)
        for i, name in enumerate(self.slots):
            y = self.dock_y + i * (TILE + TILE_GAP)
            entry = self.shelf.entries.get(name)
            lift = 0.25 if name == hover else 0.0
            if entry is None:
                ui.outline(out, x, y, x + TILE, y + TILE, TILE_R, 0.14 + lift)
                ui.text(out, name, x + TILE // 2, y + TILE // 2 - 8, 12, 0.34 + lift, "Light", align="center")
                continue
            if entry.tiles is None:
                small = cv2.resize(entry.thumb, (TILE, TILE), interpolation=cv2.INTER_AREA)
                entry.tiles = (small.astype(np.float32), ui.duotone(small).astype(np.float32))
            if name in self.on:
                g = self.glow(name)
                ui.picture(out, entry.tiles[0], self.tile_mask, x, y)
                ui.outline(out, x, y, x + TILE, y + TILE, TILE_R, min(1.0, 0.45 + 0.55 * g + lift))
            else:
                ui.picture(out, entry.tiles[1], self.tile_mask, x, y, 0.5 + lift)
                ui.outline(out, x, y, x + TILE, y + TILE, TILE_R, 0.2 + lift)
        if hover:
            entry = self.shelf.entries.get(hover)
            y = self.dock_y + self.slots.index(hover) * (TILE + TILE_GAP)
            top = f"{self.slots.index(hover) + 1}  ·  {entry.shown if entry else hover}"
            sub = C.INSTRUMENTS[hover]["label"] if entry else "shoot one to add it"
            wide = max(ui.text_mask(top, 15, "Medium")[0].shape[1], ui.text_mask(sub, 13, "Light")[0].shape[1])
            ui.frosted(out, x - 38 - wide, y + 10, x - 12, y + TILE - 10, r=10)
            ui.text(out, top, x - 25, y + 18, 15, 0.95, "Medium", align="right")
            ui.text(out, sub, x - 25, y + 40, 13, 0.6, "Light", align="right")

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
                playing = d.name in self.on
                self.draw_box(out, frame, d, 1.0 if playing else 0.5, lit=playing,
                              glow=self.glow(d.name) if playing else 0.0)
            desk = {d.name: d.shown for d in sorted(dets, key=lambda d: d.conf)}
        else:
            self.draw_preview(out, frame, dets, dt)
            desk = {n: b.det.shown for n, b in self.preview_boxes.items()}
        ui.text(out, "DeskBand", 28, 22, 22, 0.9, "Semibold")
        if self.state == PREVIEW:
            ui.text(out, "shoot an object to add it to the band", 28, 52, 15, 0.5, "Light")
        self.draw_card(out, desk)
        self.draw_dock(out)
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
            f"display {self.disp_fps:4.1f} fps   camera {v.cam_fps:4.1f} fps   detector {v.model_name} {v.fps:4.1f} fps / {v.infer_ms:3.0f} ms   audio {e.cpu * 100:3.0f}%  xruns {e.xruns}",
            f"chord {self.composer.chord_name}   step {e.step % C.STEPS_PER_PHRASE:2d}   phrase {e.step // C.STEPS_PER_PHRASE}",
            "  ".join(f"{d.alias} {d.conf:.2f}" for d in self.vision.snapshot()[1]) or "no detections",
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
        self.remote.start()
        cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        camera_ok, next_try = False, 0.0
        try:
            while True:
                t0 = time.time()
                # The camera is opened here, on the main thread, so macOS can show
                # its permission prompt; keep retrying while the user answers it.
                if not camera_ok and t0 >= next_try:
                    cap = open_camera()
                    if cap is not None:
                        self.vision.cap = cap
                        self.vision.error = None
                        self.vision.start()
                        camera_ok = True
                    else:
                        self.vision.error = ("waiting for camera access  ·  allow DeskBand in "
                                             "System Settings › Privacy & Security › Camera")
                        next_try = time.time() + 1.5
                dt = min(max(t0 - self.t_prev, 1e-3), 0.1)
                self.t_prev = t0
                self.disp_fps = 0.9 * self.disp_fps + 0.1 / dt
                self.process_commands()
                cv2.imshow(WINDOW, self.render(dt))
                wait = max(1, int(33 - (time.time() - t0) * 1000))
                k = cv2.waitKey(wait) & 0xFF
                if k in (ord("q"), 27):
                    break
                elif k == ord(" "):
                    self.toggle()
                elif k == ord("d"):
                    self.debug = not self.debug
                elif ord("1") <= k < ord("1") + len(self.slots):      # shelf slots
                    self.select(self.slots[k - ord("1")])
                elif k == ord("0"):
                    self.silence()
                elif k == ord("x") and self.slot_at(*self.mouse):
                    self.forget(self.slot_at(*self.mouse))
                elif k == ord("s"):                       # save the live frame without shooting
                    frame, _ = self.vision.snapshot()
                    if frame is not None:
                        self.save_frame(frame, "frame")
                        self.flash = 0.25
                elif k == ord("f"):
                    self.fullscreen = not self.fullscreen
                    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN if self.fullscreen else cv2.WINDOW_NORMAL)
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            self.remote.stop()
            self.vision.stop()
            self.engine.stop()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    App().run()
