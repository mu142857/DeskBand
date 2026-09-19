"""Voices: sung samples for the headphones part, made once by ElevenLabs.

Each prompt in config.VOCAL_PROMPTS asks the sound-effects model for one long
sung note. It comes back at whatever pitch the model chose, so the take is
pitch-tracked: one that wanders is dropped, a steady one is retuned to the
nearest semitone (a tiny resample) and filed under that MIDI note. The result
is an ordinary keymap folder (<midi>.wav + keymap.json in config.VOCAL_DIR)
that the sampler plays like any other pitched instrument, so the voices follow
the chords. Delete the folder to make new ones.

    .venv/bin/python -m deskband.vocals        # make them now (DeskBand also does it on start)
"""

import json
import os

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from . import cloud, sampler
from . import config as C

SR = C.SAMPLE_RATE
STEADY = 0.6          # semitones: the middle half of a take's pitch track must fit in this
WINDOW_S = 0.15       # pitch-track window


def pitch_track(x):
    """Fractional MIDI per window over the middle three fifths of a mono take."""
    n = int(WINDOW_S * SR)
    marks = [sampler.segment_midi(x[s:s + n], 70.0, 1100.0)
             for s in range(len(x) // 5, len(x) * 4 // 5 - n, n)]
    return np.array([m for m in marks if m is not None])


def trim(buf, floor_db=-40.0, rms=0.15):
    """Cut the near-silence at both ends, set the loudness (by RMS: a held
    voice carries far more energy than a plucked note of the same peak), then
    a 10 ms fade in and 50 ms out."""
    env = np.abs(buf).max(axis=1)
    loud = np.nonzero(env > env.max() * 10 ** (floor_db / 20))[0]
    buf = buf[loud[0]: loud[-1] + 1]
    buf = buf * min(rms / np.sqrt((buf ** 2).mean()), 0.9 / env.max())
    k = min(len(buf), int(0.01 * SR))
    buf[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
    return sampler.fade_tail(np.ascontiguousarray(buf, dtype=np.float32))


def retune(buf, cents_off):
    """Resample so a note `cents_off` / 100 semitones sharp lands on pitch."""
    up = int(round(1000 * 2 ** (cents_off / 1200)))
    return resample_poly(buf, up, 1000, axis=0).astype(np.float32)


def make(log=print):
    """Generate, check and file the takes. -> number of key zones written."""
    api_key = cloud.key(C.ELEVENLABS_KEY_ENV)
    if not api_key:
        log(f"[vocal] no {C.ELEVENLABS_KEY_ENV} in the environment; the voices stay silent")
        return 0
    os.makedirs(C.VOCAL_DIR, exist_ok=True)
    zones = {}
    for i, prompt in enumerate(C.VOCAL_PROMPTS, 1):
        try:
            raw = cloud.sound(prompt, C.VOCAL_SECONDS, api_key)
        except Exception as e:
            log(f"[vocal] take {i}: {e}")
            continue
        take = os.path.join(C.VOCAL_DIR, f"take{i}.mp3")          # the original, for listening
        with open(take, "wb") as f:
            f.write(raw)
        buf = trim(sampler.read_audio(take))
        track = pitch_track(buf.mean(axis=1))
        if len(track) < 3:
            log(f"[vocal] take {i}: no steady pitch found, skipped")
            continue
        lo, hi = np.percentile(track, [25, 75])
        if hi - lo > STEADY:
            log(f"[vocal] take {i}: pitch wanders by {hi - lo:.1f} semitones, skipped")
            continue
        heard = float(np.median(track))
        midi = int(round(heard))
        if midi in zones:
            log(f"[vocal] take {i}: MIDI {midi} again, skipped")
            continue
        name = f"{midi}.wav"
        sf.write(os.path.join(C.VOCAL_DIR, name), retune(buf, 100 * (heard - midi)), SR)
        zones[midi] = dict(midi=midi, file=name, heard=round(heard, 2), take=os.path.basename(take))
        log(f"[vocal] take {i}: MIDI {heard:.2f} -> {midi}, {len(buf) / SR:.1f}s")
    if zones:
        with open(os.path.join(C.VOCAL_DIR, "keymap.json"), "w") as f:
            json.dump([zones[m] for m in sorted(zones)], f, indent=1)
    return len(zones)


def load(log=print):
    """The voices keymap, made first if it is not on disk yet. None when there
    is no key or no usable take (DeskBand runs on without the voices)."""
    km = sampler.load_keymap_dir("vocal", C.VOCAL_DIR, 8.0)
    if km is None and make(log):
        km = sampler.load_keymap_dir("vocal", C.VOCAL_DIR, 8.0)
    return km


if __name__ == "__main__":
    print(f"{make()} zones in {C.VOCAL_DIR}")
