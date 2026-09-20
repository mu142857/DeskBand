"""Copy the factory samples WaveLens uses into samples/, so the band still
plays when the disk holding the Logic / GarageBand libraries is unplugged.

  python tools/copy_samples.py

Run it once with the libraries reachable. Only the files named in config.py are
copied (a few hundred MB at most), not the whole library."""

import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wavelens import config as C


def wanted():
    """-> {kind: [source paths]}"""
    out = {}
    for kind, spec in C.SAMPLE_SETS.items():
        files = []
        for path in sorted(glob.glob(os.path.join(spec["dir"], spec["glob"]))):
            if spec.get("exclude") and spec["exclude"] in os.path.basename(path):
                continue
            files.append(path)
            if "pair" in spec:
                files.append(path.replace(*spec["pair"]))
        out[kind] = files
    out["drums"] = [p for p in (os.path.join(C.DRUM_DIR, fn) for fn in C.DRUMS.values()) if os.path.exists(p)]
    return out


def main():
    missing = []
    for kind, files in wanted().items():
        if not files:
            missing.append(kind)
            continue
        dest = os.path.join(C.LOCAL_SAMPLES, kind)
        tmp = dest + ".part"                   # a half-copied folder must never win over the library
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for path in files:
            shutil.copy2(path, tmp)
        shutil.rmtree(dest, ignore_errors=True)
        os.rename(tmp, dest)
        size = sum(os.path.getsize(f) for f in files) / 1e6
        print(f"{kind}: {len(files)} files, {size:.0f} MB -> {dest}")
    if missing:
        print("not found (is the sample disk plugged in?):", ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
