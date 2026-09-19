#!/usr/bin/env python3
"""
make_kings_cross.py - build a per-note sample set of the Logic Pro Studio
Strings "String Ensemble" (the sound behind the "King's Cross" patch): one
stereo WAV per MIDI note with all five string sections layered.

    make_kings_cross.py [--out cache/kings_cross] [--lo 36] [--hi 96] [--seconds 7]

    --out DIR         output folder (default <project>/cache/kings_cross)
    --lo / --hi       MIDI note range, every semitone (default 36..96)
    --seconds S       length of every note (default 7.0)
    --fade-ms MS      fade-out at the end of every note (default 60)
    --peak P          peak of the loudest note after the one global gain (0.9)
    --no-loop         do not extend a section with its sustain loop; it then
                      ends (with its own fade) where its recording ends
    --no-pan          ignore the instrument's per-section pan positions
    --dedupe          where two sections would play the very same recording
                      (see below) give the second one another root instead
    --dest            use the "<Section> Sustain Dest" groups (see below)
    --fade-in-ms MS   fade-in at the start of every note (default 0)
    --no-verify       skip the checks that are run on the written files
    --verify-only     only run the checks on an existing output folder

What it does
  * Sections: the "<Section> Sustain" groups of String Ensemble.exs (Violin 1,
    Violin 2, Viola, Cello, CBass): the full recordings, bow attack included.
    The "<Section> Sustain Dest" groups point into the very same audio but
    start 10328-10857 frames (about 235 ms) later and so skip the attack; they
    are the notes a legato transition arrives at and begin mid-waveform (use
    --dest together with --fade-in-ms 30 or so if that is what you want).
    Because both groups overlap in the CAF, the group table of
    `exs_extract.py --list` (which cuts a zone at the next zone start) shows
    the plain groups with next to no audio; their zones are in fact 5-8 s long.
    "Sustain Acc" are accented sustains and are not used.
  * Dynamic: the middle one of the three velocity layers (mf, velocity 49-96;
    61-96 in the Dest groups); a root with another layer count uses the layer
    covering velocity 60.
  * A section contributes to a note only inside its sampled range (lowest to
    highest root; in the file the outermost zones are open ended, 0 / 127).
    The zone whose key range covers the note is read from the consolidated
    CAF and repitched by resampling: shift = (note - root) + fine tune.
  * Every section keeps its natural attack, zone start = sample 0.
  * Zone and group volume (dB) and the group pan of the instrument are applied,
    so the balance between the sections is the one the instrument was built
    with.  Pan is applied as a constant-power stereo balance.
  * The zones carry baked sustain loops (loop on, crossfade 0).  A section
    whose recording is shorter than the note is continued through its loop,
    exactly as the sampler does while a key is held (the double basses are
    only 4.4-5.2 s long).
  * Violin 1 and Violin 2 share the recordings of six roots (74, 82, 85, 90,
    93, 96: the same take in both CAFs).  On the 14 notes they cover the two
    violin sections are one recording at twice the level (and, with the two
    pans cancelling, in the centre); that is what the
    instrument itself plays, so it is kept by default and listed in the log.
    With --dedupe the second section takes the nearest other root of its own
    group for those notes instead (2-3 semitones of repitch).
  * One global gain for the whole set; 16-bit 44.1 kHz stereo WAV; keymap.json
    = [{midi, file, sections, root_shift, ...}].
  * Afterwards the written files are checked: pitch, peak, silence, attack
    time, neighbour balance, size on disk.
"""

import argparse
import json
import math
import os
import struct
import sys
import time
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import correlate, resample_poly

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import exs_extract as exs  # noqa: E402

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXS_PATH = ("/Library/Application Support/Logic/Sampler Instruments/Studio Strings/"
            "Section Instruments/String Ensemble.exs")
CAF_DIR = "/Library/Application Support/Logic/EXS Factory Samples/Studio Strings"

# (name used in keymap.json, exact group name in the instrument; --dest appends " Dest")
SECTIONS = [
    ("violin1", "Violin 1 Sustain"),
    ("violin2", "Violin 2 Sustain"),
    ("viola", "Viola Sustain"),
    ("cello", "Cello Sustain"),
    ("bass", "CBass Sustain"),
]
TARGET_VELOCITY = 60


