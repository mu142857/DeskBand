"""Composer: turns the step clock into note events.

The harmony is a one-bar-per-chord loop with fixed close voicings
(F A C E - G B D E - E G B D - E A B C). Every part is derived from the
current chord's voicing or root, and melodic notes come from the C major
pentatonic, so whatever objects are on the desk the result is in tune.

An event is (part, voice, midi_or_hit, velocity, duration_steps[, delay_steps]);
delay_steps is a fraction of a 16th, used to roll chords.
"""

import random

from . import config as C

P = C.STEPS_PER_PHRASE
ACC = set(C.ACCENTS)


def in_range(pcs, lo, hi):
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def nearest(pool, prev, span=7):
    near = [m for m in pool if abs(m - prev) <= span]
    return near or pool


class Chord:
    def __init__(self, name, root, voicing):
        self.name, self.root, self.voicing = name, root, voicing
        self.pcs = sorted({m % 12 for m in voicing} | {root})
        # chord tones that are also pentatonic (any chord tone if a remote style has none)
        self.strong = [p for p in self.pcs if p in C.PENTATONIC] or self.pcs


CHORDS = [Chord(*c) for c in C.CHORDS]


class Pattern:
    """Base: plans one bar (dict step -> list of (midi, vel, dur, delay)) at a time."""

    def __init__(self, name, spec):
        self.name = name
        self.voice = spec["voice"]
        self.lo, self.hi = spec["lo"], spec["hi"]
        self.rng = random.Random(hash(name) & 0xFFFF)
        self.prev = (self.lo + self.hi) // 2
        self.bar = {}
        self.loop_len = len(CHORDS)       # bars in the chord loop (the composer keeps it current)

    def put(self, step, midi, vel, dur, delay=0.0):
        self.bar.setdefault(step, []).append((midi, vel, dur, delay))

    def plan(self, chord, nxt):
        self.bar = {}

    def events(self, s):
        return [(self.name, self.voice, m, v, d, dl) for m, v, d, dl in self.bar.get(s, [])]


class Piano(Pattern):
    """Hazy piano: the voicing rolled softly on the downbeat and left to ring
    into the next bar, with a sparse motif above it. One motif (rhythm plus
    contour) is invented per trip round the loop and restated over each chord."""
    MELODY_STEPS = [4, 6, 8, 10, 12, 14]

    def __init__(self, name, spec):
        super().__init__(name, spec)
        self.motif = None
        self.bars_left = 0

    def new_motif(self):
        rng = self.rng
        steps = sorted(rng.sample(self.MELODY_STEPS, rng.randint(2, 3)))
        contour = [rng.choice([0, 1, 2])]
        for _ in steps[1:]:
            contour.append(contour[-1] + rng.choice([-2, -1, -1, 1, 1]))
        return steps, contour

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        # --- the chord: bottom to top, ~27 ms apart, top note a touch louder
        n = len(chord.voicing)
        for i, m in enumerate(chord.voicing):
            vel = rng.uniform(0.40, 0.48) + (0.08 if i == n - 1 else 0.0)
            self.put(0, m, vel, P + 6, delay=0.22 * i)
        if rng.random() < 0.45:                      # quiet restrike of the upper notes
            for i, m in enumerate(chord.voicing[-2:]):
                self.put(10, m, rng.uniform(0.28, 0.36), P, delay=0.2 * i)
        # --- the line above it
        if self.bars_left == 0:
            self.motif = self.new_motif()
            self.bars_left = self.loop_len
        self.bars_left -= 1
        steps, contour = self.motif
        ladder = in_range(C.PENTATONIC, self.lo, self.hi)
        strong = in_range(chord.strong, self.lo, self.hi)
        centre = (self.lo + self.hi) // 2
        anchor = min(strong, key=lambda m: abs(m - centre))
        base = ladder.index(min(ladder, key=lambda m: abs(m - anchor)))
        for i, s in enumerate(steps):
            midi = ladder[min(max(base + contour[i], 0), len(ladder) - 1)]
            if s in ACC:
                midi = min(strong, key=lambda m: abs(m - midi))
            self.put(s, midi, rng.uniform(0.5, 0.66), P)


class Keys(Pattern):
    """Laptop: a soft electric-piano shimmer, the voicing an octave up played
    in dotted 8ths so it drifts across the piano's downbeats."""
    STEPS = [2, 5, 8, 11, 14]

    def __init__(self, name, spec):
        super().__init__(name, spec)
        self.j = 0

    def plan(self, chord, nxt):
        self.bar = {}
        notes = [m + 12 for m in chord.voicing]
        seq = notes + notes[-2:0:-1]
        for s in self.STEPS:
            self.put(s, seq[self.j % len(seq)], self.rng.uniform(0.35, 0.5), 8)
            self.j += 1


