"""Write INSTRUMENTS.txt: which object plays which instrument, from which files."""

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C


def main():
    lines = ["DeskBand - object -> instrument -> sample files", ""]
    lines.append(f"Tempo {C.BPM} BPM, chords " + " - ".join(n for n, _ in C.CHORDS)
                 + f" ({C.BARS_PER_CHORD} bars each), melody notes from C major pentatonic.")
    lines.append("")
    for obj, spec in C.INSTRUMENTS.items():
        lines.append(f"[{obj}]  ->  {spec['label']}   (voice: {spec['voice']}, register MIDI {spec['lo']}-{spec['hi']})")
        kind = spec["voice"]
        if kind == "piano" and os.path.exists(os.path.join(C.CONCERT_GRAND, "keymap.json")):
            lines.append(f"    Concert Grand Piano, unpacked from Logic's EXS instrument into {C.CONCERT_GRAND}/")
            lines.append(f"    source: {C.LIB_LOGIC}/Studio Piano/Concert Grand Piano/*.caf")
        if kind in C.SAMPLE_SETS:
            s = C.SAMPLE_SETS[kind]
            files = sorted(glob.glob(os.path.join(s["dir"], s["glob"])))
            if s.get("exclude"):
                files = [f for f in files if s["exclude"] not in os.path.basename(f)]
            lines.append(f"    dir:   {s['dir']}")
            lines.append(f"    files: {s['glob']}  ({len(files)} files)")
            for f in files:
                lines.append(f"        {os.path.basename(f)}")
        elif kind == "drums":
            lines.append(f"    dir:   {C.DRUM_DIR}")
            for hit, fn in C.DRUMS.items():
                lines.append(f"        {hit:9s} {fn}")
        elif kind == "arp":
            lines.append("    synthesized in deskband/synth.py (detuned saw + lowpass pluck), no samples")
        lines.append("")
    lines.append("[backing, always on]")
    lines.append(f"    vinyl noise loop: {C.VINYL_LOOP}  (decoded to cache/vinyl.wav)")
    lines.append(f"    shaker / rim from the Trap Heat kit above; sub bass synthesized")
    lines.append(f"    reverb: Schroeder hall in deskband/fx.py, room {C.REVERB['room']}, damp {C.REVERB['damp']}")
    lines.append("")
    lines.append("Sound library: Apple Logic Pro / GarageBand factory content on this Mac.")
    lines.append("Samples are read in place and never copied into the repo.")
    path = os.path.join(C.ROOT, "INSTRUMENTS.txt")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main()
