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
from deskband.cloud import Describer
from deskband.arrangement import build_snapshot
from deskband.music import Composer
from deskband.remote import Remote
from deskband.shelf import Shelf
from deskband.stage import Stage
from deskband.synth import Engine
from deskband.vision import Detection, Vision, echoes, merge_duplicates, open_camera
from deskband.zybo import ZyboLink

WINDOW = "DeskBand"
W, H = 1280, 720
PREVIEW, SHOW = "preview", "show"
TILE, TILE_GAP, TILE_R = 72, 12, 14            # shelf slots, down the right edge
CAPTION_W = 520                                 # Gemini's description, top left


def fit_camera_frame(frame):
    """Fit the entire camera image in the window and return its box transform."""
    raw_h, raw_w = frame.shape[:2]
    scale = min(W / raw_w, H / raw_h)
    width, height = round(raw_w * scale), round(raw_h * scale)
    left, top = (W - width) // 2, (H - height) // 2
    canvas = np.empty((H, W, 3), np.uint8)
    canvas[:] = ui.TONE_DARK.astype(np.uint8)
    canvas[top:top + height, left:left + width] = cv2.resize(frame, (width, height))
    return canvas, width / raw_w, height / raw_h, left, top


class Box:
    """The single smoothed on-screen target in preview mode."""

    def __init__(self, det):
        self.xyxy = np.array(det.box, np.float32)
        self.alpha = 0.0
        self.seen = time.time()
        self.det = det


