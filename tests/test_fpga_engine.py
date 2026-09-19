"""FPGA event scheduling enters the audio callback at exact sample offsets."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.synth import Engine


class FakeComposer:
    def __init__(self):
        self.steps = []

    def step(self, step):
        self.steps.append(step)
        return [("cup", "keys", 60, 0.5, 1, 0.0)]


def test_fpga_engine():
    composer = FakeComposer()
    engine = Engine(composer)
    engine.set_bpm(120)
    engine.set_active("cup", True)
    triggered = []
    engine._trigger = lambda event, offset: triggered.append((event[0], engine.pos + offset))
    engine.set_fpga_mode(True, lookahead_steps=2)
    engine.queue_fpga_event(10, 10, 0x01, 0x01)
    engine.queue_fpga_event(11, 11, 0x02, 0x7f)  # hardware gate excludes cup
    engine.set_fpga_mode(True, lookahead_steps=2)  # bridge renewal must not clear queued events

    for _ in range(20):
        out = np.zeros((C.BLOCK_SIZE, 2), np.float32)
        engine._callback(out, C.BLOCK_SIZE, None, None)

    assert composer.steps == [10, 11]
    assert triggered == [("cup", 2 * engine.step_len)]
    engine.set_fpga_controls([255] * 7, [0, 1, 2, 3, 4, 5, 6])
    assert engine.fpga_controls[1][-1] == 6
    engine.set_fpga_mode(False)
    assert engine.next_step_at == engine.pos


if __name__ == "__main__":
    test_fpga_engine()
    print("PASS: FPGA-to-audio lookahead scheduling")