# --------------------------------------------------------------------------- #
#  Instrument access
# --------------------------------------------------------------------------- #
class Section:
    def __init__(self, inst, name, group_name, zone_chunks):
        hits = [i for i, g in enumerate(inst.groups) if g.name == group_name]
        if len(hits) != 1:
            raise SystemExit("group %r found %d times in the instrument" % (group_name, len(hits)))
        self.name, self.group_name, self.group = name, group_name, hits[0]
        body = inst.groups[self.group].body
        self.volume, self.pan = struct.unpack_from("bb", body, 0)    # dB, -100 .. +100
        by_root = exs.layers_by_note([z for z in inst.zones if z.group == self.group])
        self.zones = []
        self.layers = set()
        for root, zs in sorted(by_root.items()):
            if len(zs) == 3:
                z = zs[1]
            else:
                cover = [w for w in zs if w.vello <= TARGET_VELOCITY <= w.velhi]
                z = cover[0] if cover else zs[len(zs) // 2]
            z.loop_on = bool(zone_chunks[z.index].body[33] & 1) and z.loop_end > z.loop_start
            self.zones.append(z)
            self.layers.add((z.vello, z.velhi))
        self.lo = min(z.root for z in self.zones)
        self.hi = max(z.root for z in self.zones)

    def zone_for(self, note):
        if not (self.lo <= note <= self.hi):
            return None
        hits = [z for z in self.zones if z.keylo <= note <= z.keyhi]
        if not hits:
            return None
        return min(hits, key=lambda z: abs(z.root - note))

    def other_zone_for(self, note, avoid):
        """nearest root of this section other than `avoid` (ties: the lower root)"""
        cands = [z for z in self.zones if z is not avoid]
        return min(cands, key=lambda z: (abs(z.root - note), z.root)) if cands else None


class ZoneReader:
    """zone audio as float32, optionally continued through the sustain loop"""

    def __init__(self, inst):
        self.inst = inst
        self.cache = {}

    def raw(self, z):
        if z.index not in self.cache:
            s = self.inst.samples[z.sample]
            end = min(z.end, s.frames or z.end)
            pcm, rate = exs.read_frames(s.pcm_path, z.start, end - z.start)
            if rate != 44100 or pcm.shape[1] != 2:
                raise SystemExit("%s: expected 44.1 kHz stereo" % s.pcm_path)
            self.cache[z.index] = pcm.astype(np.float32) / 32768.0
        return self.cache[z.index]

    def frames(self, z, n, use_loop):
        """-> (audio with at most n frames, looped?)"""
        x = self.raw(z)
        if len(x) >= n:
            return x[:n], False
        if not (use_loop and z.loop_on):
            return x, False
        ls, le = z.loop_start - z.start, min(z.loop_end - z.start, len(x))
        if le - ls < 64:
            return x, False
        loop = x[ls:le]
        reps = int(math.ceil((n - le) / float(len(loop))))
        return np.concatenate([x[:le]] + [loop] * reps)[:n], True


def same_recording(a, b, rate, seconds=1.5, max_lag=4410):
    """do two zones hold the same take (possibly offset by a few ms)?"""
    n = min(len(a), len(b), int(seconds * rate))
    am, bm = a[:n].mean(axis=1), b[:n].mean(axis=1)
    den = float(np.linalg.norm(am) * np.linalg.norm(bm)) + 1e-12
    c = correlate(am, bm, mode="full", method="fft")
    mid = n - 1
    c = np.abs(c[mid - max_lag:mid + max_lag + 1]) / den
    k = int(np.argmax(c))
    return float(c[k]), k - max_lag


# --------------------------------------------------------------------------- #
#  DSP
# --------------------------------------------------------------------------- #
def ratio_for(shift_semitones, max_err_cents=0.3):
    """up/down for resample_poly such that the pitch rises by shift_semitones"""
    target = 2.0 ** (-shift_semitones / 12.0)          # output length / input length
    for max_den in (16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192):
        fr = Fraction(target).limit_denominator(max_den)
        if abs(1200.0 * math.log2(float(fr) / target)) <= max_err_cents:
            break
    return fr.numerator, fr.denominator


def repitch(x, shift_semitones):
    if abs(shift_semitones) < 0.015:                   # under 1.5 cents: leave untouched
        return x, (1, 1)
    up, down = ratio_for(shift_semitones)
    y = resample_poly(x.astype(np.float64), up, down, axis=0)
    return y.astype(np.float32), (up, down)


def pan_gains(pan):
    """constant-power stereo balance, unity at centre; pan in -100..+100"""
    p = max(-1.0, min(1.0, pan / 100.0))
    th = (p + 1.0) * math.pi / 4.0
    return math.sqrt(2.0) * math.cos(th), math.sqrt(2.0) * math.sin(th)


def fade_out(x, nf):
    nf = min(nf, len(x))
    if nf > 0:
        ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, nf, endpoint=False)))   # 1 -> 0
        x[-nf:] *= ramp[:, None].astype(x.dtype)
    return x


