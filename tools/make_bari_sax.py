#!/usr/bin/env python3
"""
make_bari_sax.py - per-note samples of Logic Pro's Studio Horns "Studio Baritone
Sax": one mono WAV per sampled root (every whole tone, 36..78, C3 = 60) plus
keymap.json, the folder wavelens/sampler.py reads as the "sax" voice.

    make_bari_sax.py [--out cache/bari_sax] [--velocity 96] [--seconds 4]

Studio Horns keeps each sustained note in two zones of the same recording: the
"Baritone Sustain" zone is only the first ~35 ms (the tongued attack) and the
"Baritone Sustain Dest" zone of the same name starts ~85 ms in and runs to the
end (the note a legato transition arrives at; it begins mid-waveform). Neither
is a playable note alone, so this reads from the start of the one to the end of
the other. exs_extract.py --verify on the Dest group: all 22 roots within 13 cents.
"""

import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exs_extract as X

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGIC = "/Library/Application Support/Logic"
EXS = f"{LOGIC}/Sampler Instruments/Studio Horns/Single Instruments/Studio Baritone Sax.exs"
CAF_DIR = f"{LOGIC}/EXS Factory Samples/Studio Horns"
ATTACK, BODY = "Baritone Sustain", "Baritone Sustain Dest"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "cache", "bari_sax"))
    ap.add_argument("--velocity", type=int, default=96, help="dynamic layer: the one covering this velocity")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--fade-ms", type=float, default=60.0)
    a = ap.parse_args()

    inst = X.Instrument(EXS)
    X.resolve_audio(inst, CAF_DIR, os.path.join(a.out, "_decoded"))
    group = {g.name: i for i, g in enumerate(inst.groups)}
    layer = lambda z: z.vello <= a.velocity <= z.velhi
    attacks = {z.root: z for z in inst.zones if z.group == group[ATTACK] and layer(z)}
    bodies = {z.root: z for z in inst.zones if z.group == group[BODY] and layer(z)}
    os.makedirs(a.out, exist_ok=True)
    keymap = []
    for root in sorted(bodies):
        body, att = bodies[root], attacks.get(root)
        start = att.start if att is not None and att.name == body.name and 0 < body.start - att.start < 22050 else body.start
        pcm = inst.samples[body.sample].pcm_path
        x, rate = X.read_frames(pcm, start, min(body.end - start, int(a.seconds * 44100)))
        x = x[:, 0].astype(np.float32) / 32768.0
        n = int(a.fade_ms / 1000 * rate)
        x[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
        sf.write(os.path.join(a.out, f"{root}.wav"), x, rate, subtype="PCM_16")
        keymap.append(dict(midi=root, root=root, file=f"{root}.wav", zone=body.name, vello=body.vello, velhi=body.velhi,
                           src_start=start, with_attack=start != body.start, frames=len(x), rate=rate))
        print(f"{root:3d}  {body.name:22s} {len(x) / rate:4.1f}s  {'attack+body' if start != body.start else 'body only'}")
    with open(os.path.join(a.out, "keymap.json"), "w") as f:
        json.dump(keymap, f, indent=1)
    print(f"wrote {len(keymap)} notes to {a.out}")


if __name__ == "__main__":
    main()
