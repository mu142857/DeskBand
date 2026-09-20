"""The shelf keeps what was shot: add, select, reload from disk, remove."""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens.shelf import Shelf, THUMB, crop_square

NAMES = ["cup", "pen", "cell phone"]


def test_shelf():
    folder = tempfile.mkdtemp(prefix="wavelens_shelf_")
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

    again = Shelf(folder, NAMES)                  # cup was deselected above; restart preserves that
    assert set(again.entries) == {"cup", "cell phone"} and again.selected() == set()
    assert again.entries["cup"].thumb.shape == (THUMB, THUMB, 3)
    assert again.entries["cup"].thumb[THUMB // 2, THUMB // 2, 2] > 150             # the orange patch

    again.remove("cup")
    assert set(Shelf(folder, NAMES).entries) == {"cell phone"}


def test_description():
    """Gemini's words are filed with the object and survive a restart; the first
    description stays even when the same object is shot again."""
    folder = tempfile.mkdtemp(prefix="wavelens_shelf_")
    frame = np.zeros((720, 1280, 3), np.uint8)
    shelf = Shelf(folder, NAMES)

    assert shelf.describe("cup", "a mug") is False            # nothing saved there yet
    shelf.add("cup", "mug", 0.7, frame, [500, 200, 700, 400])
    assert shelf.entries["cup"].description is None
    assert shelf.describe("cup", "  A white ceramic mug.\n ") is True
    assert shelf.entries["cup"].description == "A white ceramic mug."
    assert shelf.describe("cup", "A blue enamel mug.") is False    # the first one stays
    assert shelf.describe("cup", "   ") is False

    shelf.add("cup", "cup", 0.9, frame, [500, 200, 700, 400])      # re-shot: new photo, same words
    assert shelf.entries["cup"].description == "A white ceramic mug."

    again = Shelf(folder, NAMES)
    assert again.entries["cup"].description == "A white ceramic mug."
    again.add("pen", "pen", 0.6, frame, [10, 10, 90, 200])         # nothing said about this one
    assert Shelf(folder, NAMES).entries["pen"].description is None


if __name__ == "__main__":
    test_shelf()
    test_description()
    print("ok")
