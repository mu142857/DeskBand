"""Math mode: every note still fits the harmony, the melodic parts stop
repeating, and switching it lands on a bar line."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.music import Composer, Sequence, euclid

MELODIC = ["cup", "pen", "laptop", "cell phone", "headphones"]
BARS = 64


def play(composer, bars):
    """-> {part: [tuple of (step, midi) for each bar]}, plus out-of-key count."""
    per, bad = {}, 0
    for step in range(C.STEPS_PER_BAR * bars):
        for part, voice, m, *_ in composer.step(step):
            if voice == "drums" or part == "backing":
                continue
            if m % 12 not in C.PENTATONIC and m % 12 not in composer.chords[composer.chord_index].pcs:
                bad += 1
            bar = per.setdefault(part, [[] for _ in range(bars)])[step // C.STEPS_PER_BAR]
            bar.append((step % C.STEPS_PER_BAR, m))
    return {p: [tuple(b) for b in bars_] for p, bars_ in per.items()}, bad


def test_math():
    assert euclid(3, 8) == [0, 3, 6]                     # the 3-3-2 of config.ACCENTS
    assert euclid(2, 4) == [0, 2] and euclid(0, 8) == [] and euclid(4, 16, 1) == [1, 5, 9, 13]

    s = Sequence("cup")
    xs = [s.chaos() for _ in range(5000)]
    assert all(0 <= x < 1 for x in xs) and 0.4 < sum(xs) / len(xs) < 0.6       # spread evenly
    assert len(set(round(s.contour(), 12) for _ in range(5000))) == 5000        # never the same twice

    patterned, bad = play(Composer(), BARS)
    assert bad == 0
    c = Composer()
    c.set_math(True)
    computed, bad = play(c, BARS)
    assert bad == 0
    for part in ("pen", "laptop"):                       # these cycle when patterned
        assert len(set(computed[part])) > 2 * len(set(patterned[part])), part
    for part in MELODIC:                                  # no four-bar stretch ever comes back
        windows = [tuple(computed[part][i:i + 4]) for i in range(BARS - 3)]
        assert len(set(windows)) >= len(windows) - 1, part

    # switching mid-bar changes nothing until the next bar line
    c = Composer()
    for step in range(C.STEPS_PER_BAR + 5):
        c.step(step)
    planned = {n: dict(p.bar) for n, p in c.parts.items()}
    c.set_math(True)
    for step in range(C.STEPS_PER_BAR + 5, 2 * C.STEPS_PER_BAR):
        c.step(step)
    assert {n: p.bar for n, p in c.parts.items()} == planned
    assert c.bar_view.math is False                       # the UI's view of the bar: still patterned...
    c.step(2 * C.STEPS_PER_BAR)
    assert c.bar_view.math is True                        # ...until the bar line
    assert c.bar_view.onsets == {n: tuple(sorted(p.bar)) for n, p in c.parts.items()}
    assert c.computed == set(MELODIC)                     # the parts that wear math mode's ring
    c.set_math()
    assert c.math is False


if __name__ == "__main__":
    test_math()
    print("ok")
