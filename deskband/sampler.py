"""Sample loading: keymapped instruments, a drum kit, and a looping texture.
Everything is decoded to float32 stereo at the engine sample rate up front so
the audio callback only ever slices arrays."""

import glob
import json
import os
import re
import subprocess

import numpy as np
import soundfile as sf
from scipy.signal import lfilter, resample_poly

from . import config as C

SR = C.SAMPLE_RATE
NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_RE = re.compile(r"([A-Ga-g])(#|b)?(-?\d)")


def note_to_midi(name, acc, octave, c_of_60=3):
    """Logic labels middle C as C3; scientific pitch calls it C4."""
    pc = NOTE_PC[name.upper()] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return 60 + pc + 12 * (int(octave) - c_of_60)


def midi_from_name(stem, scheme):
    if scheme == "prefix3":
        return int(stem[:3])
    if scheme == "strng":                      # STRNG24C0-left
        return int(re.match(r"[A-Z]+(\d+)", stem).group(1))
    if scheme == "cbs":                        # "Cbs pizz f  0 e" / "Cbs pizz f  1a#"
        m = re.search(r"(\d)\s*([a-g])(#?)$", stem)
        return note_to_midi(m.group(2), m.group(3), m.group(1), 3)
    m = list(NOTE_RE.finditer(stem))[-1]       # last note name in the stem
    return note_to_midi(m.group(1), m.group(2), m.group(3), 3 if scheme == "logic" else 4)


