"""The block-vectorised reverb must match a plain sample-by-sample version."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.fx import Reverb


def reference(x):
    """Same topology as fx.Reverb, one sample at a time."""
    rv = Reverb()                       # only used for its parameters
    p = C.REVERB
    fb = 0.7 + 0.28 * p["room"]
    damp = p["damp"]
    out = np.zeros((len(x), 2))
    lp = 0.0
    pre = np.zeros(rv.pre.n)
    pi = 0
    sides = []
    for combs, alls in ((rv.cl, rv.al), (rv.cr, rv.ar)):
        sides.append(dict(cb=[np.zeros(c.d.n) for c in combs], ci=[0] * len(combs), cz=[0.0] * len(combs),
                          ab=[np.zeros(a.d.n) for a in alls], ai=[0] * len(alls)))
    for n, s in enumerate(x):
        lp = 0.35 * s + 0.65 * lp
        d = pre[pi]; pre[pi] = lp; pi = (pi + 1) % len(pre)
        for ch, sd in enumerate(sides):
            acc = 0.0
            for j, buf in enumerate(sd["cb"]):
                y = buf[sd["ci"][j]]
                sd["cz"][j] = (1 - damp) * y + damp * sd["cz"][j]
                buf[sd["ci"][j]] = d + sd["cz"][j] * fb
                sd["ci"][j] = (sd["ci"][j] + 1) % len(buf)
                acc += y
            v = acc * rv.norm
            for j, buf in enumerate(sd["ab"]):
                y = buf[sd["ai"][j]]
                buf[sd["ai"][j]] = v + y * 0.5
                sd["ai"][j] = (sd["ai"][j] + 1) % len(buf)
                v = y - v
            out[n, ch] = v * rv.wet
    return out


def test_matches_reference():
    rng = np.random.default_rng(1)
    n = C.BLOCK_SIZE * 12
    x = np.zeros(n, np.float32)
    x[:4000] = rng.uniform(-0.5, 0.5, 4000).astype(np.float32)     # noise burst, then tail
    rv = Reverb()
    got = np.concatenate([rv.process(x[i:i + C.BLOCK_SIZE]) for i in range(0, n, C.BLOCK_SIZE)])
    want = reference(x)
    err = np.abs(got - want).max()
    print(f"max |block - reference| = {err:.2e}   (signal peak {np.abs(want).max():.3f})")
    assert err < 1e-4, err


if __name__ == "__main__":
    test_matches_reference()
    print("ok")
