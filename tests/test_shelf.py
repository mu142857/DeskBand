"""The shelf keeps what was shot: add, select, reload from disk, remove."""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband.shelf import Shelf, THUMB, crop_square

NAMES = ["cup", "pen", "cell phone"]


def test_shelf():
    folder = tempfile.mkdtemp(prefix="deskband_shelf_")
    frame = np.zeros((720, 1280, 3), np.uint8)
    frame[200:400, 500:700] = (40, 160, 220)

    # crops are always square and inside the frame, even for a box in the corner
    assert crop_square(frame, [500, 200, 700, 400]).shape == (THUMB, THUMB, 3)
    assert crop_square(frame, [0, 0, 1280, 60]).shape == (THUMB, THUMB, 3)
    assert crop_square(frame, [1200, 650, 1280, 720]).shape == (THUMB, THUMB, 3)

    shelf = Shelf(folder, NAMES)
    assert shelf.add("teapot", "teapot", 0.9, frame, [0, 0, 50, 50]) is None       # not an instrument
    shelf.add("cup", "mug", 0.71, frame, [500, 200, 700, 400])
    shelf.add("cell phone", "cell phone", 0.5, frame, [10, 10, 90, 200])
    assert shelf.selected() == set()
    shelf.select("cup", True)
    shelf.select("pen", True)                     # nothing saved there: ignored
    assert shelf.selected() == {"cup"}
    shelf.add("cup", "cup", 0.8, frame, [500, 200, 700, 400])                       # re-shot: stays selected
    assert shelf.selected() == {"cup"} and shelf.entries["cup"].shown == "cup"
    shelf.select("cup")
    assert shelf.selected() == set()

    again = Shelf(folder, NAMES)                  # a restart finds the same shelf, all switched off
    assert set(again.entries) == {"cup", "cell phone"} and again.selected() == set()
    assert again.entries["cup"].thumb.shape == (THUMB, THUMB, 3)
    assert again.entries["cup"].thumb[THUMB // 2, THUMB // 2, 2] > 150             # the orange patch

    again.remove("cup")
    assert set(Shelf(folder, NAMES).entries) == {"cell phone"}


if __name__ == "__main__":
    test_shelf()
    print("ok")
