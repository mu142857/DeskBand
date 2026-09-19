"""Composer: turns the step clock into note events.

The harmony is a one-bar-per-chord loop with fixed close voicings
(F A C E - G B D E - E G B D - E A B C). Every part is derived from the
current chord's voicing or root, and melodic notes come from the C major
pentatonic, so whatever objects are on the desk the result is in tune.

In math mode (Composer.set_math) the melodic parts are computed rather than
patterned, so nothing comes round again: see Sequence and each part's plan_math.
Bass, drums and strings keep their patterns either way.

An event is (part, voice, midi_or_hit, velocity, duration_steps[, delay_steps]);
delay_steps is a fraction of a 16th, used to roll chords.
"""

import math
import random
import zlib
from collections import deque
from dataclasses import dataclass

from . import config as C
from .motifs import default_seed

P = C.STEPS_PER_PHRASE
ACC = set(C.ACCENTS)
PHI = (1 + 5 ** 0.5) / 2
# Speeds of the contour's rows. Irrational, so no row ever returns to a value it has had.
ROTATIONS = (PHI - 1, 2 ** 0.5 - 1, 3 ** 0.5 - 1, 5 ** 0.5 - 2, math.pi - 3)


def in_range(pcs, lo, hi):
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def nearest(pool, prev, span=7):
    near = [m for m in pool if abs(m - prev) <= span]
    return near or pool


def weight(s):
    """How strong step s of the bar is: 4 the downbeat, 3 the other 3-3-2
    accents, 2 the beats, 1 the other 8ths, 0 the 16ths in between."""
    if s == 0:
        return 4
    if s in ACC:
        return 3
    if s % 4 == 0:
        return 2
    return 1 if s % 2 == 0 else 0


