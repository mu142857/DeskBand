"""Summary navigation, card layout, selection, and nonblocking job messages."""

import os
import sys
import tempfile
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.shelf import Shelf
from deskband.summary import BACK, BUTTONS, SummaryJobs, card_rect, duration_seconds
from main import App, PREVIEW, SHOW, SUMMARY


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


if __name__ == "__main__":
    test_layout_and_empty_state()
    test_navigation_and_cards()
    test_job_updates_are_nonblocking()
    test_render_state_and_stale_clip()
    print("ok")
