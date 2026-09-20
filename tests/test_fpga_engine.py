"""FPGA event scheduling enters the audio callback at exact sample offsets, and
the clock stays at bar one until the app starts it."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import config as C
from wavelens.synth import Engine


class FakeComposer:
    def __init__(self):
        self.steps = []
        self.bar_view = None
        self.generated = []

    def step(self, step):
        self.steps.append(step)
        return [("cup", "keys", 60, 0.5, 1, 0.0)]

    def rhythmic_events(self, name, step):
        self.generated.append((name, step))
        return [(name, "keys", 64, 0.3, 1, 0.0)]


def blocks(engine, n):
    for _ in range(n):
        engine._callback(np.zeros((C.BLOCK_SIZE, 2), np.float32), C.BLOCK_SIZE, None, None)


def test_silent_until_started():
    """Nothing is played while the app loads; the first step is step 0."""
    composer = FakeComposer()
    engine = Engine(composer)
    engine.set_bpm(120)
    blocks(engine, 200)                                    # several bars' worth of loading
    assert composer.steps == []
    assert 0 <= engine.cpu < 10                         # callback diagnostic is a duration ratio
    engine.start_transport()
    blocks(engine, 20)
    assert composer.steps and composer.steps[0] == 0       # in at the top of the loop, not mid-bar
    assert composer.steps == list(range(len(composer.steps)))


def test_fpga_engine():
    composer = FakeComposer()
    engine = Engine(composer)
    engine.set_bpm(120)
    engine.start_transport()
    engine.set_active("cup", True)
    triggered = []
    engine._trigger = lambda event, offset: triggered.append((event[0], engine.pos + offset))
    engine.set_fpga_mode(True, lookahead_steps=2)
    engine.queue_fpga_event(10, 10, 0x01, 0x01)
    engine.queue_fpga_event(11, 11, 0x00, 0x7f)  # hardware gate excludes cup
    engine.queue_fpga_event(12, 12, 0x02, 0x7f)  # hardware creates a pen onset
    engine.set_fpga_mode(True, lookahead_steps=2)  # bridge renewal must not clear queued events

    for _ in range(30):
        out = np.zeros((C.BLOCK_SIZE, 2), np.float32)
        engine._callback(out, C.BLOCK_SIZE, None, None)

    assert composer.steps == [10, 11, 12]
    assert composer.generated == [("pen", 12)]
    assert triggered == [("cup", 2 * engine.step_len), ("pen", 4 * engine.step_len)]

    # Transport reset and restarted (pause/play, a new photo): ticks start again
    # from 0 and must be scheduled ahead of now again, not in the past.
    del triggered[:]
    restart = engine.pos
    engine.queue_fpga_event(0, 0, 0x01, 0x01)
    engine.queue_fpga_event(1, 1, 0x01, 0x01)
    for _ in range(20):
        engine._callback(np.zeros((C.BLOCK_SIZE, 2), np.float32), C.BLOCK_SIZE, None, None)
    assert triggered == [("cup", restart + 2 * engine.step_len), ("cup", restart + 3 * engine.step_len)]

    # Stopped and started without a reset: the count carries on after a long gap.
    del triggered[:]
    for _ in range(100):                                   # a couple of seconds of silence
        engine._callback(np.zeros((C.BLOCK_SIZE, 2), np.float32), C.BLOCK_SIZE, None, None)
    resume = engine.pos
    engine.queue_fpga_event(2, 2, 0x01, 0x01)
    for _ in range(20):
        engine._callback(np.zeros((C.BLOCK_SIZE, 2), np.float32), C.BLOCK_SIZE, None, None)
    assert triggered == [("cup", resume + 2 * engine.step_len)]
    engine.set_fpga_controls([255] * 7, [0, 1, 2, 3, 4, 5, 6])
    assert engine.fpga_controls[1][-1] == 6
    engine.set_fpga_mode(False)
    assert engine.next_step_at == engine.pos


def test_lost_bar_line():
    """A tick lost between the board and the engine must not skip the bar line,
    or the chord would not move on and the old bar would play again."""
    composer = FakeComposer()
    engine = Engine(composer)
    engine.set_bpm(120)
    engine.start_transport()
    engine.set_active("cup", True)
    engine._trigger = lambda event, offset: None
    engine.set_fpga_mode(True, lookahead_steps=2)
    for tick in (13, 14, 15, 17, 18):                      # 16, the downbeat, never arrives
        engine.queue_fpga_event(tick, tick % 16, 0x01, 0x01)
        blocks(engine, 6)
    blocks(engine, 30)
    assert composer.steps == [13, 14, 15, 16, 17, 18]


if __name__ == "__main__":
    test_lost_bar_line()
    test_silent_until_started()
    test_fpga_engine()
    print("PASS: FPGA-to-audio lookahead scheduling")
