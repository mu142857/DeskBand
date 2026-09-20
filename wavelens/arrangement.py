"""Immutable musical snapshot for the future ending screen and WAV exporter.

Snapshots describe a *new complete cycle* beginning at bar one with the most
recently published active harmony. They do not pretend to capture notes that
are already ringing in the live engine. A pending remote style is marked so a
caller can wait for it to become active before exporting.
"""

import hashlib
import json
from dataclasses import dataclass

from . import config as C
from .music import Composer, NoteEvent, score_cycle


@dataclass(frozen=True)
class ItemScore:
    name: str
    shown: str
    instrument: str
    instrument_label: str
    motif_version: int
    motif_seed: int
    selected: bool
    stage_pos: tuple[float, float] | None
    kind: str                      # "notes" or "rhythm"; drums have hit names
    events: tuple[NoteEvent, ...]

    @property
    def rhythm_steps(self):
        """(step, hit, velocity) cells for a drum grid; empty for pitched parts."""
        if self.kind != "rhythm":
            return ()
        return tuple((event.step, event.note, event.velocity) for event in self.events)


@dataclass(frozen=True)
class ArrangementSnapshot:
    items: tuple[ItemScore, ...]    # all collected entries, selected or not
    chords: tuple[tuple[str, int, tuple[int, ...]], ...]
    bpm: float
    sample_rate: int
    bars: int
    style_pending: bool
    math_mode: bool
    fingerprint: str

    @property
    def selected(self):
        return tuple(item.name for item in self.items if item.selected)

    @property
    def events(self):
        """Only notes and hits included in the song, in score order."""
        order = {name: i for i, name in enumerate(C.INSTRUMENTS)}
        return tuple(sorted((event for item in self.items if item.selected for event in item.events),
                            key=lambda event: (event.step, order[event.part])))

    def make_composer(self):
        """Fresh offline composer with the exact saved motifs and harmony."""
        composer = Composer(chords=self.chords,
                            motif_seeds={item.name: item.motif_seed for item in self.items})
        composer.set_math(self.math_mode)
        for item in self.items:
            if item.stage_pos:
                composer.set_complexity(item.name, item.stage_pos[0])
        return composer


def build_snapshot(shelf, composer, engine):
    """Freeze main-thread shelf/tempo plus callback-published immutable chords.

    Call this from the app's main thread. Engine.set_bpm and shelf edits are
    also main-thread operations; the callback changes `composer.chords` but
    publishes a separate tuple at each bar boundary. No audio-thread lock or
    read of the mutable chord list is needed here.
    """
    # The callback replaces active_chords with one immutable tuple on a bar
    # boundary. BPM and shelf edits are main-thread owned. Retry if the callback
    # publishes a new style during the read; never traverse composer.chords.
    for _ in range(8):
        chords = composer.active_chords
        bpm = float(engine.bpm)
        pending = composer.style_pending
        math_mode = composer.math
        if (chords, bpm, pending, math_mode) == (composer.active_chords, float(engine.bpm),
                                                composer.style_pending, composer.math):
            break
    else:
        raise RuntimeError("musical state changed during snapshot; retry")
    ordered = shelf.order()
    seeds = {name: shelf.entries[name].motif_seed for name in ordered}
    positions = {name: shelf.entries[name].pos for name in ordered}
    score = score_cycle(chords, ordered, seeds, math_mode=math_mode,
                        complexities={name: pos[0] for name, pos in positions.items() if pos})
    by_name = {name: [] for name in ordered}
    for event in score:
        by_name[event.part].append(event)
    items = []
    for name in ordered:
        entry = shelf.entries[name]
        spec = C.INSTRUMENTS[name]
        items.append(ItemScore(name, entry.shown, entry.instrument, spec["label"],
                               entry.motif_version, entry.motif_seed, entry.selected, entry.pos,
                               "rhythm" if spec["voice"] == "drums" else "notes",
                               tuple(by_name[name])))
    items = tuple(items)
    sound_inputs = {
        "selected": [
            {"name": item.name, "instrument": item.instrument,
             "motif_version": item.motif_version, "motif_seed": item.motif_seed,
             "stage_pos": item.stage_pos if item.stage_pos != (0.5, 0.5) else None,
             "spec": {k: C.INSTRUMENTS[item.name][k]
                      for k in ("voice", "lo", "hi", "level", "send")}}
            for item in items if item.selected
        ],
        "chords": chords, "bpm": bpm, "sample_rate": C.SAMPLE_RATE,
        "math_mode": math_mode,
        "steps_per_bar": C.STEPS_PER_BAR, "bars_per_chord": C.BARS_PER_CHORD,
        "pentatonic": C.PENTATONIC, "accents": C.ACCENTS,
        "backing": C.BACKING, "reverb": C.REVERB, "makeup": C.MAKEUP,
        "ceiling": C.CEILING,
    }
    encoded = json.dumps(sound_inputs, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    return ArrangementSnapshot(items, chords, bpm, C.SAMPLE_RATE, len(chords), pending, math_mode,
                               fingerprint)
