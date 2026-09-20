"""Summary navigation, card layout, selection, and nonblocking job messages."""

import os
import sys
import tempfile
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import config as C
from wavelens import cloud, ui
from wavelens.shelf import Shelf
from wavelens.summary import BACK, BUTTONS, SummaryJobs, card_rect, duration_seconds
from main import App, PREVIEW, SHOW, SUMMARY

# These UI tests must never pick up a developer's private Gemini key file.
C.CACHE_DIR = tempfile.mkdtemp(prefix="wavelens_test_keys_")


def make_app(folder, names=()):
    old_folder = C.SHELF_DIR
    C.SHELF_DIR = folder
    try:
        shelf = Shelf(folder, C.INSTRUMENTS)
        for index, name in enumerate(names):
            frame = np.full((120, 160, 3), 35 + index * 18, np.uint8)
            shelf.add(name, name if index != 0 else "an especially long object name",
                      0.9, frame, [30, 20, 125, 105])
            if index % 2 == 0:
                shelf.select(name, True)
        return App()
    finally:
        C.SHELF_DIR = old_folder


def test_layout_and_empty_state():
    for index in range(8):
        x0, y0, x1, y1 = card_rect(index)
        assert 0 <= x0 < x1 <= 1280 and 126 < y0 < y1 < 607
        assert not any(x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1
                       for b in (card_rect(j) for j in range(index)))
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder)
        app.enter_summary()
        assert app.state == SUMMARY
        frame = app.render(0.033)              # no camera frame is available
        assert frame.shape == (720, 1280, 3) and frame.max() > 100
        assert app.current_summary().items == ()
        assert app.summary_view.hit(*BACK[:2], app.current_summary()) == ("back", None)
        assert app.summary_view.hit(*BUTTONS["render"][:2], app.current_summary()) == ("render", None)
        app.summary_action("render")           # disabled until Milestone 3
        assert app.summary_jobs.status == "idle"


def test_navigation_and_cards():
    names = tuple(C.INSTRUMENTS)
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder, names)
        original = app.shelf.order()
        assert app.handle_key(ord("e")) is False and app.state == SUMMARY
        assert app.state_dict()["mode"] == app.state_dict()["view"] == SUMMARY
        snapshot = app.current_summary()
        assert len(snapshot.items) == 8
        assert len(snapshot.selected) == 4
        assert duration_seconds(snapshot) == 8.0
        image = app.render(0.033)
        assert image.shape == (720, 1280, 3)
        assert app.summary_view.hit(700, 160, snapshot) == ("toggle", names[4])
        old_fingerprint = snapshot.fingerprint
        app.on_mouse(cv2.EVENT_LBUTTONDOWN, 700, 160, 0, None)
        assert names[4] not in app.shelf.selected()
        assert app.current_summary().fingerprint != old_fingerprint
        assert app.handle_key(ord(" ")) is False and app.state == SUMMARY
        assert app.handle_key(ord("p")) is False and app.playing
        assert app.handle_key(ord("1")) is False
        assert names[0] not in app.shelf.selected()
        app.on_mouse(cv2.EVENT_LBUTTONDOWN, 1120, 45, 0, None)
        assert app.state == PREVIEW and app.shelf.order() == original

        app.on_mouse(cv2.EVENT_LBUTTONDOWN, 980, 650, 0, None)  # visible Finish button
        assert app.state == SUMMARY
        app.handle_key(ord("b"))
        assert app.state == PREVIEW

        app.state = SHOW
        app.on_stage = True
        app.enter_summary()
        assert app.render(0.033).shape == (720, 1280, 3)
        app.handle_key(27)
        assert app.state == SHOW and app.on_stage


def test_job_updates_are_nonblocking():
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder, ("cup",))
        snapshot = app.arrangement_snapshot()
        jobs = SummaryJobs()
        release = threading.Event()

        def worker(score, progress):
            progress("Rendering bar 1")
            assert release.wait(2)
            return score.fingerprint

        start = time.monotonic()
        assert jobs.start("render", snapshot, worker)
        assert time.monotonic() - start < 0.5
        assert not jobs.start("render", snapshot, worker)
        try:
            for _ in range(100):
                jobs.poll()
                if jobs.message == "Rendering bar 1":
                    break
                time.sleep(0.002)
            assert jobs.busy and jobs.message == "Rendering bar 1"
        finally:
            release.set()
        for _ in range(100):
            jobs.poll()
            if jobs.status == "done":
                break
            time.sleep(0.002)
        assert jobs.status == "done" and jobs.result == snapshot.fingerprint


def test_render_state_and_stale_clip():
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder, ("cup", "pen"))
        app.enter_summary()
        app.render_worker = lambda snapshot, progress: snapshot.fingerprint
        app.summary_action("render")
        for _ in range(100):
            app.render(0.033)                # main-thread queue consumption
            if app.summary_jobs.status == "done":
                break
            time.sleep(0.002)
        assert app.current_clip_ready()
        app.summary_action("toggle", "cup")
        assert not app.current_clip_ready()
        app.clip_player = lambda *_: (_ for _ in ()).throw(AssertionError("stale clip played"))
        app.summary_action("play")           # unavailable after a sound-changing selection


