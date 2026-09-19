"""The camera UI follows one stable object without changing detector boxes."""

import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband.vision import Detection
from main import App, fit_camera_frame


def test_single_target_preview():
    app = SimpleNamespace(shelf=SimpleNamespace(entries={}), preview_box=None)
    app.pick = lambda dets: App.pick(app, dets)
    drawn = []
    app.draw_box = lambda out, frame, det, *args, **kwargs: drawn.append(det)
    image = np.zeros((720, 1280, 3), np.uint8)

    cup = Detection("cup", 0.70, [20, 30, 120, 130])
    pen = Detection("pen", 0.65, [400, 40, 500, 140])
    assert len(app.pick([cup, pen])) == 1
    assert App.draw_preview(app, image, image, [cup, pen], 0.033) == {"cup": "cup"}
    assert len(drawn) == 1 and drawn[-1].name == "cup"

    moved = Detection("cup", 0.60, [100, 30, 200, 130])
    louder_pen = Detection("pen", 0.70, [400, 40, 500, 140])
    drawn.clear()
    App.draw_preview(app, image, image, [moved, louder_pen], 0.033, 2.0, 1.5)
    assert len(drawn) == 1 and drawn[-1].name == "cup"  # brief score fluctuation does not jump
    assert 40 < drawn[-1].box[0] < 200               # smooth between old and new x, then scale
    assert drawn[-1].box[1] == 45                    # scale original y for the display
    assert moved.box == [100, 30, 200, 130]         # drawing did not alter detector input

    book = Detection("book", 0.99, [700, 100, 900, 300])
    drawn.clear()
    App.draw_preview(app, image, image, [moved, book], 0.033)
    assert len(drawn) == 1 and drawn[-1].name == "book"  # old outline is gone
    assert App.pick(app, [moved, book])[0].name == "book"


def test_full_camera_frame_fits_without_crop():
    source = np.zeros((120, 160, 3), np.uint8)
    source[:, :20] = (20, 50, 90)
    source[:, -20:] = (90, 50, 20)
    fitted, sx, sy, left, top = fit_camera_frame(source)
    assert fitted.shape == (720, 1280, 3)
    assert (sx, sy, left, top) == (6.0, 6.0, 160, 0)
    assert np.array_equal(fitted[360, 160], source[60, 0])
    assert np.array_equal(fitted[360, 1119], source[60, 159])
    assert not np.array_equal(fitted[360, 0], source[60, 0])


if __name__ == "__main__":
    test_single_target_preview()
    test_full_camera_frame_fits_without_crop()
    print("ok")
