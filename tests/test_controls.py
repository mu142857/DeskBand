"""Everything the board's buttons do can be done without the board: the rhythm
grid (BTN2) and the tapped tempo (BTN3), and a part that is in the band but not
heard says why."""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

import main
from wavelens import config as C
from wavelens.music import Composer, P
from main import App


def test_eighth_grid():
    """On from the next bar line; no note on an odd 16th; no part emptied."""
    composer = Composer()
    composer.set_math(True)
    for name in composer.parts:
        composer.set_complexity(name, 1.0)               # as many 16ths as the stage can ask for
    mixed = 0
    for step in range(8 * P):
        mixed += sum(1 for ev in composer.step(step) if step % 2 and ev[0] in C.INSTRUMENTS)
    assert mixed > 0
    full = dict(composer.bar_view.onsets)
    composer.set_eighths(True)
    assert not composer.bar_view.eighths                 # the bar being played is left alone
    for step in range(8 * P, 16 * P):
        events = [ev for ev in composer.step(step) if ev[0] in C.INSTRUMENTS]
        assert composer.bar_view.eighths
        assert not (step % 2 and events), (step, events)
        if step % 2:
            assert all(composer.rhythmic_events(name, step) == [] for name in composer.parts)
    assert all(onsets for name, onsets in composer.bar_view.onsets.items() if full[name])


def make_app(folder):
    C.SHELF_DIR = folder
    return App()


def test_tap_tempo():
    folder = tempfile.TemporaryDirectory()
    old_folder, clock = C.SHELF_DIR, time.monotonic
    try:
        app = make_app(folder.name)
        now = [100.0]
        main.time.monotonic = lambda: now[0]

        def taps(gap, count=4):
            for _ in range(count):
                app.tap()
                now[0] += gap

        taps(0.6)
        assert app.engine.bpm == 100 and app.taps == []
        now[0] += 5
        taps(0.1)                                        # 600 BPM: held to 180
        assert app.engine.bpm == 180
        now[0] += 5
        taps(1.5)                                        # 40 BPM: held to 60
        assert app.engine.bpm == 60
        now[0] += 5
        taps(0.5, 2)                                     # an abandoned count starts again
        now[0] += 5
        taps(0.4)
        assert app.engine.bpm == 150

        app.handle_command({"cmd": "bpm", "value": 999})
        assert app.engine.bpm == 180
        app.handle_key(ord("-"))
        assert app.engine.bpm == 178
        x0, y0, x1, y1 = app.tempo_pill
        app.on_mouse(cv2.EVENT_LBUTTONDOWN, x1 - 10, y0 + 10, 0, None)
        assert app.engine.bpm == 180
        app.on_mouse(cv2.EVENT_LBUTTONDOWN, (x0 + x1) // 2, y0 + 10, 0, None)
        assert len(app.taps) == 1
    finally:
        main.time.monotonic = clock
        C.SHELF_DIR = old_folder
        folder.cleanup()


def test_grid_button_and_board():
    folder = tempfile.TemporaryDirectory()
    old_folder = C.SHELF_DIR
    try:
        app = make_app(folder.name)
        app.handle_key(ord("g"))
        assert app.composer.eighths
        app.on_mouse(cv2.EVENT_LBUTTONDOWN, app.grid_button[0], app.grid_button[1], 0, None)
        assert not app.composer.eighths
        app.handle_command({"cmd": "grid", "eighths": True})
        assert app.composer.eighths and app.state_dict()["eighths"] is False   # not heard yet
        app.handle_command({"cmd": "grid", "eighths": False})

        app.handle_command({"cmd": "fpga_mode", "on": True})
        app.handle_command({"cmd": "fpga_bar", "bar": 3, "eighths": True})      # BTN2 on the board
        assert app.composer.eighths and app.state_dict()["eighths"]
        app.handle_command({"cmd": "fpga_bar", "bar": 4, "eighths": True})
        app.handle_key(ord("g"))                         # the board repeating itself does not undo a click
        app.handle_command({"cmd": "fpga_bar", "bar": 5, "eighths": True})
        assert not app.composer.eighths
        app.render(0.033)
    finally:
        C.SHELF_DIR = old_folder
        folder.cleanup()


def test_why_silent():
    folder = tempfile.TemporaryDirectory()
    old_folder = C.SHELF_DIR
    try:
        app = make_app(folder.name)
        e = app.engine
        assert app.why_silent("laptop") is None          # not in the band: nothing to explain
        app.manual["laptop"] = app.manual["cup"] = True
        app.play(True)
        assert app.why_silent("cup") == "loading samples"
        assert app.why_silent("laptop") is None          # synthesised, and only just switched on
        bar = C.STEPS_PER_BAR * e.step_len
        e.pos += 3 * bar
        assert app.why_silent("laptop") == "no notes"
        e.hits["laptop"] = e.pos - bar
        assert app.why_silent("laptop") is None
        e.set_trim("laptop", 0.0)
        assert app.why_silent("laptop") == "turned down on the stage"
        e.set_trim("laptop", 1.0)

        app.handle_command({"cmd": "fpga_mode", "on": True})
        assert app.why_silent("laptop") == "no clock from the board"
        e.queue_fpga_event(0, 0, 0x7f, 0x7f)
        assert app.why_silent("laptop") is None
        levels = [255] * 7
        levels[e.fpga_track_index["laptop"]] = 0
        app.handle_command({"cmd": "fpga_controls", "levels": levels, "lfos": [0] * 7})
        assert app.why_silent("laptop") == "board level at 0"
        app.render(0.033)
        app.show_stage(True)
        app.render(0.033)
    finally:
        C.SHELF_DIR = old_folder
        folder.cleanup()


if __name__ == "__main__":
    test_eighth_grid()
    test_tap_tempo()
    test_grid_button_and_board()
    test_why_silent()
    print("ok")