class App:
    def __init__(self):
        self.shelf = Shelf(C.SHELF_DIR, C.INSTRUMENTS)   # saved slots; each capture rerolls its motif
        self.composer = Composer(motif_seeds={n: e.motif_seed for n, e in self.shelf.entries.items()})
        self.engine = Engine(self.composer)
        self.vision = Vision()
        self.base = ui.Base(W, H)
        self.state = PREVIEW
        self.captured = None            # (frame, [Detection]) once shot
        self.preview_box = None         # one visible target, even while detections change
        self.flash = 0.0
        self.debug = False
        self.fullscreen = False
        self.mouse = (-1, -1)
        self.shutter = (W // 2, H - 64, 26)
        self.play_button = (W // 2 + 84, H - 64, 19)
        self.math_button = (W // 2 - 84, H - 64, 19)
        self.view_button = (W // 2 - 168, H - 64, 19)   # camera <-> stage
        self.on_stage = False
        self.playing = True             # the master switch beside the shutter
        self.t_prev = time.time()
        self.disp_fps = 0.0
        self.manual = {}                # part -> True/False, forced from the remote port
        self.band = set()               # parts switched on
        self.on = set()                 # parts sounding now: the band, unless paused
        self.dock_x = W - 28 - TILE
        self.dock_y = 28                # eight slots fit above the bottom margin
        self.tile_mask = ui.rounded_mask(TILE, TILE, TILE_R).astype(np.float32) / 255.0
        self.stage = Stage(self, 132, 100, self.dock_x - 56, H - 136)   # the plane: loudness x complexity
        self.fpga_bar = None            # live hardware composition telemetry
        self.remote = Remote(self.state_dict)
        self.describer = Describer()    # Gemini's description of the current photo (display only)
        self.caption = (None, [])       # (text, wrapped lines)
        self.zybo = ZyboLink(on_lost=lambda: self.remote.commands.put({"cmd": "fpga_mode", "on": False}))
        self.apply_parts()              # restore the saved selection before audio starts

    # ------------------------------------------------------------ actions
    def shoot(self):
        frame, dets = self.vision.snapshot()
        if frame is None:
            return
        if self.vision.model is not None:                  # one careful look at the frozen frame
            dets = self.vision.careful(frame)
        names = {d.name for d in dets}
        flicker = [d for n, d in self.vision.recent(0.5).items()                      # smooth over dropouts...
                   if n not in names and d.conf >= C.DETECT_SURE and not echoes(d, dets)]
        dets = merge_duplicates(dets + flicker)       # ...without letting one object in under two names
        dets = self.pick(dets)
        self.captured = (frame.copy(), dets)
        self.save_frame(frame, "shot")
        self.describer.request(frame)
        self.state = SHOW
        self.flash = 1.0
        for d in sorted(dets, key=lambda d: d.conf):       # best box of each object last, so it wins
            if entry := self.shelf.add(d.name, d.shown, d.conf, frame, d.box):
                self.composer.set_motif_seed(d.name, entry.motif_seed)
                self.shelf.select(d.name, True)
        self.apply_parts()

    def pick(self, dets):
        """Choose one object, keeping the current target when it is still plausible.

        An unseen shelf class wins first; otherwise confidence decides. A small
        confidence margin prevents the outline from jumping between similar
        detections on successive camera inference passes.
        """
        if not dets:
            return []
        best = max(dets, key=lambda d: (d.name not in self.shelf.entries, d.conf))
        current = self.preview_box
        if current is not None and time.time() - current.seen < 0.5:
            same = [d for d in dets if d.name == current.det.name]
            if same and ((current.det.name not in self.shelf.entries) ==
                         (best.name not in self.shelf.entries)):
                near = min(same, key=lambda d: np.sum((np.asarray(d.box, np.float32) - current.xyxy) ** 2))
                if near.conf + 0.12 >= best.conf:
                    best = near
        return [best]

    def apply_parts(self):
        """Band = the instruments selected on the shelf, plus/minus anything forced remotely."""
        selected = self.shelf.selected()
        self.band = {n for n in C.INSTRUMENTS if self.manual.get(n, n in selected)}
        self.on = self.band if self.playing else set()
        self.stage.settle()                     # newcomers get a spot on the stage...
        self.stage.apply()                      # ...and every spot sets a loudness and a complexity
        for name in C.INSTRUMENTS:
            self.engine.set_active(name, name in self.on)

    def play(self, on=None):
        """The master switch: pausing silences the band but keeps the selection."""
        self.playing = (not self.playing) if on is None else bool(on)
        self.apply_parts()

    def math_mode(self, on=None):
        """Math mode for the melodic parts (music.Sequence); heard from the next bar."""
        self.composer.set_math(on)

    def show_stage(self, on=None):
        """Camera view <-> the stage (None flips). The band plays on either way."""
        self.on_stage = (not self.on_stage) if on is None else bool(on)
        self.stage.drag = None

    def select(self, name, on=None):
        self.shelf.select(name, on)
        self.apply_parts()

    def forget(self, name):
        self.shelf.remove(name)
        self.apply_parts()

    def silence(self):
        self.shelf.clear_selection()
        self.apply_parts()

    def arrangement_snapshot(self):
        """A complete next-cycle score for the ending screen and exporter."""
        return build_snapshot(self.shelf, self.composer, self.engine)

    # ------------------------------------------------------------ remote port
    def state_dict(self):
        e = self.engine
        heard = max(0, e.pos - int(e.latency * C.SAMPLE_RATE))       # what is audible now
        step_f = heard / e.step_len
        beat_f = step_f / C.STEPS_PER_BEAT
        dets = self.captured[1] if self.captured else self.pick(self.vision.snapshot()[1])
        return {
            "type": "state", "mode": self.state, "bpm": e.bpm,
            "bar": int(step_f // C.STEPS_PER_BAR), "step": int(step_f) % C.STEPS_PER_BAR,
            "beat": int(beat_f) % 4, "beat_phase": round(beat_f % 1.0, 3),
            "chord": self.composer.chord_name, "chord_index": self.composer.chord_index,
            "parts": {n: {"on": e.parts[n].target > 0, "glow": round(self.glow(n), 3)} for n in C.INSTRUMENTS},
            "detected": sorted({d.shown for d in dets}),
            "playing": self.playing,
            "math": self.composer.math,
            "description": self.describer.text if self.describer.status == "done" else None,
            "saved": self.shelf.order(),                                    # top of the shelf first
            "selected": [n for n in self.shelf.order() if self.shelf.entries[n].selected],
            "view": "stage" if self.on_stage else "camera",
            "placed": {n: {"complexity": round(e.pos[0], 3), "loudness": round(e.pos[1], 3)}
                       for n, e in self.shelf.entries.items() if e.pos},
            "fpga": self.fpga_bar,
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
        elif cmd == "play":
            self.play(msg.get("on"))
        elif cmd == "math":
            self.math_mode(msg.get("on"))
        elif cmd == "place" and msg.get("name") in self.shelf.entries:
            self.stage.place(msg["name"], msg.get("complexity"), msg.get("loudness"))
        elif cmd == "view":
            self.show_stage(msg.get("stage"))
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
            enabled = msg.get("on", True)
            self.engine.set_fpga_mode(enabled, msg.get("lookahead_steps", 2))
            if not enabled:
                self.fpga_bar = None
        elif cmd == "fpga_event":
            self.engine.queue_fpga_event(msg["tick"], msg["step"], msg["events"], msg["active"])
        elif cmd == "fpga_controls":
            self.engine.set_fpga_controls(msg["levels"], msg["lfos"])
        elif cmd == "fpga_bar":
            self.fpga_bar = {
                "bar": int(msg.get("bar", 0)),
                "energy": min(max(int(msg.get("energy", 1)), 0), 2),
                "locks": int(msg.get("locks", 0)) & 0x7f,
                "fill": bool(msg.get("fill")),
                "fill_queued": bool(msg.get("fill_queued")),
                "enabled": bool(msg.get("enabled", True)),
                "random": int(msg.get("random", 0)) & 0xffff,
            }

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
        self.preview_box = None
        self.describer.clear()

    def toggle(self):
        if self.on_stage:                       # space bar on the stage: back to the camera
            self.show_stage(False)
        elif self.state == PREVIEW:
            self.shoot()
        else:
            self.retake()

    def slot_at(self, x, y):
        """Name of the shelf slot under a point, or None."""
        if not self.dock_x <= x < self.dock_x + TILE:
            return None
        i, rest = divmod(y - self.dock_y, TILE + TILE_GAP)
        slots = self.shelf.order()
        return slots[i] if 0 <= i < len(slots) and rest < TILE else None

    def over(self, button, x, y):
        cx, cy, r = button
        return (x - cx) ** 2 + (y - cy) ** 2 <= (r + 8) ** 2

    def on_mouse(self, event, x, y, flags, param):
        self.mouse = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN and self.over(self.view_button, x, y):
            self.show_stage()
        elif self.on_stage and self.stage.on_mouse(event, x, y):
            pass                                # a token, or a shelf tile being dragged in
        elif event == cv2.EVENT_LBUTTONDOWN:
            if self.over(self.shutter, x, y) and not self.on_stage:
                self.toggle()
            elif self.over(self.play_button, x, y):
                self.play()
            elif self.over(self.math_button, x, y):
                self.math_mode()
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
        ui.outline(out, x0, y0, x1, y1, r, alpha * (0.85 + 0.15 * glow), thickness=2)
        spec = C.INSTRUMENTS[det.name]
        ty = y0 - 26 if y0 > 34 else y1 + 8
        adv = ui.text(out, det.shown, x0 + 2, ty, 17, alpha * 0.95, "Medium")
        ui.text(out, "  ·  " + spec["label"], x0 + 2 + adv, ty, 17, alpha * 0.7, "Light")

    def draw_preview(self, out, frame, dets, dt, scale_x=1.0, scale_y=1.0,
                     offset_x=0, offset_y=0):
        now = time.time()
        chosen = self.pick(dets)
        if chosen:
            d = chosen[0]
            if self.preview_box is None or self.preview_box.det.name != d.name:
                self.preview_box = Box(d)
            b = self.preview_box
            b.xyxy = ui.ease(b.xyxy, np.asarray(d.box, np.float32), dt, 0.18)
            b.seen = now
            b.det = d
        b = self.preview_box
        if b is None:
            return {}
        visible = now - b.seen < 0.4
        b.alpha = ui.ease(b.alpha, 1.0 if visible else 0.0, dt, 0.15)
        if b.alpha < 0.02 and not visible:
            self.preview_box = None
            return {}
        box = [int(round(v * (scale_x if i % 2 == 0 else scale_y) +
                         (offset_x if i % 2 == 0 else offset_y)))
               for i, v in enumerate(b.xyxy)]
        visual = Detection(b.det.name, b.det.conf, box, b.det.alias)
        self.draw_box(out, frame, visual, 0.98 * b.alpha, lit=False, glow=0.0)
        return {b.det.name: b.det.shown}

    def draw_card(self, out, desk):
        """Bottom-left frosted card: the band, then whatever else is in view."""
        rows = []
        for n in C.INSTRUMENTS:
            entry = self.shelf.entries.get(n)
            if n in self.band:
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
        """The shelf: what has been shot so far, first at the top. Lit = in the band."""
        x = self.dock_x
        slots = self.shelf.order()
        hover = self.slot_at(*self.mouse)
        for i, name in enumerate(slots):
            y = self.dock_y + i * (TILE + TILE_GAP)
            entry = self.shelf.entries[name]
            lift = 0.25 if name == hover else 0.0
            if entry.tile is None:                         # each instrument under its own colour filter
                small = cv2.resize(entry.thumb, (TILE, TILE), interpolation=cv2.INTER_AREA)
                entry.tile = ui.tint(small, C.INSTRUMENTS[name]["tint"])
            if name in self.band:
                g = self.glow(name)
                ui.picture(out, entry.tile, self.tile_mask, x, y)
                ui.outline(out, x, y, x + TILE, y + TILE, TILE_R, min(1.0, 0.45 + 0.55 * g + lift))
            else:
                ui.picture(out, entry.tile, self.tile_mask, x, y, 0.5 + lift)
                ui.outline(out, x, y, x + TILE, y + TILE, TILE_R, 0.2 + lift)
        if hover:
            y = self.dock_y + slots.index(hover) * (TILE + TILE_GAP)
            top = f"{slots.index(hover) + 1}  ·  {self.shelf.entries[hover].shown}"
            sub = C.INSTRUMENTS[hover]["label"]
            wide = max(ui.text_mask(top, 15, "Medium")[0].shape[1], ui.text_mask(sub, 13, "Light")[0].shape[1])
            ui.frosted(out, x - 38 - wide, y + 10, x - 12, y + TILE - 10, r=10)
            ui.text(out, top, x - 25, y + 18, 15, 0.95, "Medium", align="right")
            ui.text(out, sub, x - 25, y + 40, 13, 0.6, "Light", align="right")

    def draw_play_button(self, out):
        """Beside the shutter: pause bars while the band plays, a triangle while it rests."""
        cx, cy, r = self.play_button
        hover = self.over(self.play_button, *self.mouse)
        a = 0.95 if hover else 0.75
        ui.circle(out, cx, cy, r, a - 0.15, thickness=1)
        if self.playing:
            for dx in (-6, 2):
                ui._blend(out, np.ones((14, 4), np.float32), ui.WHITE, a, cx + dx, cy - 7)
        else:
            ui.polygon(out, [(cx - 5, cy - 8), (cx - 5, cy + 8), (cx + 8, cy)], a)
        ui.text(out, "p  ·  pause" if self.playing else "p  ·  play", cx, cy + self.shutter[2] + 10,
                13, 0.55, "Light", align="center")

    def draw_math_button(self, out):
        """Left of the shutter: math mode, lit while it is on."""
        cx, cy, r = self.math_button
        a = 0.95 if self.over(self.math_button, *self.mouse) else 0.75
        on = self.composer.math
        ui.circle(out, cx, cy, r, a if on else a - 0.15, thickness=-1 if on else 1)
        mask, _, top = ui.text_mask("φ", 20)
        ui.text(out, "φ", cx, cy - top - mask.shape[0] / 2, 20, a, color=ui.TONE_DARK if on else ui.WHITE,
                align="center")
        ui.text(out, "m  ·  math", cx, cy + self.shutter[2] + 10, 13, 0.55, "Light", align="center")

    def draw_view_button(self, out):
        """Far left of the row: to the stage (a plot with dots), or back to the camera."""
        cx, cy, r = self.view_button
        a = 0.95 if self.over(self.view_button, *self.mouse) else 0.75
        ui.circle(out, cx, cy, r, a - 0.15, thickness=1)
        if self.on_stage:                       # a camera
            ui.outline(out, cx - 9, cy - 6, cx + 10, cy + 8, 3, a)
            ui._blend(out, np.ones((2, 6), np.float32), ui.WHITE, a, cx - 3, cy - 8)
            ui.circle(out, cx + 0.5, cy + 1, 3, a, thickness=1)
        else:                                   # two axes and three dots
            ui._blend(out, np.ones((15, 1), np.float32), ui.WHITE, a, cx - 7, cy - 8)
            ui._blend(out, np.ones((1, 16), np.float32), ui.WHITE, a, cx - 7, cy + 7)
            for dx, dy in ((-2, 2), (2, -4), (6, 0)):
                ui.circle(out, cx + dx, cy + dy, 1.5, a, thickness=-1)
        ui.text(out, "tab  ·  camera" if self.on_stage else "tab  ·  stage", cx, cy + self.shutter[2] + 10,
                13, 0.55, "Light", align="center")

    def draw_caption(self, out):
        """Top left, under the title: what Gemini sees in the photo."""
        d = self.describer
        if d.status == "done":
            text, alpha = d.text, 0.92
        elif d.status == "looking":
            text, alpha = "Gemini is looking…", 0.55
        elif d.status == "error":
            text, alpha = "Gemini: " + d.text[:120], 0.5
        elif d.status == "off":
            text, alpha = "set GEMINI_API_KEY to have each photo described", 0.45
        else:
            return
        if self.caption[0] != text:
            self.caption = (text, ui.wrap(text, 15, CAPTION_W - 40)[:4])
        lines = self.caption[1]
        x0, y0 = 28, 58
        wide = max(ui.text_mask(line, 15)[0].shape[1] for line in lines)
        ui.frosted(out, x0, y0, x0 + wide + 40, y0 + 24 + 22 * len(lines))
        for i, line in enumerate(lines):
            ui.text(out, line, x0 + 20, y0 + 12 + 22 * i, 15, alpha, "Regular")

    def draw_shutter(self, out):
        cx, cy, r = self.shutter
        hover = self.over(self.shutter, *self.mouse)
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
        if self.on_stage:
            out = self.stage.render()
            self.draw_math_button(out)
            self.flash = 0.0                    # a photo taken from the remote port: no flash here
            if self.debug:
                self.draw_debug(out)
            return out
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
        frame, scale_x, scale_y, offset_x, offset_y = fit_camera_frame(frame)
        out = self.base.render(frame, dim=0.12 if self.state == PREVIEW else 0.0)
        if self.state == SHOW:
            for d in dets:
                playing = d.name in self.band
                box = [int(round(v * (scale_x if i % 2 == 0 else scale_y) +
                                 (offset_x if i % 2 == 0 else offset_y)))
                       for i, v in enumerate(d.box)]
                visual = Detection(d.name, d.conf, box, d.alias)
                self.draw_box(out, frame, visual, 1.0 if playing else 0.5, lit=playing,
                              glow=self.glow(d.name) if playing else 0.0)
            desk = {d.name: d.shown for d in sorted(dets, key=lambda d: d.conf)}
        else:
            desk = self.draw_preview(out, frame, dets, dt, scale_x, scale_y,
                                     offset_x, offset_y)
        ui.text(out, "DeskBand", 28, 22, 22, 0.9, "Semibold")
        if self.state == PREVIEW:
            ui.text(out, "shoot an object to add it to the band", 28, 52, 15, 0.5, "Light")
        self.draw_card(out, desk)
        self.draw_dock(out)
        self.draw_shutter(out)
        self.draw_play_button(out)
        self.draw_math_button(out)
        self.draw_view_button(out)
        if self.state == SHOW:
            self.draw_caption(out)
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
            f"zybo {self.zybo.status}   {'FPGA clock' if e.fpga_mode else 'Mac clock'}   math {'on' if self.composer.math else 'off'}   gemini {self.describer.status}",
        ]
        if self.fpga_bar is not None:
            f = self.fpga_bar
            energy = ("sparse", "normal", "full")[f["energy"]]
            lines.insert(2, f"FPGA bar {f['bar']}   generated {energy}   "
                            f"locks {f['locks']:02x}   fill "
                            f"{'active' if f['fill'] else 'queued' if f['fill_queued'] else 'off'}   "
                            f"LFSR {f['random']:04x}")
        y = 90
        for s in lines:
            ui.text(out, s, 28, y, 13, 0.75, "Regular")
            y += 20

    # -------------------------------------------------------------- loop
    def run(self):
        self.engine.start()
        self.remote.start()
        self.zybo.start()                             # the FPGA conductor, whenever it is plugged in
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
                elif k in (ord("p"), 13):                 # p or return
                    self.play()
                elif k == ord("m"):
                    self.math_mode()
                elif k == 9:                              # tab
                    self.show_stage()
                elif ord("1") <= k <= ord("9"):           # shelf slots, from the top
                    slots = self.shelf.order()
                    if k - ord("1") < len(slots):
                        self.select(slots[k - ord("1")])
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
            self.zybo.stop()
            self.remote.stop()
            self.vision.stop()
            self.engine.stop()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    App().run()