def read_audio(path, max_seconds=None):
    """-> float32 (n, 2) at SR. Handles mono, big-endian AIFF, 48 kHz."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    if sr != SR:
        g = np.gcd(SR, sr)
        data = resample_poly(data, SR // g, sr // g, axis=0).astype(np.float32)
    if max_seconds:
        data = data[: int(max_seconds * SR)]
    return np.ascontiguousarray(data)


def fade_tail(data, seconds=0.05):
    n = min(len(data), int(seconds * SR))
    if n > 0:
        data[-n:] *= np.linspace(1, 0, n, dtype=np.float32)[:, None]
    return data


def estimate_midi(buf, lo_hz=25.0, hi_hz=4500.0):
    """Rough f0 by autocorrelation over the loudest 0.4 s. For sanity checks."""
    x = buf.mean(axis=1)
    peak = int(np.argmax(np.abs(x)))
    return segment_midi(x[peak: peak + int(0.4 * SR)], lo_hz, hi_hz)


def segment_midi(seg, lo_hz=25.0, hi_hz=4500.0):
    """f0 of a mono segment (at least 0.1 s) by autocorrelation -> fractional
    MIDI, or None when it is silent or too short."""
    seg = seg - seg.mean()
    if len(seg) < SR // 10 or np.abs(seg).max() < 1e-4:
        return None
    seg = seg * np.hanning(len(seg))
    spec = np.fft.rfft(seg, 2 * len(seg))
    ac = np.fft.irfft(spec * np.conj(spec))[: len(seg)]
    ac /= ac[0] + 1e-12
    lag_min, lag_max = int(SR / hi_hz), int(SR / lo_hz)
    # skip the main lobe around lag 0: start after the first dip below zero
    below = np.nonzero(ac[:lag_max] < 0)[0]
    start = max(lag_min, int(below[0])) if len(below) else lag_min
    lag = start + int(np.argmax(ac[start:lag_max]))
    # prefer the shortest local maximum nearly as strong (avoids octave-down errors)
    best = ac[lag]
    for l in range(start + 1, lag):
        if ac[l] > 0.8 * best and ac[l] > ac[l - 1] and ac[l] >= ac[l + 1]:
            lag = l
            break
    return 69 + 12 * np.log2(SR / lag / 440.0)


class KeyMap:
    """One pitched instrument: nearest-sample lookup with pitch ratio."""

    def __init__(self, name):
        self.name = name
        self.notes = {}
        self.keys = None
        self.files = {}

    def add(self, midi, buf, path):
        self.notes[midi] = buf
        self.files[midi] = path

    def finish(self):
        self.keys = np.array(sorted(self.notes))
        return self

    @property
    def ready(self):
        return self.keys is not None and len(self.keys) > 0

    def lookup(self, midi):
        """-> (buffer, playback ratio) for the nearest sample."""
        k = int(self.keys[np.argmin(np.abs(self.keys - midi))])
        return self.notes[k], 2 ** ((midi - k) / 12)


def load_set(kind):
    spec = C.SAMPLE_SETS[kind]
    km = KeyMap(kind)
    folder = C.sample_dir(kind, spec["dir"])
    for path in sorted(glob.glob(os.path.join(folder, spec["glob"]))):
        stem = os.path.splitext(os.path.basename(path))[0]
        if spec.get("exclude") and spec["exclude"] in stem:
            continue
        if "pair" in spec:                    # left/right files -> stereo
            l, r = spec["pair"]
            stem = stem[: -len(l)]
            left = read_audio(path, spec["max_seconds"])
            right = read_audio(path.replace(l, r), spec["max_seconds"])
            n = min(len(left), len(right))
            buf = np.stack([left[:n, 0], right[:n, 0]], axis=1)
        else:
            buf = read_audio(path, spec["max_seconds"])
        km.add(midi_from_name(stem, spec["pitch"]), fade_tail(buf), path)
    return km.finish()


def load_keymap_dir(name, folder, max_seconds, lowpass_hz=0):
    """A folder of <midi>.wav files plus keymap.json (tools/exs_extract.py,
    tools/make_kings_cross.py). Returns None when it is not there."""
    keymap = os.path.join(folder, "keymap.json")
    if not os.path.exists(keymap):
        return None
    km = KeyMap(name)
    with open(keymap) as f:
        zones = json.load(f)
    for z in zones:
        path = os.path.join(folder, z["file"])
        buf = read_audio(path, max_seconds)
        if lowpass_hz:                       # two one-pole stages: a soft 12 dB/oct felt
            a = np.exp(-2 * np.pi * lowpass_hz / SR)
            for _ in range(2):
                buf = lfilter([1 - a], [1, -a], buf, axis=0).astype(np.float32)
        km.add(int(z["midi"]), fade_tail(buf), path)
    km.source = folder
    return km.finish()


def load_concert_grand():
    for folder in C.CONCERT_GRAND:
        km = load_keymap_dir("piano", folder, 8.0, C.PIANO_LOWPASS_HZ)
        if km is not None:
            return km
    return None


def load_kings_cross():
    km = load_keymap_dir("strings", C.KINGS_CROSS, 7.0)
    if km is None:
        return None
    # Some low notes were recorded well left of centre (the basses sit there
    # in the hall). Even out left/right loudness so chords stay centred.
    for buf in km.notes.values():
        l, r = np.sqrt((buf[:, 0] ** 2).mean()), np.sqrt((buf[:, 1] ** 2).mean())
        if l > 0 and r > 0:
            g = np.sqrt(l * r)
            buf[:, 0] *= np.clip(g / l, 0.5, 2.0)
            buf[:, 1] *= np.clip(g / r, 0.5, 2.0)
    return km


def load_drums():
    kit = {}
    folder = C.sample_dir("drums", C.DRUM_DIR)
    for name, fn in C.DRUMS.items():
        path = os.path.join(folder, fn)
        if os.path.exists(path):
            kit[name] = read_audio(path, 2.0)
    return kit


def load_loop(path, cache_name):
    """Apple Loops are AAC inside CAF; decode once with afconvert into cache/."""
    os.makedirs(C.CACHE_DIR, exist_ok=True)
    wav = os.path.join(C.CACHE_DIR, cache_name + ".wav")
    if not os.path.exists(wav):
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", path, wav],
                       check=True, capture_output=True)
    return read_audio(wav)
