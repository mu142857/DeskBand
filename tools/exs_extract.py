#!/usr/bin/env python3
"""
exs_extract.py - extract per-note WAV files from a Logic Pro EXS24 / Sampler
instrument (.exs) whose audio lives in one or more *consolidated* CAF files.

    exs_extract.py <instrument.exs> <caf_dir> <out_dir> [options]

    --layer N         velocity layer to extract per note, indexed from the
                      softest (0) upward; negative counts from the loudest
                      (-1 = loudest, the default)
    --velocity V      instead of --layer: pick the zone whose velocity range
                      contains V (0..127)
    --all-layers      extract every velocity layer (files <midi>_v<k>.wav)
    --group G         zone group to use (index or case-insensitive substring of
                      its name); default: the group covering the most root
                      notes (ties -> most audio) - the "Sustain" group for pianos
    --max-seconds S   trim each note to at most S seconds (default 6; 0 = full)
    --fade-ms MS      fade-out applied to the last MS ms of each file (default 50)
    --extent MODE     how a zone's audio range in the CAF is determined:
                        zone        [start, max(end, loop_end)] (default)
                        contiguous  [start, next sample start) - for legacy
                                    files whose 'end' field is stale
    --decoded-dir D   where PCM decodes of ALAC CAFs are cached
                      (default <out_dir>/_decoded); pre-decoded files named
                      <caf basename>.wav are picked up from here
    --list            print chunk / group / zone tables and exit (no audio)
    --verify          after extracting, estimate each note's fundamental and
                      compare with the expected pitch (prints a table)
    --verify-only     run the pitch check on an existing out_dir without
                      re-extracting

Output: <out_dir>/<midi>.wav (stereo 16-bit PCM at the CAF sample rate) and
<out_dir>/keymap.json, a list of
    {midi, root, keylo, keyhi, file, vel_layer, vello, velhi, ...}
sorted by midi.

Format notes (verified on Logic 10.7/11 "Concert Grand Piano.exs" (148-byte zone
bodies) and the 2013 "Steinway Grand Piano 2.exs" (128-byte zone bodies)):

  * The file is a flat sequence of chunks.  Chunk header (84 bytes):
        u32 signature   bits 24..27 = chunk type:
                        0 header, 1 zone, 2 group, 3 sample, 4 params,
                        8 / 11 = misc (bookmark plists etc.)
        u32 body_size   bytes following the 84-byte header
        u32 id
        u32 unknown
        4   magic       b"TBOS" (little-endian file) or b"SOBT" (big-endian)
        64  name        zero padded
  * Zone body (offsets relative to the body start; chunk offset = +84):
        +0  flags (bit3 = velocity range on, bit0 = pitch tracking off)
        +1  root note (MIDI)      +2  fine tune (i8, cents)
        +3  pan (i8)              +4  volume (i8, dB)
        +6  key low               +7  key high
        +9  velocity low          +10 velocity high
        +12 u32 sample start  } frame offsets INTO THE CONSOLIDATED CAF
        +16 u32 sample end    }
        +20 u32 loop start        +24 u32 loop end   (same units)
        +80 coarse tune (i8, semitones)
        +88 i32 group index (into the type-2 chunks, in file order)
        +92 i32 sample index (into the type-3 chunks, in file order)
  * Sample body: +4 u32 length in frames, +8 u32 sample rate, +12 u32 bit depth,
    +16 u32 channels, +88 zero-terminated directory path.  The audio file name
    is the chunk name (a longer full name, if any, follows the path field).
  * In a consolidated instrument every zone's [start, end) lies inside the
    named CAF, with no overlaps between zones.  ALAC-compressed CAFs are decoded
    with macOS `afconvert` (libsndfile reads PCM CAF directly).
"""

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
import soundfile as sf

CHUNK_HEADER = 84
TYPE_NAMES = {0: "header", 1: "zone", 2: "group", 3: "sample", 4: "params"}