def db(v):
    return 20.0 * math.log10(max(float(v), 1e-12))


# --------------------------------------------------------------------------- #
#  Build
# --------------------------------------------------------------------------- #
def build_note(note, sections, reader, n_out, fade_n, args, log):
    rate = 44100
    picks = []
    for sec in sections:
        z = sec.zone_for(note)
        if z is not None:
            picks.append([sec, z, False])

    duplicates = []
    for i in range(len(picks)):
        for j in range(i + 1, len(picks)):
            (sa, za, _), (sb, zb, _) = picks[i], picks[j]
            if za.root != zb.root:
                continue
            c, lag = same_recording(reader.raw(za), reader.raw(zb), rate)
            if c < 0.9:
                continue
            line = "note %d: %s and %s hold the same take (%r, xcorr %.3f, offset %d frames)" % (
                note, sa.name, sb.name, zb.name, c, lag)
            alt = sb.other_zone_for(note, zb) if args.dedupe else None
            if alt is not None:
                line += " -> %s uses root %d instead of %d" % (sb.name, alt.root, zb.root)
                picks[j] = [sb, alt, True]
            else:
                duplicates.append([sa.name, sb.name])
            log.append(line)

    mix = np.zeros((n_out, 2), dtype=np.float32)
    info = dict(midi=note, file="%d.wav" % note, sections=[], root_shift={}, roots={},
                shift_cents={}, gain_db={}, looped=[], substituted=[], same_take=duplicates)
    for sec, z, substituted in picks:
        shift = (note - z.root) + z.coarse + z.fine / 100.0
        n_in = int(math.ceil(n_out * 2.0 ** (shift / 12.0))) + 64
        x, looped = reader.frames(z, n_in, not args.no_loop)
        natural_end = len(x) < n_in
        y, _ = repitch(x, shift)
        y = y[:n_out].copy()
        if natural_end and len(y) < n_out:              # the section stops before the note does
            fade_out(y, fade_n)
        gain_db = sec.volume + z.volume
        g = 10.0 ** (gain_db / 20.0)
        gl, gr = (1.0, 1.0) if args.no_pan else pan_gains(sec.pan + z.pan)
        mix[:len(y), 0] += y[:, 0] * (g * gl)
        mix[:len(y), 1] += y[:, 1] * (g * gr)
        info["sections"].append(sec.name)
        info["root_shift"][sec.name] = note - z.root
        info["roots"][sec.name] = z.root
        info["shift_cents"][sec.name] = round(shift * 100.0, 1)
        info["gain_db"][sec.name] = gain_db
        if looped:
            info["looped"].append(sec.name)
        if substituted:
            info["substituted"].append(sec.name)
    fade_out(mix, fade_n)
    fin = min(int(round(args.fade_in_ms * rate / 1000.0)), n_out)
    if fin > 0:
        mix[:fin] *= (0.5 * (1 - np.cos(np.linspace(0, np.pi, fin, endpoint=False))))[:, None].astype(mix.dtype)
    return mix, info