class Guitar(Pattern):
    """Fingerpicked: root on the downbeat, voicing notes falling after it."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        roots = in_range([chord.root], self.lo - 8, self.lo + 7)
        self.put(0, roots[0], 0.75, 14)
        notes = ([m for m in chord.voicing if self.lo <= m <= self.hi] or in_range(chord.pcs, self.lo, self.hi))[::-1]
        j = rng.randrange(len(notes))
        for s in (4, 6, 10, 12, 14):
            self.put(s, notes[j % len(notes)], rng.uniform(0.45, 0.6), 10)
            j += 1


class Bass(Pattern):
    """Double bass: the chord root, only the root, on the 3-3-2 accents. The
    register (C1-B1) holds exactly one root per chord."""

    def plan(self, chord, nxt):
        self.bar = {}
        root = in_range([chord.root], self.lo, self.hi)[0]
        acc = C.ACCENTS
        for i, s in enumerate(acc):
            nxt_s = acc[i + 1] if i + 1 < len(acc) else P
            self.put(s, root, 0.9 if s == 0 else 0.62, nxt_s - s)


class Drums(Pattern):
    """Trap Heat kit played quietly: kick, rim on 2 and 4, closed hats."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        self.put(0, "kick", 0.75, 1)
        self.put(10, "kick", 0.5, 1)
        for s in (4, 12):
            self.put(s, "rim" if rng.random() < 0.7 else "snap", 0.5, 1)
        for s in range(0, P, 2):
            self.put(s, "hat", 0.3 if s % 4 == 0 else 0.2, 1)
        if rng.random() < 0.25:
            self.put(14, "hat_open", 0.25, 1)

    def events(self, s):
        return [(self.name, "drums", hit, v, d, 0.0) for hit, v, d, _ in self.bar.get(s, [])]


class Strings(Pattern):
    """Sustained voicing, held a little past the bar line so bars overlap."""

    def plan(self, chord, nxt):
        self.bar = {}
        v = chord.voicing
        low = in_range([chord.root], self.lo - 12, self.lo)[-1:]      # root an octave down
        for i, m in enumerate(low + [v[0], v[len(v) // 2], v[-1]]):       # bottom, middle, top
            if m < self.lo - 12 or m > self.hi:
                continue
            self.put(0, m, 0.55 - 0.05 * i, P + 3)


class Bells(Pattern):
    """Glockenspiel: one or two high chord tones a bar, off the beat."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        strong = in_range(chord.strong, self.lo, self.hi)
        for s in sorted(rng.sample([2, 6, 10, 14], rng.randint(1, 2))):
            self.prev = rng.choice(nearest(strong, self.prev, 5))
            self.put(s, self.prev, rng.uniform(0.45, 0.7), P)


PATTERNS = {"piano": Piano, "keys": Keys, "guitar": Guitar, "bass": Bass,
            "drums": Drums, "strings": Strings, "bells": Bells}


class Backing(Pattern):
    """Optional bed (off by default, see config.BACKING)."""

    def __init__(self):
        super().__init__("backing", dict(voice="mix", lo=36, hi=47))

    def plan(self, chord, nxt):
        self.bar = {}
        root = in_range([chord.root], 36, 47)[0]
        if C.BACKING["perc"]:
            for s in range(0, P, 2):
                self.put(s, ("drums", "shaker"), 0.45 if s % 4 == 0 else 0.3, 1)
            for s in (4, 12):
                self.put(s, ("drums", "rim"), 0.3, 1)
        if C.BACKING["sub"]:
            acc = C.ACCENTS
            for i, s in enumerate(acc):
                nxt_s = acc[i + 1] if i + 1 < len(acc) else P
                self.put(s, ("sub", root), 0.5, nxt_s - s)

    def events(self, s):
        return [("backing", kind, m, v, d, 0.0) for (kind, m), v, d, _ in self.bar.get(s, [])]


class Composer:
    def __init__(self):
        self.parts = {name: PATTERNS[spec["voice"]](name, spec)
                      for name, spec in C.INSTRUMENTS.items()}
        self.backing = Backing()
        self.chords = list(CHORDS)
        self.pending = None            # a new chord loop waiting for the next loop start
        self.bar_count = -1
        self.chord_index = 0

    @property
    def chord_name(self):
        return self.chords[self.chord_index].name

    def request_style(self, chords):
        """chords: [(name, root_pc, [midi...]), ...]. Takes effect when the
        current loop comes round, so the change always lands on a downbeat."""
        self.pending = [Chord(*c) for c in chords]

    def step(self, step):
        s = step % P
        if s == 0:
            self.bar_count += 1
            if self.pending is not None and self.bar_count % len(self.chords) == 0:
                self.chords, self.pending, self.bar_count = self.pending, None, 0
                for p in self.parts.values():
                    p.loop_len = len(self.chords)
                    if hasattr(p, "bars_left"):
                        p.bars_left = 0                  # new harmony, new motif
            self.chord_index = self.bar_count % len(self.chords)
            chord = self.chords[self.chord_index]
            nxt = self.chords[(self.chord_index + 1) % len(self.chords)]
            self.backing.plan(chord, nxt)
            for p in self.parts.values():
                p.plan(chord, nxt)
        events = self.backing.events(s)
        for p in self.parts.values():
            events.extend(p.events(s))
        return events