# --------------------------------------------------------------------------- #
#  Binary parsing
# --------------------------------------------------------------------------- #
class Chunk:
    __slots__ = ("offset", "sig", "size", "id", "unknown", "type", "name", "body", "endian")

    def __init__(self, offset, sig, size, cid, unknown, ctype, name, body, endian):
        self.offset, self.sig, self.size, self.id, self.unknown = offset, sig, size, cid, unknown
        self.type, self.name, self.body, self.endian = ctype, name, body, endian


def cstring(buf, start, maxlen=None):
    end = buf.find(b"\0", start)
    if end < 0:
        end = len(buf)
    if maxlen is not None:
        end = min(end, start + maxlen)
    return buf[start:end].decode("utf-8", "replace")


def parse_chunks(data):
    chunks = []
    off = 0
    while off + CHUNK_HEADER <= len(data):
        magic = data[off + 16:off + 20]
        if magic == b"TBOS":
            endian = "<"
        elif magic == b"SOBT":
            endian = ">"
        else:
            raise ValueError("bad chunk magic %r at offset %d" % (magic, off))
        sig, size, cid, unknown = struct.unpack_from(endian + "IIII", data, off)
        ctype = (sig >> 24) & 0x0F
        name = cstring(data, off + 20, 64)
        body = data[off + CHUNK_HEADER:off + CHUNK_HEADER + size]
        if len(body) != size:
            raise ValueError("truncated chunk at offset %d" % off)
        chunks.append(Chunk(off, sig, size, cid, unknown, ctype, name, body, endian))
        off += CHUNK_HEADER + size
    if off != len(data):
        print("warning: %d trailing bytes after last chunk" % (len(data) - off), file=sys.stderr)
    return chunks


class Zone:
    def __init__(self, chunk, index):
        b, e = chunk.body, chunk.endian
        if len(b) < 96:
            raise ValueError("zone body too small (%d bytes) in %r" % (len(b), chunk.name))
        u32 = lambda o: struct.unpack_from(e + "I", b, o)[0]
        i32 = lambda o: struct.unpack_from(e + "i", b, o)[0]
        i8 = lambda o: struct.unpack_from("b", b, o)[0]
        self.index = index
        self.name = chunk.name
        self.id = chunk.id
        self.flags = b[0]
        self.root = b[1]
        self.fine = i8(2)
        self.pan = i8(3)
        self.volume = i8(4)
        self.keylo = b[6]
        self.keyhi = b[7]
        self.vello = b[9]
        self.velhi = b[10]
        self.start = u32(12)
        self.end = u32(16)
        self.loop_start = u32(20)
        self.loop_end = u32(24)
        self.coarse = i8(80)
        self.group = i32(88)
        self.sample = i32(92)
        # filled in later
        self.ext_start = self.start
        self.ext_end = self.end

    @property
    def pitch_off(self):
        return bool(self.flags & 1)

    @property
    def sample_pitch(self):
        """MIDI note (float) at which the raw audio actually sounds: the sampler
        transposes by coarse/fine when playing the root key."""
        return self.root - self.coarse - self.fine / 100.0

    def row(self):
        return "%-26s %4d %4d %4d %4d %4d %11d %11d %4d %4d %3d %s" % (
            self.name[:26], self.root, self.keylo, self.keyhi, self.vello, self.velhi,
            self.start, self.end, self.sample, self.group, self.coarse,
            "P" if self.pitch_off else "")


class Sample:
    def __init__(self, chunk, index):
        b, e = chunk.body, chunk.endian
        u32 = lambda o: struct.unpack_from(e + "I", b, o)[0] if len(b) >= o + 4 else 0
        self.index = index
        self.name = chunk.name
        self.length = u32(4)
        self.rate = u32(8)
        self.bits = u32(12)
        self.channels = u32(16)
        self.path = cstring(b, 88, 256) if len(b) >= 92 else ""
        # a full file name longer than the 63 chars of the chunk name may follow the path
        self.filename = self.name
        if len(b) >= 344 + 4:
            longname = cstring(b, 344, 256)
            if longname and longname.startswith(self.name[:20]) and len(longname) >= len(self.name):
                self.filename = longname
        self.audio_path = None     # resolved on disk
        self.pcm_path = None       # readable-by-libsndfile version
        self.frames = None         # actual frames in pcm_path


