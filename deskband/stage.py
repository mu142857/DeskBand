"""The stage (tab): the band laid out by hand on a plane.

Up is loudness, across is complexity (config.STAGE_DB, config.STAGE_AS_WRITTEN,
music.Pattern.arrange). Being on the stage is being in the band: drag a
thumbnail from the shelf into it to bring that instrument in, drag its token
out again (or right-click it) to take it out. Where each one stands is kept on
the shelf (Entry.pos), so it comes back to the same place, after a restart too.
Loudness follows the hand at once; complexity is heard from the next bar line.
In math mode the grid gives way to a golden-angle field and every computed
part wears a ring of the bar's 16ths with its onsets joined up, both from the
bar line where math mode is first heard.
Drawing only; the App owns the shelf, the band and the buttons."""

import math
import time

import cv2
import numpy as np

from . import config as C
from . import ui

DRAG_PX = 5                  # a press that moves less than this is a click
# Where an instrument lands when it joins without being dragged in (a photo, a
# click on the shelf, a number key): along the middle line, as-written first.
HOME_X = (0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74, 0.18, 0.82)
RING_GAP = 10                # math mode's ring of 16ths sits this far outside a token
FIELD_GAP = 10               # spacing of the golden-angle field (px per sqrt(seed))


def loudness_db(y):
    """0..1 up the plane -> dB on the part's own level: 0 dB in the middle,
    config.STAGE_DB at the bottom and top edges."""
    lo, hi = C.STAGE_DB
    return 2 * (y - 0.5) * (hi if y >= 0.5 else -lo)


def loudness_gain(y):
    return 10 ** (loudness_db(y) / 20)


def complexity_word(x):
    lo, hi = C.STAGE_AS_WRITTEN
    return "pared down" if x < lo else "embellished" if x > hi else "as written"