# --------------------------------------------------------------------------- #
#  Verification (runs on the written files)
# --------------------------------------------------------------------------- #
def pitch_acf(mono, rate, t0=0.5, t1=2.0, fmin=28.0, fmax=5000.0):
    """blind autocorrelation estimate of the fundamental over t0..t1"""
    seg = mono[int(t0 * rate):int(t1 * rate)].astype(np.float64)
    if len(seg) < 0.5 * rate:
        return float("nan")
    seg = seg - seg.mean()
    n = len(seg)
    spec = np.fft.rfft(seg, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    if ac[0] <= 0:
        return float("nan")
    ac = ac / ac[0] * (n / (n - np.arange(n, dtype=np.float64)))     # unbiased
    neg = np.nonzero(ac < 0)[0]
    lo = max(int(rate / fmax), int(neg[0]) if len(neg) else 2, 2)
    hi = min(int(rate / fmin) + 1, n // 2)
    if hi <= lo + 2:
        return float("nan")
    body = ac[lo:hi]
    gmax = body.max()
    # the first local maximum that is nearly as high as the best one (avoids sub-octaves)
    is_peak = (body[1:-1] >= body[:-2]) & (body[1:-1] > body[2:]) & (body[1:-1] >= 0.9 * gmax)
    idx = np.nonzero(is_peak)[0]
    i = lo + 1 + int(idx[0]) if len(idx) else lo + int(np.argmax(body))

    def refine(i):
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        return i + max(-1.0, min(1.0, d))

    lag = refine(i)
    k = 1
    while 2 * k * lag < 0.025 * rate:                  # sharpen on multiples of the period
        k *= 2
        c = int(round(k * lag))
        w = max(1, int(0.35 * lag))
        a, b = max(1, c - w), min(n - 2, c + w)
        j = a + int(np.argmax(ac[a:b + 1]))
        j = max(1, min(n - 2, j))
        lag = refine(j) / k
    return rate / lag


def pitch_fft(mono, rate, f_expected, t0=0.5, t1=2.0):
    """energy centroid of the partials 1..3 within +/-80 cents of where they should be"""
    seg = mono[int(t0 * rate):int(t1 * rate)].astype(np.float64)
    if len(seg) < 0.5 * rate:
        return float("nan")
    nfft = 1 << 19
    p = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft)) ** 2
    df = rate / float(nfft)
    num = den = 0.0
    for h in (1, 2, 3):
        a = int(h * f_expected * 2 ** (-80 / 1200.0) / df)
        b = int(h * f_expected * 2 ** (80 / 1200.0) / df) + 1
        if b >= len(p):
            break
        i = a + int(np.argmax(p[a:b]))
        w = max(2, int(0.006 * h * f_expected / df))            # +/-10 cents around the peak
        sl = slice(max(a, i - w), min(b, i + w + 1))
        f = (np.arange(sl.start, sl.stop) * df * p[sl]).sum() / (p[sl].sum() + 1e-30)
        e = p[sl].sum()
        num += e * 1200.0 * math.log2(f / (h * f_expected))
        den += e
    return f_expected * 2 ** (num / den / 1200.0) if den > 0 else float("nan")


def attack_times(x, rate):
    """time (ms) at which the 2 ms peak envelope first reaches 10 % / 50 % / 90 % of the note's peak"""
    blk = int(0.002 * rate)
    nb = len(x) // blk
    env = np.abs(x[:nb * blk]).max(axis=1).reshape(nb, blk).max(axis=1)
    peak = env.max()
    if peak <= 0:
        return (float("nan"),) * 3
    return tuple(1000.0 * blk * int(np.argmax(env >= f * peak)) / rate for f in (0.1, 0.5, 0.9))


