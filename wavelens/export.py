"""Render one frozen arrangement with an isolated, Mac-clocked audio engine."""

import os
import hashlib
import tempfile
from datetime import datetime
from dataclasses import dataclass

import numpy as np
import soundfile as sf

from . import config as C, sampler
from .music import score_cycle
from .stage import loudness_gain
from .synth import Engine


@dataclass(frozen=True)
class RenderedLoop:
    fingerprint: str
    path: str
    sample_rate: int
    frames: int
    sha256: str = ""

    @property
    def duration(self):
        return self.frames / self.sample_rate


class _SnapshotComposer:
    """Feed the engine the same frozen item events drawn on the Collections page."""

    def __init__(self, snapshot):
        self.backing = snapshot.make_composer()
        self.events = {}
        for event in snapshot.events:
            self.events.setdefault(event.step, []).append(
                (event.part, event.voice, event.note, event.velocity,
                 event.duration_steps, event.delay_steps))

    @property
    def bar_view(self):
        """The engine marks each bar with it for the stage's rings; nothing reads it here."""
        return self.backing.bar_view

    def step(self, step):
        backing = [event for event in self.backing.step(step) if event[0] == "backing"]
        return backing + self.events.get(step, [])


def _load_selected(engine, snapshot, progress):
    voices = {item.name: C.INSTRUMENTS[item.name]["voice"] for item in snapshot.items
              if item.selected}
    for name, kind in voices.items():
        if kind in ("keys", "arp", "sub"):
            continue
        progress(f"Loading {C.INSTRUMENTS[name]['label']}…")
        if kind == "drums":
            engine.drums = sampler.load_drums()
            if not engine.drums:
                raise RuntimeError("Drum samples are unavailable")
        elif kind == "vocal":
            # Existing takes only. Export must never generate or upload audio.
            km = sampler.load_keymap_dir("vocal", C.VOCAL_DIR, 8.0)
            if km is None or not km.ready:
                raise RuntimeError("Voice samples are unavailable; deselect that instrument or prepare them first")
            engine.keymaps[kind] = km
        else:
            km = (sampler.load_concert_grand() if kind == "piano" else
                  sampler.load_kings_cross() if kind == "strings" else
                  sampler.load_bari_sax() if kind == "sax" else None)
            if km is None and kind in C.SAMPLE_SETS:
                km = sampler.load_set(kind)
            if km is None or not km.ready:
                raise RuntimeError(f"{C.INSTRUMENTS[name]['label']} samples are unavailable")
            engine.keymaps[kind] = km


def render_loop(snapshot, progress=lambda message: None, *, folder=None):
    """Write a validated stereo PCM16 WAV atomically; return its provenance."""
    if not snapshot.selected:
        raise ValueError("Choose at least one item to render")
    if snapshot.style_pending:
        raise ValueError("Wait for the pending chord change")
    if snapshot.sample_rate != C.SAMPLE_RATE:
        raise ValueError("The output sample rate changed; rebuild the arrangement")
    ordered = tuple(item.name for item in snapshot.items)
    expected = score_cycle(snapshot.chords, ordered,
                           {item.name: item.motif_seed for item in snapshot.items},
                           math_mode=snapshot.math_mode,
                           complexities={item.name: item.stage_pos[0] for item in snapshot.items
                                         if item.stage_pos})
    expected = tuple(event for event in expected if event.part in snapshot.selected)
    if expected != snapshot.events:
        raise ValueError("The displayed score changed; refresh the arrangement")

    engine = Engine(_SnapshotComposer(snapshot))
    engine.set_bpm(snapshot.bpm)
    engine.set_fpga_mode(False)
    _load_selected(engine, snapshot, progress)
    for item in snapshot.items:
        part = engine.parts[item.name]
        part.target = part.gain = float(item.selected)
        trim = loudness_gain(item.stage_pos[1]) if item.stage_pos else 1.0
        part.trim = part.trim_to = trim
    engine.parts["backing"].gain = engine.parts["backing"].target
    engine.parts["sfx"].target = engine.parts["sfx"].gain = 0.0
    engine.makeup = C.MAKEUP.get(len(snapshot.selected), 1.0)
    engine.start_transport()               # the engine's clock waits for it (the app: start_band)

    frames = engine.step_len * C.STEPS_PER_BAR * snapshot.bars
    target = os.path.abspath(folder or os.path.join(C.CACHE_DIR, "exports"))
    os.makedirs(target, exist_ok=True)
    name = f"wavelens-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{snapshot.fingerprint[:10]}.wav"
    path = os.path.join(target, name)
    fd, pending = tempfile.mkstemp(prefix=".render-", suffix=".wav", dir=target)
    os.close(fd)
    peak = 0.0
    try:
        with sf.SoundFile(pending, "w", samplerate=snapshot.sample_rate, channels=2,
                          format="WAV", subtype="PCM_16") as output:
            written = 0
            while written < frames:
                count = min(C.BLOCK_SIZE, frames - written)
                block = np.empty((count, 2), np.float32)
                engine._callback(block, count, None, None)
                if not np.isfinite(block).all():
                    raise RuntimeError("Renderer produced invalid audio")
                peak = max(peak, float(np.max(np.abs(block))))
                # Only the final edge fades. The first downbeat is preserved.
                fade = min(int(0.02 * snapshot.sample_rate), frames)
                if written + count > frames - fade:
                    positions = np.arange(written, written + count)
                    block *= np.clip((frames - 1 - positions) / max(fade - 1, 1), 0, 1)[:, None]
                output.write(block)
                written += count
                if written == frames or written % (C.BLOCK_SIZE * 32) < C.BLOCK_SIZE:
                    progress(f"Rendering {written / frames:.0%}…")
        info = sf.info(pending)
        if (info.frames != frames or info.samplerate != snapshot.sample_rate or
                info.channels != 2 or info.subtype != "PCM_16" or peak < 1e-5 or peak > 1.001):
            raise RuntimeError("The rendered WAV failed validation")
        os.replace(pending, path)
        progress("Loop ready")
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return RenderedLoop(snapshot.fingerprint, path, snapshot.sample_rate, frames,
                            digest.hexdigest())
    finally:
        if os.path.exists(pending):
            os.remove(pending)
