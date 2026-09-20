"""Collection summary UI and nonblocking job state for later export/cloud work."""

import queue
import threading
from functools import lru_cache
from math import ceil

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
    "song_play": (848, 622, 1000, 672),
    "song_reveal": (1014, 622, 1252, 672),
}
CONFIRM_UPLOAD = (376, 430, 660, 480)
CANCEL_UPLOAD = (680, 430, 904, 480)
DESC = (94, 66, 171, 14, 2)             # x, y and width in the card, line height, lines shown
HOVER_W = 420                           # the whole description, while the pointer rests on a card


def duration_seconds(snapshot):
    return snapshot.bars * C.STEPS_PER_BAR / C.STEPS_PER_BEAT * 60.0 / snapshot.bpm


def card_rect(index):
    """Four rows in each of two columns, all inside the 1280x720 window."""
    x = CARD_X[index // 4]
    y = CARD_Y + (index % 4) * (CARD_H + CARD_GAP)
    return x, y, x + CARD_W, y + CARD_H


def contains(rect, x, y):
    return rect[0] <= x < rect[2] and rect[1] <= y < rect[3]


@lru_cache(maxsize=512)
def fit_text(value, size, width):
    value = str(value)
    if ui.text_width(value, size) <= width:
        return value
    if ui.text_width("…", size) > width:
        return ""
    low, high = 0, len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if ui.text_width(value[:middle] + "…", size) <= width:
            low = middle
        else:
            high = middle - 1
    return value[:low] + "…"


@lru_cache(maxsize=128)
def fit_lines(value, size, width, lines):
    """Wrap to at most `lines`; the last one ends in … when there is more to read."""
    wrapped = ui.wrap(value, size, width)
    if len(wrapped) > lines:
        wrapped = wrapped[:lines - 1] + [fit_text(" ".join(wrapped[lines - 1:]), size, width)]
    return tuple(wrapped)


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
        self._canvas_size = None
        self._strips = {}
        self._thumb_mask = ui.rounded_mask(66, 66, 10).astype(np.float32) / 255.0

    def hit(self, x, y, snapshot, *, confirm_upload=False):
        if confirm_upload:
            if contains(CONFIRM_UPLOAD, x, y):
                return "confirm_extend", None
            if contains(CANCEL_UPLOAD, x, y):
                return "cancel_extend", None
            return None, None
        if contains(BACK, x, y):
            return "back", None
        for index, item in enumerate(snapshot.items):
            if contains(card_rect(index), x, y):
                return "toggle", item.name
        for action, rect in BUTTONS.items():
            if contains(rect, x, y):
                return action, None
        return None, None

    def _prepare(self, snapshot, canvas_size):
        if snapshot is self._snapshot and canvas_size == self._canvas_size:
            return
        self._snapshot = snapshot
        self._canvas_size = canvas_size
        sx, sy = canvas_size[0] / ui.DESIGN_W, canvas_size[1] / ui.DESIGN_H
        self._strips = {item.name: score_strip(item, snapshot.bars,
                                              width=round(200 * sx), height=round(48 * sy))
                        for item in snapshot.items}

    @staticmethod
    def _description_panel(out, x0, y0, y1, text):
        """What Gemini said about the photo, in full, beside the card it belongs to."""
        lines = fit_lines(text, 14, HOVER_W - 36, 5)
        wide = ceil(max(ui.text_width(line, 14) for line in lines)) + 36
        high = 26 + 20 * len(lines)
        x = min(max(x0 + DESC[0] - 16, 8), 1280 - wide - 8)
        y = y1 - 10 if y1 - 10 + high <= 600 else max(y0 + 10 - high, 132)   # attached to its own card
        ui.frosted(out, x, y, x + wide, y + high, r=12)
        for row, line in enumerate(lines):
            ui.text(out, line, x + 18, y + 13 + 20 * row, 14, 0.92, "Regular")

    @staticmethod
    def _button(out, rect, label, enabled, hovered=False):
        x0, y0, x1, y1 = rect
        radius = (y1 - y0) // 2 - 1
        ui.outline(out, x0, y0, x1, y1, radius,
                   0.92 if enabled and hovered else 0.65 if enabled else 0.2)
        ui.text(out, label, (x0 + x1) // 2, y0 + 15, 16,
                0.98 if hovered and enabled else 0.82 if enabled else 0.35,
                "Medium", align="center")

    def render(self, snapshot, shelf, jobs, mouse=(-1, -1), *, song_jobs=None,
               clip_playing=False, can_render=False, can_play=False, can_reveal=False,
               can_extend=False, song_playing=False, confirm_upload=False,
               has_music_key=False, notice="", description_pending=None,
               description_attempts=(), has_gemini_key=False,
               canvas_size=(ui.DESIGN_W, ui.DESIGN_H)):
        self._prepare(snapshot, canvas_size)
        out = np.empty((canvas_size[1], canvas_size[0], 3), np.uint8)
        out[:] = ui.TONE_DARK.astype(np.uint8)
        ui.fill_rect(out, 0, 0, 1280, 127, (27, 25, 24))
        ui.text(out, "Collections", 28, 23, 30, 0.98, "Semibold")
        selected = len(snapshot.selected)
        ui.text(out, f"{len(snapshot.items)} saved  ·  {selected} in this song", 30, 69, 17, 0.72, "Regular")
        chords = "  →  ".join(chord[0] for chord in snapshot.chords)
        detail = f"{snapshot.bpm:g} BPM   ·   {snapshot.bars} bars   ·   {duration_seconds(snapshot):.1f} sec   ·   "
        ui.text(out, fit_text(detail + chords, 16, 1100), 30, 101, 16, 0.62, "Light")
        self._button(out, BACK, "Back to collecting", True, contains(BACK, *mouse))

        described = None                     # the hovered card's words, drawn over the rest
        if not snapshot.items:
            ui.text(out, "Nothing collected yet", 640, 292, 27, 0.9, "Medium", align="center")
            ui.text(out, "Go back and photograph an object to start your band.",
                    640, 337, 17, 0.55, "Light", align="center")
        for index, item in enumerate(snapshot.items):
            x0, y0, x1, y1 = card_rect(index)
            hover = contains((x0, y0, x1, y1), *mouse)
            ui.fill_rect(out, x0, y0, x1, y1,
                         (43, 39, 37) if hover else (35, 32, 30))
            ui.outline(out, x0, y0, x1, y1, 12, 0.38 if item.selected else 0.16)
            entry = shelf.entries[item.name]
            thumb = cv2.resize(entry.thumb, (66, 66), interpolation=cv2.INTER_AREA)
            ui.picture(out, ui.tint(thumb, C.INSTRUMENTS[item.name]["tint"]),
                       self._thumb_mask, x0 + 16, y0 + 17)
            ui.text(out, fit_text(item.shown, 19, 165), x0 + 94, y0 + 16, 19, 0.96, "Medium")
            ui.text(out, fit_text(item.instrument_label, 14, 165),
                    x0 + 94, y0 + 47, 14, 0.62, "Light")
            if entry.description:
                dx, dy, dw, line, rows = DESC
                for row, text in enumerate(fit_lines(entry.description, 12, dw, rows)):
                    ui.text(out, text, x0 + dx, y0 + dy + row * line, 12, 0.82, "Regular")
                if hover:
                    described = (x0, y0, y1, entry.description)
            else:
                if not has_gemini_key:
                    caption = "Gemini key needed for description"
                elif item.name == description_pending:
                    caption = "Gemini is describing…"
                elif item.name in description_attempts:
                    caption = "Gemini could not describe this item"
                else:
                    caption = "Waiting for Gemini…"
                ui.text(out, caption, x0 + 94, y0 + 69, 12, 0.62, "Light")
            label = "BEAT GRID" if item.kind == "rhythm" else "MELODY"
            ui.text(out, label, x0 + 275, y0 + 11, 11, 0.45, "Medium")
            strip = self._strips[item.name]
            ui.paste(out, strip, x0 + 275, y0 + 34, 200, 48)
            ui.text(out, "In this song", x0 + 502, y0 + 14, 12,
                    0.75 if item.selected else 0.43, "Medium")
            ui.circle(out, x0 + 543, y0 + 64, 15,
                      0.9 if item.selected else 0.35, -1 if item.selected else 2)
            if item.selected:
                ui.text(out, "✓", x0 + 543, y0 + 52, 17, 1.0, "Semibold",
                        color=ui.TONE_DARK, align="center")

        if described is not None:
            self._description_panel(out, *described)

        ui.line(out, 28, 607, 1252, 607, (75, 69, 64))
        ready = jobs.result is not None and jobs.status == "done" and jobs.fingerprint == snapshot.fingerprint
        song_busy = song_jobs.busy if song_jobs is not None else False
        busy = jobs.busy or song_busy
        render_enabled = bool(selected) and not snapshot.style_pending and can_render and not busy
        render_label = "Render again" if jobs.status == "done" and not ready else "Render loop"
        song_ready = song_jobs is not None and song_jobs.status == "done" and song_jobs.result is not None
        controls = (("render", render_label, render_enabled),
                    ("play", "Stop clip" if clip_playing else "Play clip", ready and can_play and not jobs.busy),
                    ("reveal", "Reveal file", ready and can_reveal and not jobs.busy),
                    ("extend", "Continue with ElevenLabs", ready and can_extend and has_music_key and not busy),
                    ("song_play", "Stop song" if song_playing else "Play song", song_ready and not busy),
                    ("song_reveal", "Reveal song", song_ready and not busy))
        for action, label, enabled in controls:
            self._button(out, BUTTONS[action], label, enabled, contains(BUTTONS[action], *mouse))
        if notice:
            message = notice
        elif song_busy:
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
            message = "Loop rendering is unavailable. Your selection is saved."
        elif jobs.status == "done" and not ready:
            message = "The song changed. Render again to use the new arrangement."
        elif song_ready:
            earlier = " · earlier arrangement" if song_jobs.fingerprint != snapshot.fingerprint else ""
            message = f"Full song ready · {song_jobs.result.duration:.1f} sec · original intro + AI continuation{earlier}"
        elif ready and not has_music_key:
            message = f"Loop ready. Set {C.ELEVENLABS_KEY_ENV} to enable full-song generation."
        else:
            message = jobs.message or "Ready to render one complete chord cycle."
        ui.text(out, fit_text(message, 14, 1170), 29, 686, 14, 0.6, "Light")
        if confirm_upload:
            ui.frosted(out, 312, 250, 968, 500, r=18, darken=0.78)
            ui.text(out, "Continue with ElevenLabs?", 348, 280, 25, 0.98, "Semibold")
            ui.text(out, "The rendered WAV will be uploaded. Upload and generation may use paid credits.",
                    348, 329, 15, 0.80, "Regular")
            ui.text(out, "Confirm you have rights to its sounds; screening can still reject the upload.",
                    348, 354, 15, 0.80, "Regular")
            ui.text(out, "Your original loop stays as the intro of the generated song.",
                    348, 379, 15, 0.80, "Regular")
            self._button(out, CONFIRM_UPLOAD, "Upload & generate", True,
                         contains(CONFIRM_UPLOAD, *mouse))
            self._button(out, CANCEL_UPLOAD, "Cancel", True, contains(CANCEL_UPLOAD, *mouse))
        return out