def verify(out_dir, tolerance=30.0):
    keymap = json.load(open(os.path.join(out_dir, "keymap.json")))
    print("\nverification of the files in %s" % out_dir)
    print("pitch: acf = blind autocorrelation estimate over 0.5-2.0 s, fft = energy centroid of partials 1-3;")
    print("rms = level over 1.0-3.0 s; L/R = channel balance; t10/t50/t90 = time until the envelope first reaches")
    print("10/50/90 % of the note's peak\n")
    print("%4s %-5s %9s %9s %7s %7s | %6s %7s %6s | %5s %5s %5s | %s" % (
        "midi", "note", "target", "acf_Hz", "acf_c", "fft_c", "peak", "rms_dB", "L/R", "t10", "t50", "t90", "sections"))
    names = "C C# D D# E F F# G G# A A# B".split()
    rows, problems = [], []
    total = os.path.getsize(os.path.join(out_dir, "keymap.json"))
    for e in keymap:
        path = os.path.join(out_dir, e["file"])
        total += os.path.getsize(path)
        pcm, rate = sf.read(path, dtype="int16", always_2d=True)
        info = sf.info(path)
        if (info.samplerate, info.channels, info.subtype) != (44100, 2, "PCM_16"):
            problems.append("%s: not 16-bit 44.1 kHz stereo" % e["file"])
        x = pcm.astype(np.float64) / 32768.0
        mono = x.mean(axis=1)
        target = exs.midi_to_hz(e["midi"])
        fa, ff = pitch_acf(mono, rate), pitch_fft(mono, rate, target)
        ca = exs.cents(fa, target) if fa == fa and fa > 0 else float("nan")
        cf = exs.cents(ff, target) if ff == ff and ff > 0 else float("nan")
        peak = float(np.abs(x).max())
        clipped = int((np.abs(pcm.astype(np.int32)) >= 32767).sum())
        sus = x[int(1.0 * rate):int(3.0 * rate)]
        rms = db(np.sqrt((sus ** 2).mean())) if len(sus) else -200.0
        lr = db(np.sqrt((sus[:, 0] ** 2).mean())) - db(np.sqrt((sus[:, 1] ** 2).mean())) if len(sus) else 0.0
        t10, t50, t90 = attack_times(x, rate)
        flags = []
        if not (abs(ca) <= tolerance):
            flags.append("PITCH(acf)")
        if not (abs(cf) <= tolerance):
            flags.append("PITCH(fft)")
        if peak >= 1.0 or clipped:
            flags.append("CLIPPED(%d)" % clipped)
        if rms < -50.0 or peak < 0.01:
            flags.append("SILENT")
        if flags:
            problems.append("%s: %s" % (e["file"], " ".join(flags)))
        rows.append(dict(midi=e["midi"], peak=peak, rms=rms, lr=lr, t50=t50, ca=ca, cf=cf))
        print("%4d %-5s %9.2f %9.2f %+7.1f %+7.1f | %6.3f %7.1f %+6.1f | %5.0f %5.0f %5.0f | %s %s" % (
            e["midi"], names[e["midi"] % 12] + str(e["midi"] // 12 - 1), target, fa, ca, cf, peak, rms, lr,
            t10, t50, t90, "+".join(e["sections"]), " ".join(flags)))

    lo = min(rows, key=lambda r: r["peak"])
    hi = max(rows, key=lambda r: r["peak"])
    print("\npeaks: quietest note %d = %.3f (%.1f dBFS), loudest note %d = %.3f (%.1f dBFS)" % (
        lo["midi"], lo["peak"], db(lo["peak"]), hi["midi"], hi["peak"], db(hi["peak"])))
    rl = min(rows, key=lambda r: r["rms"])
    rh = max(rows, key=lambda r: r["rms"])
    print("sustain rms (1-3 s): quietest note %d = %.1f dBFS, loudest note %d = %.1f dBFS" % (
        rl["midi"], rl["rms"], rh["midi"], rh["rms"]))
    steps = [(abs(b["rms"] - a["rms"]), abs(db(b["peak"]) - db(a["peak"])), a["midi"], b["midi"])
             for a, b in zip(rows, rows[1:]) if b["midi"] - a["midi"] == 1]
    if steps:
        s = max(steps)
        p = max(steps, key=lambda t: t[1])
        print("largest step between neighbouring notes: rms %.1f dB (%d->%d), peak %.1f dB (%d->%d)" % (
            s[0], s[2], s[3], p[1], p[2], p[3]))
        for d_rms, d_peak, a, b in steps:
            if d_rms > 10.0 or d_peak > 10.0:
                problems.append("balance: %d->%d differs by %.1f dB rms / %.1f dB peak" % (a, b, d_rms, d_peak))
    worst = max(rows, key=lambda r: max(abs(r["ca"]), abs(r["cf"])) if r["ca"] == r["ca"] and r["cf"] == r["cf"] else 1e9)
    print("pitch: worst note %d (acf %+.1f c, fft %+.1f c), tolerance +/-%.0f c, %d notes checked" % (
        worst["midi"], worst["ca"], worst["cf"], tolerance, len(rows)))
    t50s = sorted(r["t50"] for r in rows)
    print("attack: t50 min %.0f ms, median %.0f ms, max %.0f ms" % (t50s[0], t50s[len(t50s) // 2], t50s[-1]))
    print("size on disk: %.1f MB in %d files + keymap.json" % (total / 1e6, len(rows)))
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  " + p)
    else:
        print("\nall checks passed")
    return not problems


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--out", default=os.path.join(PROJECT, "cache", "kings_cross"))
    ap.add_argument("--lo", type=int, default=36)
    ap.add_argument("--hi", type=int, default=96)
    ap.add_argument("--seconds", type=float, default=7.0)
    ap.add_argument("--fade-ms", type=float, default=60.0)
    ap.add_argument("--peak", type=float, default=0.9)
    ap.add_argument("--no-loop", action="store_true")
    ap.add_argument("--no-pan", action="store_true")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--dest", action="store_true")
    ap.add_argument("--fade-in-ms", type=float, default=0.0)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--exs", default=EXS_PATH)
    ap.add_argument("--caf-dir", default=CAF_DIR)
    args = ap.parse_args(argv)

    if args.verify_only:
        return 0 if verify(args.out) else 1

    t_start = time.time()
    inst = exs.Instrument(args.exs)
    exs.resolve_audio(inst, args.caf_dir, os.path.join(args.out, "_decoded"))
    zone_chunks = [c for c in inst.chunks if c.type == 1]
    sections = [Section(inst, name, group + (" Dest" if args.dest else ""), zone_chunks)
                for name, group in SECTIONS]

    print("sections (group volume / pan are applied to the mix%s):" % (", pan ignored" if args.no_pan else ""))
    for s in sections:
        layers = ", ".join("%d-%d" % l for l in sorted(s.layers))
        vols = [z.volume for z in s.zones]
        print("  %-8s group [%d] %-22s layer vel %s  roots %d..%d (%d zones, %.1f-%.1f s)  "
              "group vol %+d dB pan %+d  zone vol %+d..%+d dB" % (
                  s.name, s.group, s.group_name, layers, s.lo, s.hi, len(s.zones),
                  min(z.end - z.start for z in s.zones) / 44100.0, max(z.end - z.start for z in s.zones) / 44100.0,
                  s.volume, s.pan, min(vols), max(vols)))

    rate = 44100
    n_out = int(round(args.seconds * rate))
    fade_n = int(round(args.fade_ms * rate / 1000.0))
    reader = ZoneReader(inst)
    notes, log = [], []
    for note in range(args.lo, args.hi + 1):
        mix, info = build_note(note, sections, reader, n_out, fade_n, args, log)
        if not info["sections"]:
            print("note %d: no section covers it, skipped" % note)
            continue
        notes.append((mix, info))
    if not notes:
        raise SystemExit("nothing to write")
    if log:
        print("\nsame take in two sections:")
        for line in log:
            print("  " + line)

    peak = max(float(np.abs(m).max()) for m, _ in notes)
    gain = args.peak / peak
    print("\nglobal gain %+.2f dB (loudest raw mix peak %.3f -> %.2f)" % (db(gain), peak, args.peak))

    os.makedirs(args.out, exist_ok=True)
    old_keymap = os.path.join(args.out, "keymap.json")
    if os.path.exists(old_keymap):                     # notes of an earlier run of this script with a wider range
        try:
            old = [e for e in json.load(open(old_keymap)) if isinstance(e, dict) and "root_shift" in e]
        except ValueError:
            old = []
        keep = set(info["file"] for _m, info in notes)
        for e in old:
            path = os.path.join(args.out, os.path.basename(str(e.get("file", ""))))
            if e.get("file") not in keep and path.endswith(".wav") and os.path.isfile(path):
                os.remove(path)
    keymap = []
    for mix, info in notes:
        pcm = np.clip(np.round(mix * (gain * 32767.0)), -32768, 32767).astype(np.int16)
        sf.write(os.path.join(args.out, info["file"]), pcm, rate, subtype="PCM_16")
        info["peak"] = round(float(np.abs(mix).max()) * gain, 4)
        keymap.append(info)
    with open(os.path.join(args.out, "keymap.json"), "w") as f:
        json.dump(keymap, f, indent=1)
    print("wrote %d notes (%d..%d) + keymap.json to %s in %.1f s" % (
        len(keymap), keymap[0]["midi"], keymap[-1]["midi"], args.out, time.time() - t_start))

    ok = True
    if not args.no_verify:
        ok = verify(args.out)
        print("total runtime %.1f s" % (time.time() - t_start))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
