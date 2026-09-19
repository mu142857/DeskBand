"""The stage's two axes: loudness maps to a trim on the part's level,
complexity reshapes each bar (thinner to the left, busier to the right, as
written in the middle, always in tune), and placements survive a restart."""

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.music import Composer, weight
from deskband.shelf import Shelf
from deskband.stage import complexity_word, loudness_db, loudness_gain

BARS = 16
P = C.STEPS_PER_BAR


def play(complexity, math=False):
    """-> {part: [(bar, step, midi_or_hit), ...]} with every part at one complexity."""
    c = Composer()
    c.set_math(math)
    for name in c.parts:
        c.set_complexity(name, complexity)
    notes = {}
    for step in range(P * BARS):
        for part, voice, m, *_ in c.step(step):
            if part == "backing":
                continue
            if voice != "drums":
                assert m % 12 in C.PENTATONIC or m % 12 in c.chords[c.chord_index].pcs, (part, m)
            notes.setdefault(part, []).append((step // P, step % P, m))
    return notes


def test_loudness():
    lo, hi = C.STAGE_DB
    assert loudness_db(0.5) == 0 and loudness_gain(0.5) == 1
    assert abs(loudness_db(0.0) - lo) < 1e-9 and abs(loudness_db(1.0) - hi) < 1e-9
    ys = np.linspace(0, 1, 101)
    assert all(np.diff([loudness_gain(y) for y in ys]) > 0)          # higher is always louder
    assert [complexity_word(x) for x in (0.1, 0.5, 0.9)] == ["pared down", "as written", "embellished"]


def test_complexity():
    written = play(0.5)
    assert play(C.STAGE_AS_WRITTEN[0] + 0.01) == written              # the middle band changes nothing
    sparse, busy = play(0.0), play(1.0)
    for part in written:
        assert sparse.get(part), part                                    # thinned, never silenced
        assert len({(b, s) for b, s, _ in sparse[part]}) <= BARS, part   # one onset a bar at most
        assert len(busy[part]) > len(written[part]), part
    assert all(weight(s) == 4 for _, s, _ in sparse["book"])            # drums: the downbeat kick alone
    mid = play(0.25)                                                     # beats only
    assert all(weight(s) >= 2 for part in ("pen", "book") for _, s, _ in mid[part])
    assert len(play(1.0, math=True)["cup"]) > len(play(0.5, math=True)["cup"])


def test_placement_saved():
    folder = tempfile.mkdtemp(prefix="deskband_stage_")
    frame = np.zeros((720, 1280, 3), np.uint8)
    shelf = Shelf(folder, ["cup", "pen"])
    shelf.add("cup", "cup", 0.8, frame, [500, 200, 700, 400])
    assert shelf.entries["cup"].pos is None
    shelf.place("cup", (0.8, 1.7))                                       # clamped into the plane
    assert shelf.entries["cup"].pos == (0.8, 1.0)
    shelf.add("cup", "mug", 0.9, frame, [500, 200, 700, 400])            # re-shot: stays where it was
    assert Shelf(folder, ["cup", "pen"]).entries["cup"].pos == (0.8, 1.0)


if __name__ == "__main__":
    test_loudness()
    test_complexity()
    test_placement_saved()
    print("ok")
