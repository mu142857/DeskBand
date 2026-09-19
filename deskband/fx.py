"""Hall reverb (Schroeder/Freeverb topology) vectorised per sub-block.
All delay lines are longer than the sub-block, so each stage is a slice read,
one short IIR for damping, and a slice write - no per-sample Python."""

import numpy as np
from scipy.signal import lfilter

from . import config as C

SUB = 256   # every delay below must be > SUB samples


class Delay:
    def __init__(self, n):
        self.buf = np.zeros(n, np.float32)
        self.n = n
        self.i = 0

    def read(self, k):
        i, n = self.i, self.n
        if i + k <= n:
            return self.buf[i:i + k]
        return np.concatenate([self.buf[i:], self.buf[: i + k - n]])

    def write(self, x):
        i, n, k = self.i, self.n, len(x)
        if i + k <= n:
            self.buf[i:i + k] = x
        else:
            self.buf[i:] = x[: n - i]
            self.buf[: i + k - n] = x[n - i:]
        self.i = (i + k) % n


class Comb:
    def __init__(self, n, feedback, damp):
        self.d = Delay(n)
        self.fb, self.damp = feedback, damp
        self.z = np.zeros(1)

    def process(self, x):
        out = self.d.read(len(x))
        filt, self.z = lfilter([1 - self.damp], [1, -self.damp], out, zi=self.z)
        self.d.write(x + filt.astype(np.float32) * self.fb)
        return out


class Allpass:
    def __init__(self, n, g=0.5):
        self.d = Delay(n)
        self.g = g

    def process(self, x):
        delayed = self.d.read(len(x))
        self.d.write(x + delayed * self.g)
        return delayed - x


class Reverb:
    COMBS_L = [1116, 1188, 1277, 1356]
    COMBS_R = [1422, 1491, 1557, 1617]
    ALLPASS_L = [556, 441]
    ALLPASS_R = [579, 464]

    def __init__(self):
        p = C.REVERB
        fb = 0.7 + 0.28 * p["room"]
        self.pre = Delay(max(SUB + 1, int(p["predelay_ms"] / 1000 * C.SAMPLE_RATE)))
        self.cl = [Comb(n, fb, p["damp"]) for n in self.COMBS_L]
        self.cr = [Comb(n, fb, p["damp"]) for n in self.COMBS_R]
        self.al = [Allpass(n) for n in self.ALLPASS_L]
        self.ar = [Allpass(n) for n in self.ALLPASS_R]
        self.wet = p["wet"]
        self.lp = np.zeros(1)

    def process(self, send):
        """send: mono float32 (n,) -> stereo (n, 2) wet signal."""
        out = np.empty((len(send), 2), np.float32)
        for s in range(0, len(send), SUB):
            x = send[s:s + SUB]
            # soften the input: reverb tails should not be bright
            x, self.lp = lfilter([0.35], [1, -0.65], x, zi=self.lp)
            x = x.astype(np.float32)
            delayed = self.pre.read(len(x))     # read before write = full delay
            self.pre.write(x)
            x = delayed
            l = sum(c.process(x) for c in self.cl) * 0.25
            r = sum(c.process(x) for c in self.cr) * 0.25
            for a in self.al:
                l = a.process(l)
            for a in self.ar:
                r = a.process(r)
            out[s:s + SUB, 0] = l
            out[s:s + SUB, 1] = r
        return out * self.wet
