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
from deskband.stage import Stage, complexity_word, loudness_db, loudness_gain

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


class FakeApp:
    """Just enough of the App for the stage to place tokens and apply them."""

    def __init__(self, folder, names):
        self.shelf = Shelf(folder, C.INSTRUMENTS)
        self.composer = Composer()
        self.engine = type("E", (), {"set_trim": lambda *a: None})()
        self.tile_mask = np.zeros((72, 72), np.float32)
        frame = np.zeros((720, 1280, 3), np.uint8)
        for n in names:
            self.shelf.add(n, n, 0.9, frame, [500, 200, 700, 400])
        self.band = set(names)


def stage_of(names):
    app = FakeApp(tempfile.mkdtemp(prefix="deskband_stage_"), names)
    app.stage = Stage(app, 132, 100, 1124, 584)                          # the App's own plane
    return app.stage


def spread(stage):
    """-> (positions, the closest two tokens in px)."""
    pos = {n: stage.app.shelf.entries[n].pos for n in stage.placed()}
    screen = [stage.to_screen(p) for p in pos.values()]
    gaps = [np.hypot(a[0] - b[0], a[1] - b[1])
            for i, a in enumerate(screen) for b in screen[i + 1:]]
    return pos, min(gaps, default=1e9)


def test_new_instruments_spread_out():
    names = list(C.INSTRUMENTS)[:6]
    for _ in range(20):                                                  # it is random: run it a few times
        stage = stage_of(names)
        stage.settle()
        pos, closest = spread(stage)
        assert len(pos) == len(names)
        assert closest >= stage.size, closest                            # no token lands on another
        for (x, y) in pos.values():                                      # never against an edge
            assert 0.1 < x < 0.9 and 0.1 < y < 0.9, (x, y)


def test_shuffle():
    names = list(C.INSTRUMENTS)
    for _ in range(20):
        stage = stage_of(names)
        stage.settle()
        stage.shuffle()
        pos, closest = spread(stage)
        assert closest >= stage.size, closest
        computed = {n: p for n, p in pos.items() if n in stage.app.composer.computed}
        loud = [n for n, p in computed.items() if loudness_db(p[1]) > 6]
        assert len(loud) == 1, loud                                      # exactly one line out front...
        assert all(p[1] <= 0.62 for n, p in computed.items() if n not in loud)   # ...the rest kept under it
        drums = [n for n in pos if C.INSTRUMENTS[n]["voice"] == "drums"]
        for n in drums:                                                  # high, in the middle
            assert 0.4 <= pos[n][0] <= 0.6 and 0.6 <= pos[n][1] <= 0.78, pos[n]


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
    test_new_instruments_spread_out()
    test_shuffle()
    test_placement_saved()
    print("ok")