class Instrument:
    def __init__(self, path):
        self.path = path
        data = open(path, "rb").read()
        self.chunks = parse_chunks(data)
        self.groups = [c for c in self.chunks if c.type == 2]
        self.samples = [Sample(c, i) for i, c in enumerate(c for c in self.chunks if c.type == 3)]
        self.zones = [Zone(c, i) for i, c in enumerate(c for c in self.chunks if c.type == 1)]
        for z in self.zones:
            if not (0 <= z.sample < len(self.samples)):
                raise ValueError("zone %r references sample %d but only %d sample chunks"
                                 % (z.name, z.sample, len(self.samples)))
        self.compute_extents()

    def group_name(self, gi):
        return self.groups[gi].name if 0 <= gi < len(self.groups) else "<group %d>" % gi

    def compute_extents(self):
        """Per zone, decide which frames of the CAF belong to it."""
        by_sample = {}
        for z in self.zones:
            by_sample.setdefault(z.sample, []).append(z)
        for si, zs in by_sample.items():
            zs.sort(key=lambda z: z.start)
            length = self.samples[si].length or (1 << 62)
            for i, z in enumerate(zs):
                # next distinct start after this zone (several zones may share one sample)
                nxt = length
                for w in zs[i + 1:]:
                    if w.start > z.start:
                        nxt = w.start
                        break
                z.next_start = nxt
                z.ext_start = z.start
                z.ext_end = max(z.end, z.loop_end) if z.loop_end > z.end else z.end
                z.ext_end = min(z.ext_end, nxt, length)

    def summary(self):
        from collections import Counter
        out = []
        out.append("file: %s (%d bytes, %d chunks, %s-endian)" % (
            self.path, os.path.getsize(self.path), len(self.chunks),
            "big" if self.chunks and self.chunks[0].endian == ">" else "little"))
        cnt = Counter(c.type for c in self.chunks)
        out.append("chunks per type: " + ", ".join(
            "%s(%d)=%d" % (TYPE_NAMES.get(t, "type"), t, n) for t, n in sorted(cnt.items())))
        out.append("")
        out.append("samples:")
        for s in self.samples:
            out.append("  [%d] %s  frames=%d rate=%d bits=%d ch=%d  dir=%s" % (
                s.index, s.filename, s.length, s.rate, s.bits, s.channels, s.path))
        out.append("")
        out.append("groups:")
        for gi, g in enumerate(self.groups):
            zs = [z for z in self.zones if z.group == gi]
            roots = sorted(set(z.root for z in zs))
            layers = Counter(z.root for z in zs)
            dur = sum(z.ext_end - z.ext_start for z in zs)
            rate = self.samples[zs[0].sample].rate if zs else 44100
            out.append("  [%d] %-28s zones=%-4d roots=%d (%s..%s) layers/root=%s..%s audio=%.1f min" % (
                gi, g.name, len(zs), len(roots), roots[0] if roots else "-", roots[-1] if roots else "-",
                min(layers.values()) if layers else 0, max(layers.values()) if layers else 0,
                dur / max(rate, 1) / 60))
        return "\n".join(out)

    def zone_table(self, zones=None):
        zones = self.zones if zones is None else zones
        hdr = "%-26s %4s %4s %4s %4s %4s %11s %11s %4s %4s %3s %s" % (
            "name", "root", "klo", "khi", "vlo", "vhi", "start", "end", "smp", "grp", "crs", "flags")
        return "\n".join([hdr] + [z.row() for z in zones])

    def check_ranges(self):
        problems = []
        for si, s in enumerate(self.samples):
            zs = sorted((z for z in self.zones if z.sample == si), key=lambda z: z.start)
            for z in zs:
                if not (0 <= z.start < z.end <= s.length):
                    problems.append("zone %r [%d,%d) outside sample %d length %d"
                                    % (z.name, z.start, z.end, si, s.length))
            for a, b in zip(zs, zs[1:]):
                if b.start < a.end and b.start != a.start:
                    problems.append("zones %r and %r overlap" % (a.name, b.name))
        return problems


