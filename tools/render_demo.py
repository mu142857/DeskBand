"""Render the band offline to a WAV: parts enter one phrase at a time.
Usage: render_demo.py out.wav"""

import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.music import Composer
from deskband.synth import Engine

# object entering at each phrase (2 bars); None = nothing new
SCRIPT = [None, "cup", "pen", "bottle", "book", "lamp", "cell phone", "laptop",
          None, None, "-book", "-laptop", "-lamp", None]


def main(out_path):
    engine = Engine(Composer())
    engine.load_instruments()
    frames = C.BLOCK_SIZE
    phrase_samples = engine.step_len * C.STEPS_PER_PHRASE
    blocks_per_phrase = phrase_samples // frames + 1
    audio, times = [], []
    for phrase, change in enumerate(SCRIPT):
        if change:
            if change.startswith("-"):
                engine.set_active(change[1:], False)
            else:
                engine.set_active(change, True)
        for _ in range(blocks_per_phrase):
            out = np.zeros((frames, 2), np.float32)
            t = time.perf_counter()
            engine._callback(out, frames, None, None)
            times.append(time.perf_counter() - t)
            audio.append(out.copy())
    a = np.concatenate(audio)
    budget = frames / C.SAMPLE_RATE
    times = np.array(times) / budget
    print(f"rendered {len(a) / C.SAMPLE_RATE:.1f}s  peak {np.abs(a).max():.2f}  "
          f"cpu mean {times.mean() * 100:.0f}%  p99 {np.percentile(times, 99) * 100:.0f}%  max {times.max() * 100:.0f}%")
    sf.write(out_path, a, C.SAMPLE_RATE)
    print("wrote", out_path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.wav")
