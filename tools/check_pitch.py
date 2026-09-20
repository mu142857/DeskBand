"""Sanity check: does each sample's measured pitch match the MIDI note we
read from its file name? Run once after adding a sample set."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import config as C
from wavelens import sampler


def main():
    kinds = sys.argv[1:] or list(C.SAMPLE_SETS)
    for kind in kinds:
        km = sampler.load_set(kind)
        bad = 0
        print(f"== {kind}: {len(km.keys)} samples, midi {km.keys.min()}..{km.keys.max()}")
        for midi in km.keys:
            est = sampler.estimate_midi(km.notes[midi])
            if est is None:
                print(f"   {midi:3d}  ?    {os.path.basename(km.files[midi])}")
                continue
            diff = est - midi
            flag = "" if abs(diff) < 0.6 else "  <-- MISMATCH"
            if flag:
                bad += 1
            print(f"   {midi:3d}  measured {est:6.2f}  diff {diff:+5.2f}{flag}   {os.path.basename(km.files[midi])}")
        print(f"   mismatches: {bad}")


if __name__ == "__main__":
    main()