# --------------------------------------------------------------------------- #
#  Audio access
# --------------------------------------------------------------------------- #
def find_file(caf_dir, filename):
    cand = os.path.join(caf_dir, filename)
    if os.path.isfile(cand):
        return cand
    for root, _dirs, files in os.walk(caf_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None


def sf_readable(path):
    try:
        info = sf.info(path)
        return info
    except Exception:
        return None


def resolve_audio(inst, caf_dir, decoded_dir):
    """Locate every sample file and make sure a libsndfile-readable copy exists."""
    for s in inst.samples:
        stem = os.path.splitext(s.filename)[0]
        # 1. a pre-decoded PCM copy?
        for cand in (os.path.join(decoded_dir, stem + ".wav"), os.path.join(decoded_dir, stem + ".caf")):
            info = sf_readable(cand) if os.path.exists(cand) else None
            if info is not None:
                s.pcm_path, s.frames = cand, info.frames
                break
        src = find_file(caf_dir, s.filename)
        if src is None and s.path:
            src = find_file(s.path, s.filename) if os.path.isdir(s.path) else None
        s.audio_path = src
        if s.pcm_path is None:
            if src is None:
                raise FileNotFoundError("cannot find %r under %s" % (s.filename, caf_dir))
            info = sf_readable(src)
            if info is not None:
                s.pcm_path, s.frames = src, info.frames
            else:
                s.pcm_path = decode_with_afconvert(src, decoded_dir, stem, s)
                s.frames = sf.info(s.pcm_path).frames
        if s.length and s.frames != s.length:
            print("warning: %s has %d frames but the instrument expects %d"
                  % (s.pcm_path, s.frames, s.length), file=sys.stderr)
        if not s.length:
            s.length = s.frames


def decode_with_afconvert(src, decoded_dir, stem, s):
    if shutil.which("afconvert") is None:
        raise RuntimeError("%s is not PCM (probably ALAC) and `afconvert` (macOS) is not available "
                           "to decode it; decode it to <decoded-dir>/%s.wav yourself" % (src, stem))
    os.makedirs(decoded_dir, exist_ok=True)
    nbytes = (s.length or 0) * max(s.channels, 1) * 2
    if nbytes and nbytes < 0xFFFFFFFF - (1 << 20):
        out, fmt = os.path.join(decoded_dir, stem + ".wav"), "WAVE"
    else:
        out, fmt = os.path.join(decoded_dir, stem + ".caf"), "caff"
    print("decoding %s -> %s (afconvert %s LEI16) ..." % (src, out, fmt), file=sys.stderr)
    tmp = out + ".part"
    subprocess.run(["afconvert", "-f", fmt, "-d", "LEI16", src, tmp], check=True)
    os.replace(tmp, out)
    return out


def read_frames(pcm_path, start, nframes):
    with sf.SoundFile(pcm_path) as f:
        f.seek(start)
        return f.read(nframes, dtype="int16", always_2d=True), f.samplerate


# --------------------------------------------------------------------------- #
#  Selection
# --------------------------------------------------------------------------- #
def pick_group(inst, spec):
    if spec is not None:
        if spec.isdigit() and int(spec) < len(inst.groups):
            return int(spec)
        matches = [i for i, g in enumerate(inst.groups) if spec.lower() in g.name.lower()]
        if len(matches) == 1:
            return matches[0]
        raise SystemExit("group %r matches %d groups: %s" % (
            spec, len(matches), [inst.groups[i].name for i in matches]))
    best = None
    for gi in range(len(inst.groups)):
        zs = [z for z in inst.zones if z.group == gi]
        if not zs:
            continue
        key = (len(set(z.root for z in zs)), sum(z.ext_end - z.ext_start for z in zs))
        if best is None or key > best[0]:
            best = (key, gi)
    if best is None:
        raise SystemExit("instrument has no zones")
    return best[1]


def layers_by_note(zones):
    """{root: [zones sorted by velocity low]}"""
    notes = {}
    for z in zones:
        notes.setdefault(z.root, []).append(z)
    for zs in notes.values():
        zs.sort(key=lambda z: (z.vello, z.velhi, z.index))
    return notes


def select_zones(notes, layer=None, velocity=None, all_layers=False):
    """returns list of (zone, layer_index)"""
    out = []
    for root in sorted(notes):
        zs = notes[root]
        if all_layers:
            out.extend((z, k) for k, z in enumerate(zs))
        elif velocity is not None:
            hits = [k for k, z in enumerate(zs) if z.vello <= velocity <= z.velhi]
            if not hits:
                k = min(range(len(zs)), key=lambda k: min(abs(zs[k].vello - velocity), abs(zs[k].velhi - velocity)))
                print("warning: note %d has no zone covering velocity %d; using %r"
                      % (root, velocity, zs[k].name), file=sys.stderr)
                hits = [k]
            out.append((zs[hits[0]], hits[0]))
        else:
            k = layer if layer >= 0 else len(zs) + layer
            k = max(0, min(len(zs) - 1, k))
            out.append((zs[k], k))
    return out


# --------------------------------------------------------------------------- #
#  Extraction
# --------------------------------------------------------------------------- #
def extract(inst, selection, out_dir, max_seconds, fade_ms, extent_mode, all_layers):
    os.makedirs(out_dir, exist_ok=True)
    keymap = []
    seen = {}
    total_bytes = 0
    for z, k in selection:
        s = inst.samples[z.sample]
        start = z.ext_start
        end = z.ext_end if extent_mode == "zone" else min(z.next_start, s.length)
        if s.frames is not None:
            end = min(end, s.frames)
        n = end - start
        if n <= 0:
            print("warning: zone %r has empty range, skipped" % z.name, file=sys.stderr)
            continue
        audio, rate = read_frames(s.pcm_path, start, n)
        if max_seconds and len(audio) > int(max_seconds * rate):
            audio = audio[:int(max_seconds * rate)]
        x = audio.astype(np.float32)
        nf = min(len(x), int(fade_ms * rate / 1000.0))
        if nf > 0:
            ramp = 0.5 * (1 + np.cos(np.linspace(0, np.pi, nf, endpoint=False)))  # 1 -> 0
            x[-nf:] *= ramp[:, None]
        pcm = np.clip(np.round(x), -32768, 32767).astype(np.int16)

        base = "%d" % z.root
        if all_layers:
            base += "_v%d" % k
        key = base
        if key in seen:                     # duplicate root (round robin / split key range)
            seen[key] += 1
            base += "_rr%d" % seen[key]
            print("warning: several zones map to %s; wrote %s as %s" % (key, z.name, base), file=sys.stderr)
        else:
            seen[key] = 0
        fname = base + ".wav"
        sf.write(os.path.join(out_dir, fname), pcm, rate, subtype="PCM_16")
        total_bytes += os.path.getsize(os.path.join(out_dir, fname))
        keymap.append(dict(
            midi=z.root, root=z.root, keylo=z.keylo, keyhi=z.keyhi, file=fname,
            vel_layer=k, vello=z.vello, velhi=z.velhi, n_layers=None,
            coarse=z.coarse, fine=z.fine, volume_db=z.volume, pan=z.pan,
            sample_pitch=z.sample_pitch, zone=z.name, group=inst.group_name(z.group),
            source=s.filename, src_start=start, src_end=end, frames=len(pcm), rate=rate,
        ))
    return keymap, total_bytes


# --------------------------------------------------------------------------- #
#  Pitch verification
# --------------------------------------------------------------------------- #
def midi_to_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def cents(f, ref):
    return 1200.0 * math.log2(f / ref)


def _peak_interp(spec, i):
    """parabolic interpolation of a log-magnitude peak at bin i -> (bin, level_db)"""
    i = max(1, min(len(spec) - 2, i))
    y0, y1, y2 = np.log(spec[i - 1] + 1e-12), np.log(spec[i] + 1e-12), np.log(spec[i + 1] + 1e-12)
    den = y0 - 2 * y1 + y2
    d = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    return i + d, 20 * math.log10(spec[i] + 1e-12)


def _spectrum(seg, rate, min_nfft=1 << 18):
    n = len(seg)
    nfft = max(min_nfft, 1 << int(math.ceil(math.log2(n * 8))))
    spec = np.abs(np.fft.rfft(seg * np.hanning(n), nfft))
    ref = 20 * math.log10(spec.max() + 1e-12)
    return spec, ref, rate / float(nfft)


def _fundamental_from_partials(spec, ref, df, f0):
    """refine f0 from the strongest of its first three partials (fundamental preferred)"""
    best = None
    for h in (1, 2, 3):
        tol = min(0.05, 0.004 * h * h)
        a = max(1, int(h * f0 * (1 - tol) / df))
        b = min(len(spec) - 2, int(h * f0 * (1 + tol) / df) + 1)
        if b <= a:
            continue
        i = a + int(np.argmax(spec[a:b]))
        pos, lvl = _peak_interp(spec, i)
        lvl -= ref
        if h == 1:
            lvl += 20.0                     # prefer the fundamental unless it is >20 dB weaker
        if best is None or lvl > best[1]:
            best = (pos * df / h, lvl)
    return best[0] if best else f0


def _harmonic_pick(seg, rate, fmin, fmax):
    """Peak-based fundamental search for a struck/plucked string tone.
    Candidates are (strong peak)/n; a candidate is scored by the mean level of
    its predicted partials, a bonus for a present fundamental, and a penalty
    for strong peaks that are not near any of its multiples.  This resolves
    both the weak-fundamental bass case (octave/twelfth errors) and the
    few-partials treble case (sub-octave / noise-floor errors)."""
    from scipy.signal import find_peaks
    spec, ref, df = _spectrum(seg, rate)
    spec_db = np.maximum(20 * np.log10(spec + 1e-12) - ref, -50.0)
    nyq = 0.45 * rate
    lo, hi = int(fmin / df), int(min(nyq, fmax * 8) / df)
    idx, props = find_peaks(spec_db[lo:hi], height=-35.0, prominence=6.0, distance=max(1, int(0.5 * fmin / df)))
    idx = idx + lo
    if len(idx) == 0:
        return None, None
    order = np.argsort(spec_db[idx])[::-1][:12]
    peaks = [(idx[j] * df, spec_db[idx[j]]) for j in order]

    cands = set()
    for p, _l in peaks:
        for n in range(1, 9):
            c = p / n
            if fmin <= c <= fmax:
                cands.add(round(c, 3))
    cands = sorted(cands)

    def band_max(fc, tol):
        a = max(0, int(fc * (1 - tol) / df))
        b = min(len(spec_db), int(fc * (1 + tol) / df) + 1)
        return spec_db[a:b].max() if b > a else -50.0

    def tol_h(h):
        return min(0.06, 0.004 * h * h)

    best = None
    for f0 in cands:
        Hn = max(1, min(6, int(nyq // f0)))
        levels = [band_max(h * f0, tol_h(h)) for h in range(1, Hn + 1)]
        # strongest three predicted partials (treble notes only have a few),
        # plus the first two partials and the fundamental itself, so that a
        # sub-octave candidate (all odd partials missing) or a noise-floor
        # candidate cannot tie with the true fundamental
        pred = float(np.mean(sorted(levels, reverse=True)[:3]))
        first2 = float(np.mean(levels[:2]))
        fund = levels[0]
        penalty = 0.0
        for p, l in peaks:
            r = p / f0
            if r >= 8.5:
                continue
            h = int(round(r))
            if h < 1 or abs(r - h) > min(0.35, tol_h(h) * h):
                penalty += 15.0 * (l + 50.0) / 50.0
        score = pred + 0.3 * first2 + 0.3 * fund - penalty
        if best is None or score > best[0]:
            best = (score, f0)
    f0 = best[1]
    return _fundamental_from_partials(spec, ref, df, f0), band_max(f0, tol_h(1))


def estimate_f0(x, rate, seconds=0.5, fmin=25.0, fmax=4500.0):
    """Fundamental of a struck tone from the first `seconds` after onset.
    Returns dict(f0, f_acf, level_db, onset_s, head_db) or None.
    f0 is a spectral estimate (peak-based harmonic search, then the fundamental
    peak refined on a window of ~40 periods); f_acf is an independent
    autocorrelation estimate (global ACF maximum between 1/fmax and 1/fmin);
    head_db is the level of the first millisecond relative to the peak (a
    value near 0 dB means the file starts mid-waveform, i.e. a click)."""
    mono = x.astype(np.float64).mean(axis=1) if x.ndim == 2 else x.astype(np.float64)
    if mono.size < rate * 0.2:
        return None
    peak_abs = max(float(np.abs(mono).max()), 1e-9)
    blk = max(1, int(0.005 * rate))
    nb = len(mono) // blk
    env = np.sqrt((mono[:nb * blk].reshape(nb, blk) ** 2).mean(axis=1) + 1e-12)
    onset = int(np.argmax(env > env.max() * 0.1)) * blk
    head = mono[:max(1, int(0.001 * rate))]
    head_db = 20 * math.log10(np.sqrt((head ** 2).mean()) / peak_abs + 1e-12)
    level_db = 20 * math.log10(peak_abs / 32768.0)

    seg_start = onset + int(0.02 * rate)
    seg = mono[seg_start:seg_start + int(seconds * rate)]
    if len(seg) < rate * 0.1:
        return None
    f0, _fund = _harmonic_pick(seg, rate, fmin, fmax)
    if f0 is None:
        return None
    win = min(1.5, max(seconds, 40.0 / f0))
    if win > seconds:
        seg2 = mono[seg_start:seg_start + int(win * rate)]
        if len(seg2) >= int(seconds * rate):
            spec, ref, df = _spectrum(seg2, rate, 1 << 19)
            f0 = _fundamental_from_partials(spec, ref, df, f0)

    # independent autocorrelation estimate on the same first window
    seg = seg - seg.mean()
    n = len(seg)
    S = np.fft.rfft(seg, 2 * n)
    ac = np.fft.irfft(S * np.conj(S))[:n]
    ac /= (ac[0] + 1e-12)
    lag_lo, lag_hi = max(2, int(rate / fmax)), min(n - 2, int(rate / fmin) + 1)
    f_acf = float("nan")
    if lag_hi > lag_lo:
        i = lag_lo + int(np.argmax(ac[lag_lo:lag_hi]))
        y0, y1, y2 = ac[i - 1], ac[i], ac[i + 1]
        den = y0 - 2 * y1 + y2
        d = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        d = max(-1.0, min(1.0, d))
        if i + d > 0:
            f_acf = rate / (i + d)
    return dict(f0=f0, f_acf=f_acf, level_db=level_db, onset_s=onset / rate, head_db=head_db)


def verify(out_dir, keymap, tolerance=30.0):
    print("\npitch verification (expected = root - coarse - fine/100; 'cents' uses the spectral estimate,")
    print("acf is an independent autocorrelation estimate; onset = start of the note in the file;")
    print("head = level of the file's first ms re. peak, near 0 dB would mean a click/mid-note cut)")
    print("%5s %-14s %9s %9s %7s %9s %7s %7s %7s %7s %s" % (
        "midi", "zone", "expected", "measured", "cents", "acf_Hz", "cents", "peak", "onset", "head", ""))
    n_ok = n_bad = 0
    for e in keymap:
        x, rate = sf.read(os.path.join(out_dir, e["file"]), dtype="int16", always_2d=True)
        exp = midi_to_hz(e["sample_pitch"])
        r = estimate_f0(x, rate)
        if r is None:
            print("%5d %-14s %9.2f   (no signal)" % (e["midi"], e["zone"][:14], exp))
            n_bad += 1
            continue
        c = cents(r["f0"], exp)
        ca = cents(r["f_acf"], exp) if (r["f_acf"] == r["f_acf"] and r["f_acf"] > 0) else float("nan")
        ok = abs(c) <= tolerance
        n_ok += ok
        n_bad += not ok
        print("%5d %-14s %9.2f %9.2f %+7.1f %9.2f %+7.1f %5.1fdB %5.0fms %5.0fdB %s" % (
            e["midi"], e["zone"][:14], exp, r["f0"], c, r["f_acf"], ca, r["level_db"],
            r["onset_s"] * 1000, r["head_db"], "ok" if ok else "MISMATCH"))
    print("pitch check: %d ok, %d mismatched (tolerance +/-%.0f cents)" % (n_ok, n_bad, tolerance))
    return n_bad == 0


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("exs")
    ap.add_argument("caf_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--layer", type=int, default=-1)
    ap.add_argument("--velocity", type=int)
    ap.add_argument("--all-layers", action="store_true")
    ap.add_argument("--group")
    ap.add_argument("--max-seconds", type=float, default=6.0)
    ap.add_argument("--fade-ms", type=float, default=50.0)
    ap.add_argument("--extent", choices=("zone", "contiguous"), default="zone")
    ap.add_argument("--decoded-dir")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--tolerance", type=float, default=30.0, help="cents allowed in --verify")
    args = ap.parse_args(argv)

    inst = Instrument(args.exs)
    print(inst.summary())
    problems = inst.check_ranges()
    if problems:
        print("range problems:", file=sys.stderr)
        for p in problems[:20]:
            print("  " + p, file=sys.stderr)
        if len(problems) > 20:
            print("  ... %d more" % (len(problems) - 20), file=sys.stderr)
    else:
        print("all %d zones lie inside their sample file with no overlaps" % len(inst.zones))

    gi = pick_group(inst, args.group)
    gzones = [z for z in inst.zones if z.group == gi]
    notes = layers_by_note(gzones)
    print("\nusing group [%d] %r: %d zones, %d notes" % (gi, inst.group_name(gi), len(gzones), len(notes)))
    from collections import Counter
    layer_shapes = Counter(tuple((z.vello, z.velhi) for z in zs) for zs in notes.values())
    print("velocity layer layouts (count of notes: ranges):")
    for shape, n in sorted(layer_shapes.items(), key=lambda kv: -kv[1]):
        print("  %3d notes: %s" % (n, " ".join("%d-%d" % r for r in shape)))

    if args.list:
        print("\n" + inst.zone_table())
        return 0

    if args.verify_only:
        keymap = json.load(open(os.path.join(args.out_dir, "keymap.json")))
        return 0 if verify(args.out_dir, keymap, args.tolerance) else 1

    decoded_dir = args.decoded_dir or os.path.join(args.out_dir, "_decoded")
    resolve_audio(inst, args.caf_dir, decoded_dir)
    for s in inst.samples:
        print("audio [%d] %s -> %s (%d frames)" % (s.index, s.audio_path, s.pcm_path, s.frames))

    selection = select_zones(notes, layer=args.layer, velocity=args.velocity, all_layers=args.all_layers)
    keymap, total = extract(inst, selection, args.out_dir, args.max_seconds, args.fade_ms, args.extent, args.all_layers)
    for e in keymap:
        e["n_layers"] = len(notes[e["root"]])
    keymap.sort(key=lambda e: (e["midi"], e["vel_layer"]))
    with open(os.path.join(args.out_dir, "keymap.json"), "w") as f:
        json.dump(keymap, f, indent=1)
    print("\nwrote %d files (%.1f MB) + keymap.json to %s" % (len(keymap), total / 1e6, args.out_dir))

    if args.verify:
        return 0 if verify(args.out_dir, keymap, args.tolerance) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
