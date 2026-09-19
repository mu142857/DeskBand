"""Collection summary UI and nonblocking job state for later export/cloud work."""

import queue
import threading

import cv2
import numpy as np

from . import config as C, ui
from .score_view import score_strip


CARD_W, CARD_H = 600, 100
CARD_X = (28, 652)
CARD_Y, CARD_GAP = 146, 10
BACK = (1076, 29, 1252, 74)
BUTTONS = {
    "render": (28, 622, 226, 672),
    "play": (240, 622, 364, 672),
    "reveal": (378, 622, 524, 672),
    "extend": (538, 622, 834, 672),
}


def duration_seconds(snapshot):
    return snapshot.bars * C.STEPS_PER_BAR / C.STEPS_PER_BEAT * 60.0 / snapshot.bpm


def card_rect(index):
    """Four rows in each of two columns, all inside the 1280x720 window."""
    x = CARD_X[index // 4]
    y = CARD_Y + (index % 4) * (CARD_H + CARD_GAP)
    return x, y, x + CARD_W, y + CARD_H


def contains(rect, x, y):
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


def fit_text(value, size, width):
    value = str(value)
    if ui.text_mask(value, size)[0].shape[1] <= width:
        return value
    while value and ui.text_mask(value + "…", size)[0].shape[1] > width:
        value = value[:-1]
    return value + "…"


class SummaryJobs:
    """Workers only send messages; the UI applies them on its own thread."""

    def __init__(self):
        self.updates = queue.Queue()
        self.status = "idle"
        self.kind = None
        self.message = ""
        self.result = None
        self.fingerprint = None

    @property
    def busy(self):
        return self.status == "running"

    def start(self, kind, snapshot, worker):
        if self.busy:
            return False
        self.kind, self.status = kind, "running"
        self.message, self.result = "Preparing…", None
        self.fingerprint = snapshot.fingerprint

        def run():
            try:
                result = worker(snapshot, lambda message: self.updates.put(("progress", str(message))))
                self.updates.put(("done", result))
            except Exception as exc:
                self.updates.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True).start()
        return True

    def poll(self):
        while True:
            try:
                event, value = self.updates.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                self.message = value
            elif event == "done":
                self.status, self.result = "done", value
                self.message = "Ready"
            elif event == "error":
                self.status, self.result = "error", None
                self.message = value