def euclid(k, n, rotate=0):
    """Euclidean rhythm: k onsets spread as evenly as n slots allow, turned by
    `rotate` slots. E(3, 8) is the 3-3-2 of ACCENTS. -> sorted slot indices."""
    k = max(0, min(k, n))
    return sorted((-(-i * n // k) + rotate) % n for i in range(k))


class Sequence:
    """Math mode's source of numbers in [0, 1): deterministic, never repeating.

    contour() is 1/f noise by Voss's method: row k holds its value for 2**k
    draws, and each row steps round an irrational rotation (frac(j * alpha), a
    Weyl sequence), so neither a row nor their sum ever comes back to where it
    was. Melodies have roughly this 1/f spectrum (Voss & Clarke, 1975): close
    from one note to the next, wandering over a phrase.
    chaos() is the logistic map x -> r x (1 - x) in its chaotic range, spread
    evenly over [0, 1) by the arcsine change of variable; it decides rhythms."""

    def __init__(self, name):
        seed = zlib.crc32(name.encode()) / 2 ** 32
        self.n = 0
        self.phase = [(seed * (k + 2) * PHI) % 1.0 for k in range(len(ROTATIONS))]
        self.x = 0.2 + 0.6 * seed

    def contour(self):
        self.n += 1
        rows = [((self.n >> k) * a + p) % 1.0 for k, (a, p) in enumerate(zip(ROTATIONS, self.phase))]
        return sum(rows) / len(rows)

    def chaos(self):
        self.x = C.LOGISTIC_R * self.x * (1 - self.x)
        if not 1e-12 < self.x < 1 - 1e-12:           # round-off onto the fixed point: step off it
            self.x = (self.n * PHI) % 0.8 + 0.1
        return min(2 / math.pi * math.asin(math.sqrt(self.x)), 0.999999)

    def pick(self, lo, hi):
        """An integer in lo..hi from the chaotic map."""
        return lo + int(self.chaos() * (hi - lo + 1))

    def walk(self, ladder, prev, leap=2):
        """Next note on `ladder`: head for where the contour points, at most
        `leap` rungs at a time, so the line moves mostly by step. Standing on the
        target, it usually leans a rung towards where the contour really is
        rather than repeat the note."""
        i = min(range(len(ladder)), key=lambda j: abs(ladder[j] - prev))
        target = self.contour() * (len(ladder) - 1)
        move = max(-leap, min(leap, round(target) - i))
        if move == 0 and self.chaos() < 0.6:
            move = 1 if target >= i else -1
        return ladder[min(max(i + move, 0), len(ladder) - 1)]


class Chord:
    def __init__(self, name, root, voicing):
        self.name, self.root, self.voicing = name, root, voicing
        self.pcs = sorted({m % 12 for m in voicing} | {root})
        # chord tones that are also pentatonic (any chord tone if a remote style has none)
        self.strong = [p for p in self.pcs if p in C.PENTATONIC] or self.pcs


CHORDS = [Chord(*c) for c in C.CHORDS]


@dataclass(frozen=True)
class NoteEvent:
    """One audible note or drum hit in a complete chord cycle."""

    part: str
    voice: str
    note: int | str
    step: int
    duration_steps: int
    velocity: float
    delay_steps: float = 0.0


class Pattern:
    """Base: plans one bar (dict step -> list of (midi, vel, dur, delay)) at a time."""
    GRID = 2              # embellishments fall on 8ths; slow parts use quarters
    FILL_CHORD = False    # embellishments use chord tones rather than the pentatonic

    def __init__(self, name, spec, seed=None):
        self.name = name
        self.voice = spec["voice"]
        self.lo, self.hi = spec["lo"], spec["hi"]
        self.seed = default_seed(name) if seed is None else seed
        self.rng = random.Random(self.seed)
        self.orn = random.Random(zlib.crc32(name.encode()))
        self.complexity = 0.5
        self.seq = Sequence(name)
        self.prev = (self.lo + self.hi) // 2
        self.bar = {}
        self.loop_len = len(CHORDS)       # bars in the chord loop (the composer keeps it current)

    def reset_cycle(self, seed):
        """Replay this item's motif from the same starting state each loop."""
        self.seed = seed
        self.rng.seed(seed)
        self.orn.seed(zlib.crc32(self.name.encode()))
        self.prev = (self.lo + self.hi) // 2

    def put(self, step, midi, vel, dur, delay=0.0):
        self.bar.setdefault(step, []).append((midi, vel, dur, delay))

    def plan(self, chord, nxt):
        self.bar = {}

    def plan_math(self, chord, nxt):
        """Math mode; parts without a computed version keep their pattern."""
        self.plan(chord, nxt)

    def events(self, s):
        return [(self.name, self.voice, m, v, d, dl) for m, v, d, dl in self.bar.get(s, [])]

    def rhythmic_events(self, s):
        """A safe extra onset requested by the FPGA on an unwritten step.

        Re-articulate one nearby note from this bar instead of inventing an
        unconstrained pitch. The FPGA therefore owns the new rhythm while the
        Mac keeps every generated note inside the current chord/scale plan.
        """
        if s in self.bar or not self.bar:
            return []
        earlier = [step for step in self.bar if step < s]
        source = max(earlier) if earlier else min(self.bar)
        notes = self.bar[source]
        pitched = [note for note in notes if isinstance(note[0], int)]
        if not pitched:
            return []
        midi, velocity, duration, _delay = max(pitched, key=lambda note: note[0])
        duration = min(max(int(duration), 1), max(2, 2 * self.GRID))
        return [(self.name, self.voice, midi, 0.72 * velocity, duration, 0.0)]

    # --- complexity: the stage's x axis, applied to each planned bar
    def arrange(self, chord):
        """Inside config.STAGE_AS_WRITTEN the bar is left alone. Below it notes
        drop away from the weakest beats first, down to the downbeat alone;
        above it the gaps fill in."""
        lo, hi = C.STAGE_AS_WRITTEN
        c = self.complexity
        if c < lo:
            self.thin(4 * min(1.0, (lo - c) / (0.85 * lo)))
        elif c > hi:
            self.embellish(chord, min(1.0, (c - hi) / (1 - hi)))

    def thin(self, need):
        """Keep the notes on steps at least `need` strong (see weight). Never
        silent: if nothing is left, the strongest step stays."""
        kept = {s: notes for s, notes in self.bar.items() if weight(s) >= need}
        if not kept and self.bar:
            s = max(self.bar, key=lambda s: (weight(s), -s))
            kept = {s: self.bar[s]}
        self.bar = kept

    def fill_pool(self, chord):
        return in_range(chord.pcs if self.FILL_CHORD else C.PENTATONIC, self.lo, self.hi)

    def embellish(self, chord, a):
        """a in 0..1. Empty grid slots fill (more of them as a rises) with notes
        stepping from the line's last note towards its next one, so several in a
        row make a run. Past a = 0.5, 8th-note parts also lead into some of
        their notes with a 16th grace note a step away."""
        rng, pool = self.orn, self.fill_pool(chord)
        if not self.bar or not pool:
            return
        top = {s: max(notes)[:2] for s, notes in self.bar.items()}     # (midi, vel) of each step's top note
        written = sorted(top)

        def near(m):
            return min(range(len(pool)), key=lambda j: abs(pool[j] - m))

        for s in range(0, P, self.GRID):
            if s in top or rng.random() >= 0.8 * a:
                continue
            before = [t for t in top if t < s]
            after = [t for t in top if t > s]
            m, v = top[max(before)] if before else top[min(after)]
            ahead = top[min(after)][0] if after else m
            move = (ahead > m) - (ahead < m) or rng.choice((-1, 1))
            i = near(m)
            j = min(max(i + move, 0), len(pool) - 1)
            if j == i:                                   # at the edge of the register: turn round
                j = min(max(i - move, 0), len(pool) - 1)
            v *= rng.uniform(0.6, 0.8)
            self.put(s, pool[j], v, 2 * self.GRID)
            top[s] = (pool[j], v)
        if self.GRID == 2 and a > 0.5:
            for s in written:
                if s == 0 or s - 1 in self.bar or rng.random() >= a - 0.4:
                    continue
                m, v = top[s]
                j = min(max(near(m) + rng.choice((-1, 1)), 0), len(pool) - 1)
                if pool[j] != m:
                    self.put(s - 1, pool[j], 0.5 * v, 1)


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

    def reset_cycle(self, seed):
        super().reset_cycle(seed)
        self.motif = None
        self.bars_left = 0

    def roll(self, chord):
        """The chord: bottom to top, ~27 ms apart, top note a touch louder."""
        rng = self.rng
        n = len(chord.voicing)
        for i, m in enumerate(chord.voicing):
            vel = rng.uniform(0.40, 0.48) + (0.08 if i == n - 1 else 0.0)
            self.put(0, m, vel, P + 6, delay=0.22 * i)
        if rng.random() < 0.45:                      # quiet restrike of the upper notes
            for i, m in enumerate(chord.voicing[-2:]):
                self.put(10, m, rng.uniform(0.28, 0.36), P, delay=0.2 * i)

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        self.roll(chord)
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

    def plan_math(self, chord, nxt):
        """The same chord, but the line above it is computed afresh every bar: a
        Euclidean rhythm of 2-4 eighths, pitches walking a 1/f contour."""
        self.bar = {}
        self.roll(chord)
        seq = self.seq
        ladder = in_range(C.PENTATONIC, self.lo, self.hi)
        strong = in_range(chord.strong, self.lo, self.hi)
        for slot in euclid(seq.pick(2, 4), 8, seq.pick(0, 7)):
            s = 2 * slot
            if s == 0:                                   # the downbeat belongs to the chord
                continue
            self.prev = seq.walk(ladder, self.prev)
            if s in ACC:
                self.prev = min(strong, key=lambda m: abs(m - self.prev))
            self.put(s, self.prev, 0.5 + 0.16 * seq.chaos(), P)


class Keys(Pattern):
    """Laptop: a soft electric-piano shimmer, the voicing an octave up played
    in dotted 8ths so it drifts across the piano's downbeats."""
    STEPS = [2, 5, 8, 11, 14]

    def __init__(self, name, spec):
        super().__init__(name, spec)
        self.j = 0

    def reset_cycle(self, seed):
        super().reset_cycle(seed)
        self.j = 0

    def plan(self, chord, nxt):
        self.bar = {}
        notes = [m + 12 for m in chord.voicing]
        seq = notes + notes[-2:0:-1]
        for s in self.STEPS:
            self.put(s, seq[self.j % len(seq)], self.rng.uniform(0.35, 0.5), 8)
            self.j += 1

    def plan_math(self, chord, nxt):
        """3-6 notes on a turned Euclidean grid of 16ths, each voicing note
        chosen by the contour."""
        self.bar = {}
        seq = self.seq
        notes = [m + 12 for m in chord.voicing]
        for s in euclid(seq.pick(3, 6), P, seq.pick(0, P - 1)):
            self.put(s, notes[round(seq.contour() * (len(notes) - 1))], 0.35 + 0.15 * seq.chaos(), 8)


class Guitar(Pattern):
    """Fingerpicked: root on the downbeat, voicing notes falling after it."""
    FILL_CHORD = True

    def pluck_root(self, chord):
        self.put(0, in_range([chord.root], self.lo - 8, self.lo + 7)[0], 0.75, 14)

    def reachable(self, chord):
        """The voicing notes the guitar can reach, top first."""
        return ([m for m in chord.voicing if self.lo <= m <= self.hi] or in_range(chord.pcs, self.lo, self.hi))[::-1]

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        self.pluck_root(chord)
        notes = self.reachable(chord)
        j = rng.randrange(len(notes))
        for s in (4, 6, 10, 12, 14):
            self.put(s, notes[j % len(notes)], rng.uniform(0.45, 0.6), 10)
            j += 1

    def plan_math(self, chord, nxt):
        """Root on the downbeat still; the picking is a turned Euclidean rhythm
        of eighths, each note chosen by the contour."""
        self.bar = {}
        seq = self.seq
        self.pluck_root(chord)
        notes = self.reachable(chord)
        for slot in euclid(seq.pick(3, 6), 8, seq.pick(1, 7)):
            if slot:                                     # the downbeat is the root's
                self.put(2 * slot, notes[round(seq.contour() * (len(notes) - 1))], 0.45 + 0.15 * seq.chaos(), 10)


class Bass(Pattern):
    """Double bass: the chord root, only the root, on the 3-3-2 accents. The
    register (C1-B1) holds exactly one root per chord."""
    FILL_CHORD = True

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

    def embellish(self, chord, a):
        """Busier kit: 16th hats between the 8ths, ghost rims leading into the
        accents, the kick filling in the 3-3-2."""
        rng = self.orn
        for s in range(1, P, 2):
            if rng.random() < a:
                self.put(s, "hat", rng.uniform(0.1, 0.16), 1)
        for s in (5, 11, 15):
            if rng.random() < 0.6 * a:
                self.put(s, "rim", rng.uniform(0.14, 0.22), 1)
        if rng.random() < a:
            self.put(6, "kick", 0.45, 1)

    def events(self, s):
        return [(self.name, "drums", hit, v, d, 0.0) for hit, v, d, _ in self.bar.get(s, [])]

    def rhythmic_events(self, s):
        """FPGA-created drum onsets are quiet hats, never surprise kicks."""
        if s in self.bar:
            return []
        velocity = 0.18 if s % 2 == 0 else 0.12
        return [(self.name, "drums", "hat", velocity, 1, 0.0)]


class Strings(Pattern):
    """Sustained voicing, held a little past the bar line so bars overlap."""
    GRID, FILL_CHORD = 4, True        # the bows are slow: a counter-line in quarters at most

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

    def plan_math(self, chord, nxt):
        """1-3 chord tones on a turned Euclidean grid of 16ths, walking the contour."""
        self.bar = {}
        seq = self.seq
        strong = in_range(chord.strong, self.lo, self.hi)
        for s in euclid(seq.pick(1, 3), P, seq.pick(0, P - 1)):
            self.prev = seq.walk(strong, self.prev)
            self.put(s, self.prev, 0.45 + 0.25 * seq.chaos(), P)


class Vocal(Pattern):
    """Voices (ElevenLabs "ooh" samples): a slow sung line on chord tones, one
    or two long notes a bar, each moving to a near one, with a quieter second
    voice on the chord tone below."""
    GRID, FILL_CHORD = 4, True

    def sing(self, step, midi, dur, chord):
        self.put(step, midi, 0.55, dur)
        below = in_range(chord.pcs, self.lo - 5, midi - 3)
        if below:
            self.put(step, below[-1], 0.35, dur)

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        strong = in_range(chord.strong, self.lo, self.hi)
        self.prev = rng.choice(nearest(strong, self.prev, 4))
        two = rng.random() < 0.4
        self.sing(0, self.prev, 10 if two else P + 4, chord)
        if two:
            self.prev = rng.choice(nearest([m for m in strong if m != self.prev] or strong, self.prev, 5))
            self.sing(8, self.prev, P - 4, chord)

    def plan_math(self, chord, nxt):
        """One or two notes a bar (a Euclidean split of the four beats), each
        walking the contour over the chord tones; notes overlap a beat, legato."""
        self.bar = {}
        seq = self.seq
        strong = in_range(chord.strong, self.lo, self.hi)
        beats = euclid(seq.pick(1, 2), 4)
        for a, b in zip(beats, beats[1:] + [4]):
            self.prev = seq.walk(strong, self.prev)
            self.sing(4 * a, self.prev, 4 * (b - a) + 4, chord)


PATTERNS = {"piano": Piano, "keys": Keys, "guitar": Guitar, "bass": Bass,
            "drums": Drums, "strings": Strings, "bells": Bells, "vocal": Vocal}


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
    def __init__(self, chords=None, motif_seeds=None):
        self.motif_seeds = {name: default_seed(name) for name in C.INSTRUMENTS}
        if motif_seeds:
            self.motif_seeds.update(motif_seeds)
        self.parts = {name: PATTERNS[spec["voice"]](name, spec)
                      for name, spec in C.INSTRUMENTS.items()}
        self.backing = Backing()
        self.chords = [Chord(c.name, c.root, list(c.voicing)) for c in CHORDS] if chords is None else [Chord(*c) for c in chords]
        for part in self.parts.values():
            part.loop_len = len(self.chords)
        self.pending = None            # a new chord loop waiting for the next loop start
        self._style_requests = deque() # main thread appends; audio thread drains at bar boundaries
        self._publishing = False
        self.bar_count = -1
        self.chord_index = 0
        self.math = C.MATH_MODE
        # A single immutable publication. Readers never traverse self.chords while
        # the audio callback changes the active style.
        self.active_chords = self._chord_specs()

    def _chord_specs(self):
        return tuple((c.name, c.root, tuple(c.voicing)) for c in self.chords)

    @property
    def style_pending(self):
        return self._publishing or self.pending is not None or bool(self._style_requests)

    def set_motif_seed(self, name, seed):
        """A replacement motif takes effect on the next complete loop."""
        if name not in self.parts:
            raise KeyError(name)
        updated = self.motif_seeds.copy()
        updated[name] = int(seed)
        self.motif_seeds = updated

    @property
    def chord_name(self):
        return self.chords[self.chord_index].name

    def set_math(self, on=None):
        """Math mode on / off (None flips it). Parts plan a bar at a time, so
        it is heard from the next bar line."""
        self.math = (not self.math) if on is None else bool(on)

    def set_complexity(self, name, c):
        """The stage's x axis for one part, 0..1. Heard from the next bar line."""
        self.parts[name].complexity = min(max(float(c), 0.0), 1.0)

    def rhythmic_events(self, name, step):
        """Return chord-safe notes for a new onset generated by the FPGA."""
        part = self.parts.get(name)
        return [] if part is None else part.rhythmic_events(step % P)

    def request_style(self, chords):
        """chords: [(name, root_pc, [midi...]), ...]. Takes effect when the
        current loop comes round, so the change always lands on a downbeat."""
        self._style_requests.append(tuple((name, root, tuple(voicing)) for name, root, voicing in chords))

    def step(self, step):
        s = step % P
        if s == 0:
            self._publishing = self.pending is not None
            try:
                self.bar_count += 1
                while self._style_requests:
                    self._publishing = True
                    self.pending = [Chord(*c) for c in self._style_requests.popleft()]
                if self.pending is not None and self.bar_count % len(self.chords) == 0:
                    self.chords, self.pending, self.bar_count = self.pending, None, 0
                    for p in self.parts.values():
                        p.loop_len = len(self.chords)
                if not self.math and self.bar_count % len(self.chords) == 0:
                    seeds = self.motif_seeds
                    for name, p in self.parts.items():
                        p.reset_cycle(seeds[name])
                self.active_chords = self._chord_specs()
            finally:
                self._publishing = False
            self.chord_index = self.bar_count % len(self.chords)
            chord = self.chords[self.chord_index]
            nxt = self.chords[(self.chord_index + 1) % len(self.chords)]
            self.backing.plan(chord, nxt)
            for p in self.parts.values():
                (p.plan_math if self.math else p.plan)(chord, nxt)
                p.arrange(chord)
        events = self.backing.events(s)
        for p in self.parts.values():
            events.extend(p.events(s))
        return events


def score_cycle(chords, names, motif_seeds=None, *, math_mode=False, complexities=None):
    """The exact note/hit score a fresh local Composer plays for one cycle.

    `chords` is a tuple of (name, root, MIDI voicing) specs. Both a future
    exporter and the ending screen can consume these immutable events.
    """
    chosen = set(names)
    composer = Composer(chords=chords, motif_seeds=motif_seeds)
    composer.set_math(math_mode)
    for name, value in (complexities or {}).items():
        composer.set_complexity(name, value)
    events = []
    for step in range(P * len(chords)):
        for part, voice, note, velocity, duration, delay in composer.step(step):
            if part in chosen:
                events.append(NoteEvent(part, voice, note, step, duration, velocity, delay))
    return tuple(events)