class Stage:
    def __init__(self, app, x0, y0, x1, y1):
        self.app = app
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.size = app.tile_mask.shape[0]            # tokens are the shelf's tinted tiles, cut round
        self.mask = ui.rounded_mask(self.size, self.size, self.size // 2).astype(np.float32) / 255.0
        self.bg = self.bg_math = None                 # the empty plane, drawn once for each mode
        self.drag = None
        self.mix = 0.0                                # 0 patterned .. 1 math, eased
        self.t_prev = None
        self.bar = (None, 0.0)                        # (BarView heard now, 0..1 through it)

    # ------------------------------------------------------------ geometry
    def to_screen(self, pos):
        return (self.x0 + pos[0] * (self.x1 - self.x0), self.y1 - pos[1] * (self.y1 - self.y0))

    def to_plane(self, x, y):
        return (min(max((x - self.x0) / (self.x1 - self.x0), 0.0), 1.0),
                min(max((self.y1 - y) / (self.y1 - self.y0), 0.0), 1.0))

    def droppable(self, x, y):
        """A token centred here stays in (pinned to the edge if just over it)."""
        r = self.size / 2
        return self.x0 - r <= x <= self.x1 + r and self.y0 - r <= y <= self.y1 + r

    def placed(self):
        """The band's saved instruments, shelf order: the tokens on the plane."""
        shelf = self.app.shelf
        return [n for n in shelf.order() if n in self.app.band and shelf.entries[n].pos]

    def token_at(self, x, y):
        r2 = (self.size / 2) ** 2
        for name in reversed(self.placed()):                    # the one drawn on top first
            cx, cy = self.to_screen(self.app.shelf.entries[name].pos)
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                return name
        return None

    # ------------------------------------------------------------ the mix
    def settle(self):
        """Give every instrument in the band that has never been placed a spot."""
        shelf = self.app.shelf
        for name in shelf.order():
            if name in self.app.band and shelf.entries[name].pos is None:
                taken = [shelf.entries[n].pos for n in self.placed()]
                x = next((x for x in HOME_X if all(abs(x - p[0]) > 0.06 or abs(p[1] - 0.5) > 0.1
                                                   for p in taken)), 0.5)
                shelf.place(name, (x, 0.5))

    def apply(self, names=None):
        """Placements -> the engine's loudness trims and the composer's complexity."""
        for name in names or C.INSTRUMENTS:
            entry = self.app.shelf.entries.get(name)
            x, y = entry.pos if entry and entry.pos else (0.5, 0.5)
            self.app.engine.set_trim(name, loudness_gain(y))
            self.app.composer.set_complexity(name, x)

    def place(self, name, complexity=None, loudness=None):
        """Move a saved instrument (the remote port's "place"); None keeps that axis."""
        entry = self.app.shelf.entries.get(name)
        if entry is None:
            return
        x, y = entry.pos or (0.5, 0.5)
        self.app.shelf.place(name, (x if complexity is None else complexity,
                                    y if loudness is None else loudness))
        self.apply([name])

    # ------------------------------------------------------------ mouse
    def on_mouse(self, event, x, y):
        """-> True when the event was the stage's (a token, or a shelf tile being dragged)."""
        app = self.app
        if event == cv2.EVENT_LBUTTONDOWN:
            name, dock = self.token_at(x, y), False
            if name:
                cx, cy = self.to_screen(app.shelf.entries[name].pos)
            else:                                        # a shelf tile: lifted as a token under the pointer
                name, dock = app.slot_at(x, y), True
                if not name:
                    return False
                cx, cy = x, y
            self.drag = dict(name=name, dock=dock, start=(x, y), grab=(cx - x, cy - y), moved=False)
            return True
        if event == cv2.EVENT_RBUTTONDOWN and self.token_at(x, y):
            app.select(self.token_at(x, y), False)
            return True
        d = self.drag
        if d is None or event not in (cv2.EVENT_MOUSEMOVE, cv2.EVENT_LBUTTONUP):
            return False
        if d["name"] not in app.shelf.entries:           # forgotten mid-drag
            self.drag = None
            return True
        d["moved"] = d["moved"] or math.hypot(x - d["start"][0], y - d["start"][1]) > DRAG_PX
        cx, cy = x + d["grab"][0], y + d["grab"][1]
        inside = self.droppable(cx, cy)
        if event == cv2.EVENT_MOUSEMOVE:
            if d["moved"] and inside and not d["dock"]:    # heard while it moves
                app.shelf.place(d["name"], self.to_plane(cx, cy), save=False)
                self.apply([d["name"]])
            return True
        self.drag = None
        if not d["moved"]:
            if d["dock"]:                                # a click on the shelf, as in the camera view
                app.select(d["name"])
        elif inside:
            app.shelf.place(d["name"], self.to_plane(cx, cy))
            app.select(d["name"], True)
            self.apply([d["name"]])
        elif not d["dock"]:                              # dragged off the stage: out of the band
            app.shelf.place(d["name"], app.shelf.entries[d["name"]].pos)     # remember where it was
            app.select(d["name"], False)
        return True

    # ------------------------------------------------------------ drawing
    def field(self):
        """Golden-angle dots over the plane, packed as a sunflower packs its seeds
        (seed i at radius sqrt(i), turned 2π/φ² from the last): math mode's
        backdrop. -> float mask the size of the plane."""
        w, h = self.x1 - self.x0, self.y1 - self.y0
        m = np.zeros((h, w), np.uint8)
        turn = math.pi * (3 - 5 ** 0.5)
        reach = math.hypot(w, h) / 2
        for i in range(1, int((reach / FIELD_GAP) ** 2)):
            r = FIELD_GAP * math.sqrt(i)
            x, y = w / 2 + r * math.cos(i * turn), h / 2 + r * math.sin(i * turn)
            if 6 < x < w - 6 and 6 < y < h - 6:          # a little larger towards the middle
                cv2.circle(m, (round(16 * x), round(16 * y)), round(16 * (1.5 - 0.6 * r / reach)),
                           255, -1, cv2.LINE_AA, shift=4)
        return m.astype(np.float32) / 255.0

    def backdrop(self, W, H, math_mode=False):
        base = np.empty((H, W, 3), np.uint8)
        base[:] = np.clip(ui.TONE_DARK * 1.3, 0, 255).astype(np.uint8)
        out = cv2.multiply(base, self.app.base.vignette, scale=1 / 255.0)
        x0, y0, x1, y1 = self.x0, self.y0, self.x1, self.y1
        lo, hi = C.STAGE_AS_WRITTEN
        a, b = int(x0 + lo * (x1 - x0)), int(x0 + hi * (x1 - x0))
        ui._blend(out, np.ones((y1 - y0, b - a), np.float32), ui.WHITE, 0.025, a, y0)   # the as-written band
        if math_mode:
            ui._blend(out, self.field(), ui.WHITE, 0.12, x0, y0)
        else:
            minor = np.zeros((H, W), np.float32)
            major = np.zeros((H, W), np.float32)
            for f in (0.25, 0.5, 0.75):
                layer = major if f == 0.5 else minor
                x, y = int(x0 + f * (x1 - x0)), int(y1 - f * (y1 - y0))
                cv2.line(layer, (x, y0 + 1), (x, y1 - 1), 1.0, 1)
                cv2.line(layer, (x0 + 1, y), (x1 - 1, y), 1.0, 1)
            ui._blend(out, minor, ui.WHITE, 0.05, 0, 0)
            ui._blend(out, major, ui.WHITE, 0.10, 0, 0)
        ui.outline(out, x0, y0, x1, y1, 16, 0.2)
        ui.text(out, "as computed" if math_mode else "as written", (a + b) / 2, y1 - 20, 12, 0.3, "Light",
                align="center")
        lo_db, hi_db = C.STAGE_DB
        for f, s in ((1.0, f"{hi_db:+.0f} dB"), (0.5, "0 dB"), (0.0, f"{lo_db:+.0f} dB".replace("-", "−"))):
            ui.text(out, s, x0 + 10, y1 - f * (y1 - y0) + (6 if f == 1.0 else -20 if f == 0.0 else -18),
                    12, 0.3, "Light")
        mid = (y0 + y1) / 2
        ui.text(out, "louder", x0 - 16, y0, 14, 0.55, "Light", align="right")
        ui.text(out, "loudness", x0 - 16, mid - 9, 14, 0.8, "Regular", align="right")
        ui.text(out, "quieter", x0 - 16, y1 - 16, 14, 0.55, "Light", align="right")
        ui.text(out, "← simpler", x0, y1 + 14, 14, 0.55, "Light")
        ui.text(out, "complexity", (x0 + x1) / 2, y1 + 14, 14, 0.8, "Regular", align="center")
        ui.text(out, "more complex →", x1, y1 + 14, 14, 0.55, "Light", align="right")
        return out

    def tile(self, name):
        entry = self.app.shelf.entries[name]
        if entry.tile is None:                            # same tile as the shelf draws
            small = cv2.resize(entry.thumb, (self.size, self.size), interpolation=cv2.INTER_AREA)
            entry.tile = ui.tint(small, C.INSTRUMENTS[name]["tint"])
        return entry.tile

    def draw_ring(self, out, name, cx, cy, alpha):
        """Round a part math mode computes: the bar's 16ths clockwise from the
        top, the steps it plays lit in its colour and joined up (a Euclidean
        rhythm is a regular-ish polygon on this circle, turned), and a hand at
        the step being heard. The shape changes every bar."""
        view, phase = self.bar
        onsets = view.onsets.get(name, ()) if view else ()
        n = C.STEPS_PER_PHRASE
        R = self.size // 2 + RING_GAP
        pad = R + 8

        def at(turns, radius=R):                       # -> 1/16 px fixed point, for shift=4
            return (round(16 * (pad + radius * math.sin(2 * math.pi * turns))),
                    round(16 * (pad - radius * math.cos(2 * math.pi * turns))))

        white = np.zeros((2 * pad + 1, 2 * pad + 1), np.uint8)
        colour = white.copy()
        for s in range(n):
            if s not in onsets:
                cv2.circle(white, at(s / n), 22, 70, -1, cv2.LINE_AA, shift=4)
        if len(onsets) > 1:
            cv2.polylines(colour, [np.array([at(s / n) for s in onsets], np.int32)], True, 130, 1,
                          cv2.LINE_AA, shift=4)
        for s in onsets:
            cv2.circle(colour, at(s / n), 48, 255, -1, cv2.LINE_AA, shift=4)
        cv2.line(white, at(phase, R - 6), at(phase, R + 6), 190, 1, cv2.LINE_AA, shift=4)
        c = ui.hex_bgr(C.INSTRUMENTS[name]["tint"])
        x, y = int(cx) - pad, int(cy) - pad
        ui._blend(out, white.astype(np.float32) / 255.0, ui.WHITE, alpha, x, y)
        ui._blend(out, colour.astype(np.float32) / 255.0, c + (255 - c) * 0.25, alpha, x, y)

    def draw_token(self, out, name, cx, cy, alpha=1.0, readout=False, note=None):
        r = self.size // 2
        g = self.app.glow(name)
        entry = self.app.shelf.entries[name]
        ring = self.mix * alpha if name in self.app.composer.computed else 0.0
        if ring > 0.01:
            self.draw_ring(out, name, cx, cy, ring)
        ui.picture(out, self.tile(name), self.mask, int(cx) - r, int(cy) - r, alpha)
        ui.circle(out, cx, cy, r, alpha * (0.45 + 0.55 * g), thickness=1)
        if g > 0.02:                                       # a ring that swells out on every note
            ui.circle(out, cx, cy, r + 3 + 9 * (1 - g), alpha * 0.5 * g, thickness=1)
        if note is None and readout and entry.pos:
            x, y = entry.pos
            note = f"{loudness_db(y):+.0f} dB  ·  {complexity_word(x)}".replace("-", "−")
        W = out.shape[1]
        for s, dy, size, a, weight in ((entry.shown, 8, 14, 0.9, "Medium"), (note, 28, 12, 0.6, "Light")):
            if s:                                          # kept whole inside the window
                half = ui.text_mask(s, size, weight)[0].shape[1] / 2
                ui.text(out, s, min(max(cx, half + 8), W - half - 8), cy + r + dy + int(12 * ring),
                        size, alpha * a, weight, align="center")

    def draw_guides(self, out, cx, cy):
        """Faint lines from a token being dragged to the two axes."""
        r = self.size // 2
        cx, cy = int(min(max(cx, self.x0), self.x1)), int(min(max(cy, self.y0), self.y1))
        if cy + r < self.y1:
            ui._blend(out, np.ones((self.y1 - cy - r, 1), np.float32), ui.WHITE, 0.15, cx, cy + r)
        if cx - r > self.x0:
            ui._blend(out, np.ones((1, cx - r - self.x0), np.float32), ui.WHITE, 0.15, self.x0, cy)

    def draw_beat(self, out):
        """Where the shutter sits in the camera view: a light on the beat and the chord."""
        app, e = self.app, self.app.engine
        cx, cy, r = app.shutter
        beat = e.step_len * C.STEPS_PER_BEAT
        phase = ((e.pos - e.latency * C.SAMPLE_RATE) % beat) / beat
        ui.circle(out, cx, cy, r, 0.3, thickness=1)
        ui.circle(out, cx, cy, r - 7, 0.06 + (0.45 * math.exp(-5 * phase) if app.on else 0.0), thickness=-1)
        ui.text(out, app.composer.chord_name, cx, cy + r + 10, 13, 0.55, "Light", align="center")

    def render(self):
        app, e = self.app, self.app.engine
        W, H = app.base.W, app.base.H
        now = time.time()
        dt, self.t_prev = (now - self.t_prev if self.t_prev else 1.0), now
        into, view = e.bar_now()                          # the bar being heard, not the one being planned
        self.bar = (view, min(into * C.SAMPLE_RATE / (e.step_len * C.STEPS_PER_PHRASE), 0.999))
        self.mix = ui.ease(self.mix, 1.0 if view and view.math else 0.0, dt, 0.25)
        if self.bg is None:
            self.bg, self.bg_math = self.backdrop(W, H), self.backdrop(W, H, math_mode=True)
        m = self.mix
        out = (self.bg.copy() if m < 0.01 else self.bg_math.copy() if m > 0.99
               else cv2.addWeighted(self.bg, 1 - m, self.bg_math, m, 0))
        pulse = math.exp(-into / 0.18) if view and app.on else 0.0
        if pulse > 0.02:                                  # the plane's edge lights on each downbeat
            ui.outline(out, self.x0, self.y0, self.x1, self.y1, 16, 0.35 * pulse)
        ui.text(out, "DeskBand", 28, 22, 22, 0.9, "Semibold")
        ui.text(out, "drag instruments in from the shelf  ·  up is louder, right is busier",
                28, 52, 15, 0.5, "Light")
        d = self.drag
        if d and d["name"] not in app.shelf.entries:
            d = self.drag = None
        dragging = d["name"] if d and d["moved"] else None
        placed = self.placed()
        if not app.shelf.entries:
            ui.text(out, "nothing on the shelf yet  ·  tab back to the camera and shoot an object",
                    (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2 - 10, 16, 0.5, "Light", align="center")
        elif not placed and not dragging:
            ui.text(out, "drag an instrument here from the shelf", (self.x0 + self.x1) / 2,
                    (self.y0 + self.y1) / 2 - 10, 16, 0.5, "Light", align="center")
        hover = self.token_at(*app.mouse) if not d else None
        for name in placed:
            if name != dragging:
                self.draw_token(out, name, *self.to_screen(app.shelf.entries[name].pos), readout=name == hover)
        app.draw_dock(out)
        if dragging:
            x, y = app.mouse
            cx, cy = x + d["grab"][0], y + d["grab"][1]
            if self.droppable(cx, cy):
                pos = self.to_plane(cx, cy)
                sx, sy = self.to_screen(pos)
                self.draw_guides(out, sx, sy)
                note = f"{loudness_db(pos[1]):+.0f} dB  ·  {complexity_word(pos[0])}".replace("-", "−")
                self.draw_token(out, dragging, sx, sy, note=note)
            else:
                self.draw_token(out, dragging, cx, cy, 0.45,
                                note="" if d["dock"] else "release to take it out")
        app.draw_view_button(out)
        app.draw_play_button(out)
        self.draw_beat(out)
        return out