class SummaryView:
    def __init__(self):
        self._snapshot = None
        self._strips = {}
        self._thumb_mask = ui.rounded_mask(66, 66, 10).astype(np.float32) / 255.0

    def hit(self, x, y, snapshot):
        if contains(BACK, x, y):
            return "back", None
        for index, item in enumerate(snapshot.items):
            if contains(card_rect(index), x, y):
                return "toggle", item.name
        for action, rect in BUTTONS.items():
            if contains(rect, x, y):
                return action, None
        return None, None

    def _prepare(self, snapshot):
        if snapshot is self._snapshot:
            return
        self._snapshot = snapshot
        self._strips = {item.name: score_strip(item, snapshot.bars, width=200, height=48)
                        for item in snapshot.items}

    @staticmethod
    def _button(out, rect, label, enabled, hovered=False):
        x0, y0, x1, y1 = rect
        colour = (67, 62, 57) if enabled else (39, 36, 34)
        cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1), colour, -1)
        ui.outline(out, x0, y0, x1, y1, 11, 0.85 if enabled and hovered else 0.4 if enabled else 0.18)
        ui.text(out, label, (x0 + x1) // 2, y0 + 15, 16,
                0.96 if enabled else 0.35, "Medium", align="center")

    def render(self, snapshot, shelf, jobs, mouse=(-1, -1), *, song_jobs=None,
               clip_playing=False, can_render=False, can_play=False, can_reveal=False,
               can_extend=False):
        self._prepare(snapshot)
        out = np.empty((720, 1280, 3), np.uint8)
        out[:] = ui.TONE_DARK.astype(np.uint8)
        cv2.rectangle(out, (0, 0), (1279, 126), (27, 25, 24), -1)
        ui.text(out, "Collected", 28, 23, 30, 0.98, "Semibold")
        selected = len(snapshot.selected)
        ui.text(out, f"{len(snapshot.items)} saved  ·  {selected} in this song", 30, 69, 17, 0.72, "Regular")
        chords = "  →  ".join(chord[0] for chord in snapshot.chords)
        detail = f"{snapshot.bpm:g} BPM   ·   {snapshot.bars} bars   ·   {duration_seconds(snapshot):.1f} sec   ·   "
        ui.text(out, fit_text(detail + chords, 16, 1100), 30, 101, 16, 0.62, "Light")
        self._button(out, BACK, "Back to collecting", True, contains(BACK, *mouse))

        if not snapshot.items:
            ui.text(out, "Nothing collected yet", 640, 292, 27, 0.9, "Medium", align="center")
            ui.text(out, "Go back and photograph an object to start your band.",
                    640, 337, 17, 0.55, "Light", align="center")
        for index, item in enumerate(snapshot.items):
            x0, y0, x1, y1 = card_rect(index)
            hover = contains((x0, y0, x1, y1), *mouse)
            cv2.rectangle(out, (x0, y0), (x1 - 1, y1 - 1),
                          (43, 39, 37) if hover else (35, 32, 30), -1)
            ui.outline(out, x0, y0, x1, y1, 12, 0.38 if item.selected else 0.16)
            entry = shelf.entries[item.name]
            thumb = cv2.resize(entry.thumb, (66, 66), interpolation=cv2.INTER_AREA)
            ui.picture(out, ui.tint(thumb, C.INSTRUMENTS[item.name]["tint"]),
                       self._thumb_mask, x0 + 16, y0 + 17)
            ui.text(out, fit_text(item.shown, 19, 165), x0 + 94, y0 + 16, 19, 0.96, "Medium")
            ui.text(out, fit_text(item.instrument_label, 14, 165),
                    x0 + 94, y0 + 47, 14, 0.62, "Light")
            label = "BEAT GRID" if item.kind == "rhythm" else "MELODY"
            ui.text(out, label, x0 + 275, y0 + 11, 11, 0.45, "Medium")
            strip = self._strips[item.name]
            out[y0 + 34:y0 + 82, x0 + 275:x0 + 475] = strip
            ui.text(out, "In this song", x0 + 502, y0 + 14, 12,
                    0.75 if item.selected else 0.43, "Medium")
            ui.circle(out, x0 + 543, y0 + 64, 15,
                      0.9 if item.selected else 0.35, -1 if item.selected else 2)
            if item.selected:
                ui.text(out, "✓", x0 + 543, y0 + 52, 17, 1.0, "Semibold",
                        color=ui.TONE_DARK, align="center")

        cv2.line(out, (28, 607), (1252, 607), (75, 69, 64), 1)
        ready = jobs.result is not None and jobs.status == "done" and jobs.fingerprint == snapshot.fingerprint
        song_busy = song_jobs.busy if song_jobs is not None else False
        busy = jobs.busy or song_busy
        render_enabled = bool(selected) and not snapshot.style_pending and can_render and not busy
        controls = (("render", "Render loop", render_enabled),
                    ("play", "Stop clip" if clip_playing else "Play clip", ready and can_play and not busy),
                    ("reveal", "Reveal file", ready and can_reveal and not busy),
                    ("extend", "Continue with ElevenLabs", ready and can_extend and not busy))
        for action, label, enabled in controls:
            self._button(out, BUTTONS[action], label, enabled, contains(BUTTONS[action], *mouse))
        if song_busy:
            message = song_jobs.message
        elif jobs.busy:
            message = jobs.message
        elif song_jobs is not None and song_jobs.status == "error":
            message = "ElevenLabs: " + song_jobs.message
        elif jobs.status == "error":
            message = "Could not finish: " + jobs.message
        elif snapshot.style_pending:
            message = "Chord change queued. Wait for the next loop before rendering."
        elif not snapshot.items:
            message = "Collect an item to make a song."
        elif not selected:
            message = "Choose at least one item for this song."
        elif not can_render:
            message = "Loop rendering comes in the next milestone. Your selection is saved."
        elif jobs.status == "done" and not ready:
            message = "The song changed. Render again to use the new arrangement."
        else:
            message = jobs.message or "Ready to render one complete chord cycle."
        ui.text(out, fit_text(message, 14, 1170), 29, 686, 14, 0.6, "Light")
        return out