def test_description_is_kept_and_shown():
    """Gemini answers after the shutter; the words reach the object that photo
    filed, and the Collections card shows them, in full while hovered."""
    words = ("A white ceramic mug with a matte glaze and a small chip on the rim, "
             "half full of black coffee.")
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder, ("cup", "pen"))
        app.enter_summary()
        plain = app.render(0.033)

        app.describing = ("cup", app.describer.job)          # the photo that filed the cup
        app.describer.status, app.describer.text = "done", words
        app.file_description()
        assert app.describing is None
        assert app.shelf.entries["cup"].description == words

        app.describing = ("pen", app.describer.job - 1)      # an older photo: not these words
        app.file_description()
        assert app.describing is None and app.shelf.entries["pen"].description is None

        x0, y0, x1, y1 = card_rect(app.shelf.order().index("cup"))
        box = (slice(y0 + 66, y0 + 92), slice(x0 + 94, x0 + 265))
        shown = app.render(0.033)
        assert shown[box].max() > plain[box].max() + 20      # two lines of it, under the labels
        assert np.array_equal(shown[y0 + 17:y0 + 83, x0 + 16:x0 + 82],
                              plain[y0 + 17:y0 + 83, x0 + 16:x0 + 82])   # thumbnail untouched

        app.mouse = ((x0 + x1) // 2, (y0 + y1) // 2)         # the whole description, on hover
        panel = (slice(y1 + 10, y1 + 40), slice(x0 + 94, x0 + 400))
        assert abs(float(app.render(0.033)[panel].mean()) - float(shown[panel].mean())) > 3


def test_existing_items_get_individual_descriptions():
    original_describe = cloud.describe
    original_key = os.environ.get(C.GEMINI_KEY_ENV)
    descriptions = []

    def describe(frame, api_key):
        descriptions.append(int(frame[0, 0, 0]))
        return f"Saved object shade {descriptions[-1]}"

    try:
        os.environ[C.GEMINI_KEY_ENV] = "test-key"
        cloud.describe = describe
        with tempfile.TemporaryDirectory() as folder:
            app = make_app(folder, ("cup", "pen"))
            app.enter_summary()
            for _ in range(100):
                app.render(0.033)
                if all(entry.description for entry in app.shelf.entries.values()):
                    break
                time.sleep(0.01)
            assert len(descriptions) == 2
            assert all(entry.description for entry in app.shelf.entries.values())
            assert len({entry.description for entry in app.shelf.entries.values()}) == 2
            saved = Shelf(folder, C.INSTRUMENTS)
            assert all(saved.entries[name].description == app.shelf.entries[name].description
                       for name in ("cup", "pen"))
    finally:
        cloud.describe = original_describe
        if original_key is None:
            os.environ.pop(C.GEMINI_KEY_ENV, None)
        else:
            os.environ[C.GEMINI_KEY_ENV] = original_key


def test_failed_description_is_not_retried_each_frame():
    original_describe = cloud.describe
    original_key = os.environ.get(C.GEMINI_KEY_ENV)
    attempts = []

    def fail(frame, api_key):
        attempts.append(1)
        raise RuntimeError("temporary Gemini failure")

    try:
        os.environ[C.GEMINI_KEY_ENV] = "test-key"
        cloud.describe = fail
        with tempfile.TemporaryDirectory() as folder:
            app = make_app(folder, ("cup",))
            app.enter_summary()
            for _ in range(30):
                app.render(0.033)
                time.sleep(0.001)
            assert len(attempts) == 1
            assert app.shelf.entries["cup"].description is None
    finally:
        cloud.describe = original_describe
        if original_key is None:
            os.environ.pop(C.GEMINI_KEY_ENV, None)
        else:
            os.environ[C.GEMINI_KEY_ENV] = original_key


def test_six_descriptions_do_not_rasterize_hundreds_of_trial_strings():
    """Opening Collections with six long Gemini captions must stay light enough
    that the audio callback can keep running while its instruments fade out."""
    with tempfile.TemporaryDirectory() as folder:
        app = make_app(folder, tuple(C.INSTRUMENTS)[:6])
        for name in app.shelf.order():
            app.shelf.describe(name, "A ceramic and metal object with a bright finish " * 3)
        app.enter_summary()
        original = ui.text_mask
        masks = []

        def counted(*args, **kwargs):
            masks.append(1)
            return original(*args, **kwargs)

        try:
            ui.text_mask = counted
            app.render(0.033)
        finally:
            ui.text_mask = original
        assert len(masks) < 120, len(masks)


if __name__ == "__main__":
    test_layout_and_empty_state()
    test_navigation_and_cards()
    test_job_updates_are_nonblocking()
    test_render_state_and_stale_clip()
    test_description_is_kept_and_shown()
    test_existing_items_get_individual_descriptions()
    test_failed_description_is_not_retried_each_frame()
    test_six_descriptions_do_not_rasterize_hundreds_of_trial_strings()
    print("ok")
