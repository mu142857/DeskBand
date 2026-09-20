"""SampleVoice must reproduce its buffer exactly, across block boundaries."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens.synth import SampleVoice


def play(voice, total, block=1024, first_offset=0):
    chunks, n = [], first_offset
    chunks.append(np.zeros((first_offset, 2), np.float32))
    while n < total:
        k = min(block - (n % block) if n % block else block, total - n)
        chunks.append(voice.render(k))
        n += k
    return np.concatenate(chunks)


def make_buf(n=20000):
    t = np.arange(n) / 48000
    x = (np.sin(2 * np.pi * 220 * t) * np.exp(-t * 3)).astype(np.float32)
    return np.stack([x, x * 0.5], axis=1)


def test_unity_ratio_is_bit_exact():
    buf = make_buf()
    got = play(SampleVoice(buf, 1.0, 1.0, 0), 12000, first_offset=300)
    assert np.abs(got[300:12000] - buf[:11700]).max() < 1e-7


def test_pitched_matches_interp():
    buf = make_buf()
    ratio = 2 ** (2 / 12)
    got = play(SampleVoice(buf, ratio, 1.0, 0), 9000)
    pos = np.arange(9000) * ratio
    want = np.interp(pos, np.arange(len(buf)), buf[:, 0])
    assert np.abs(got[:, 0] - want).max() < 1e-4


if __name__ == "__main__":
    test_unity_ratio_is_bit_exact()
    test_pitched_matches_interp()
    print("ok")
