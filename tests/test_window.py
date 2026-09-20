"""Resizable window geometry and native-resolution drawing across all pages."""

import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import App, SUMMARY, Viewport, fit_camera_frame
from wavelens import config as C
from wavelens import ui


def test_window_geometry_and_clicks():
    wide = Viewport(1600, 900)
    assert wide.canvas_size == (1600, 900)
    assert wide.to_logical(800, 450) == (640, 360)
    tall = Viewport(1000, 700)
    assert tall.canvas_size == (1000, 562)
    assert tall.left == 0 and tall.top > 0
    picture = np.full((562, 1000, 3), 150, np.uint8)
    shown = tall.present(picture)
    assert shown.shape == (700, 1000, 3)
    assert np.array_equal(shown[0, 0], ui.TONE_DARK.astype(np.uint8))
    assert np.array_equal(shown[tall.top + 200, 500], picture[200, 500])

    with tempfile.TemporaryDirectory() as folder:
        old_shelf, old_cache = C.SHELF_DIR, C.CACHE_DIR
        try:
            C.SHELF_DIR = C.CACHE_DIR = folder
            app = App()
            app.set_viewport(1000, 700)
            x = app.viewport.left + round(1028 * app.viewport.fit_w / 1280)
            y = app.viewport.top + round(656 * app.viewport.fit_h / 720)
            app.on_display_mouse(cv2.EVENT_LBUTTONDOWN, x, y, 0, None)
            assert app.state == SUMMARY
        finally:
            C.SHELF_DIR, C.CACHE_DIR = old_shelf, old_cache


def test_full_resolution_camera_stage_and_collections():
    frame = np.full((1080, 1920, 3), 130, np.uint8)
    fitted, sx, sy, left, top = fit_camera_frame(frame, 1600, 900)
    assert fitted.shape == (900, 1600, 3)
    assert abs(sx - 1280 / 1920) < 1e-9 and abs(sy - 720 / 1080) < 1e-9
    assert left == top == 0

    with tempfile.TemporaryDirectory() as folder:
        old_shelf, old_cache = C.SHELF_DIR, C.CACHE_DIR
        try:
            C.SHELF_DIR = C.CACHE_DIR = folder
            app = App()
            app.set_viewport(1600, 900)
            app.vision.snapshot = lambda: (frame, [])
            assert app.render(0.033).shape == (900, 1600, 3)
            app.show_stage(True)
            assert app.render(0.033).shape == (900, 1600, 3)
            app.enter_summary()
            assert app.render(0.033).shape == (900, 1600, 3)
            app.set_viewport(1000, 700)
            assert app.render(0.033).shape == (562, 1000, 3)
            assert app.viewport.present(app.render(0.033)).shape == (700, 1000, 3)
        finally:
            C.SHELF_DIR, C.CACHE_DIR = old_shelf, old_cache


if __name__ == "__main__":
    test_window_geometry_and_clicks()
    test_full_resolution_camera_stage_and_collections()
    print("ok")
