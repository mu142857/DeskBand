"""Composer: turns the step clock into note events.

Rules (after Mikutap):
  * one chord per 2-bar phrase, Fmaj7 - Em7 - Dm7 - Cmaj7
  * melodic parts pick notes from the C major pentatonic, so any random
    choice fits; on accents they prefer the chord tones inside it
  * the rhythm skeleton is the 3-3-3-3-2-2 accent pattern (C.ACCENTS)
  * everything lands on the 16th grid; most parts on 8ths
"""

import random

from . import config as C

P = C.STEPS_PER_PHRASE
ACC = set(C.ACCENTS)
# weight of each 16th in a phrase for melodic parts: accents > 8ths > 16ths
WEIGHT = [8 if s in ACC else 3 if s % 2 == 0 else 1 for s in range(P)]


def in_range(pcs, lo, hi):
    return [m for m in range(lo, hi + 1) if m % 12 in pcs]


def nearest(pool, prev, span=7):
    near = [m for m in pool if abs(m - prev) <= span]
    return near or pool


class Chord:
    def __init__(self, name, pcs):
        self.name, self.pcs = name, pcs
        self.root = pcs[0]
        self.strong = [p for p in pcs if p in C.PENTATONIC]   # chord tones that are also pentatonic


CHORDS = [Chord(n, p) for n, p in C.CHORDS]


class Pattern:
    """Base: plans one phrase (dict step -> list of (midi, vel, dur)) at a time."""

    def __init__(self, name, spec):
        self.name = name
        self.voice = spec["voice"]
        self.lo, self.hi = spec["lo"], spec["hi"]
        self.rng = random.Random(hash(name) & 0xFFFF)
        self.prev = (self.lo + self.hi) // 2
        self.bar = {}

    def put(self, step, midi, vel, dur):
        self.bar.setdefault(step, []).append((midi, vel, dur))

    def plan(self, chord, nxt):
        self.bar = {}

    def events(self, s):
        return [(self.name, self.voice, m, v, d) for m, v, d in self.bar.get(s, [])]


class Melody(Pattern):
    """Piano: 6-9 notes per phrase, random walk through the pentatonic."""
    count = (6, 9)

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        n = rng.randint(*self.count)
        steps = sorted(self._pick(n))
        chord_notes = in_range(chord.strong, self.lo, self.hi)
        pent = in_range(C.PENTATONIC, self.lo, self.hi)
        prev = self.prev
        for i, s in enumerate(steps):
            pool = chord_notes if (s in ACC or rng.random() < 0.5) else pent
            midi = rng.choice(nearest(pool, prev))
            nxt_s = steps[i + 1] if i + 1 < len(steps) else P
            dur = min(nxt_s - s, 12)
            vel = rng.uniform(0.75, 0.95) if s in ACC else rng.uniform(0.45, 0.7)
            self.put(s, midi, vel, dur)
            if s in ACC and rng.random() < 0.35:        # occasional 3rd/6th below
                low = [m for m in chord_notes if 3 <= midi - m <= 9]
                if low:
                    self.put(s, rng.choice(low), vel * 0.7, dur)
            prev = midi
        self.prev = prev

    def _pick(self, n):
        w = [x if s % 2 == 0 else x * 0.3 for s, x in enumerate(WEIGHT)]   # mostly 8ths
        chosen = set()
        while len(chosen) < n:
            s = self.rng.choices(range(P), w)[0]
            chosen.add(s)
            w[s] = 0
        return chosen


class Bells(Melody):
    """Glockenspiel: sparse, high, likes off-beats and quick pairs."""
    count = (2, 4)

    def _pick(self, n):
        w = [1 if s in ACC else 4 if s % 2 == 0 else 1.5 for s in range(P)]
        chosen = set()
        while len(chosen) < n:
            s = self.rng.choices(range(P), w)[0]
            chosen.add(s)
            w[s] = 0
            if self.rng.random() < 0.3 and s + 1 < P:
                chosen.add(s + 1)
        return chosen


class Guitar(Pattern):
    """Fingerpicked chord tones on the accent skeleton plus 8ths between."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        tones = in_range(chord.pcs, self.lo, self.hi)
        roots = [m for m in tones if m % 12 == chord.root]
        bass = min(roots) if roots else tones[0]
        upper = [m for m in tones if m > bass]
        steps = sorted(ACC | {3, 9, 15, 21, 27, 30})
        seq = upper[:] if rng.random() < 0.5 else upper[::-1]
        j = rng.randrange(len(seq))
        for s in steps:
            if s in (0, 12, 24):
                self.put(s, bass, 0.85, 12)
            else:
                m = seq[j % len(seq)]
                j += 1
                self.put(s, m, rng.uniform(0.5, 0.7), 6 if s in ACC else 3)


class Bass(Pattern):
    """Double bass: roots on the accents, a walk-up into the next chord."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        roots = in_range([chord.root], self.lo, self.hi)
        fifth = in_range([(chord.root + 7) % 12], self.lo, self.hi)
        root = roots[0] if rng.random() < 0.6 or len(roots) == 1 else roots[-1]
        for s in (0, 12, 24):
            self.put(s, root, 0.95, 6)
        for s in (6, 18):
            alt = fifth[0] if fifth and rng.random() < 0.5 else root
            self.put(s, alt, 0.7, 6)
        # step 28: lead into the next chord's root
        nroots = in_range([nxt.root], self.lo, self.hi)
        target = min(nroots, key=lambda m: abs(m - root)) if nroots else root
        lead = target - 1 if rng.random() < 0.4 else (root if rng.random() < 0.5 else target)
        self.put(28, max(self.lo, lead), 0.75, 4)


class Drums(Pattern):
    """Trap Heat kit: kick on the accents, clap on 2 & 4, hats on 8ths."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        for s in C.ACCENTS:
            if s == 28 and rng.random() < 0.5:
                continue
            self.put(s, "kick", 0.9 if s in (0, 12, 24) else 0.75, 1)
        for s in (4, 12, 20, 28):
            self.put(s, "clap" if rng.random() < 0.6 else "snare", 0.8, 1)
        for s in range(0, P, 2):
            self.put(s, "hat", 0.55 if s % 4 == 0 else 0.4, 1)
        if rng.random() < 0.5:                     # 16th roll into the next phrase
            for s in (29, 30, 31):
                self.put(s, "hat", 0.35, 1)
        if rng.random() < 0.6:
            self.put(rng.choice([14, 22, 30]), "hat_open", 0.45, 1)

    def events(self, s):
        return [(self.name, "drums", hit, v, d) for hit, v, d in self.bar.get(s, [])]


class Strings(Pattern):
    """Sustained 3-note voicing for the whole phrase, staggered a hair."""

    def plan(self, chord, nxt):
        self.bar = {}
        root, third, seventh = chord.pcs[0], chord.pcs[1], chord.pcs[3]
        lo_root = in_range([root], self.lo, self.lo + 11)[0]
        voicing = [lo_root]
        for pc in (seventh, third):
            cands = [m for m in in_range([pc], self.lo, self.hi) if m > voicing[-1]]
            if cands:
                voicing.append(cands[0])
        for i, m in enumerate(voicing):
            self.put(min(i, 1), m, 0.6 - 0.08 * i, P - i)


class Arp(Pattern):
    """Synth: 16th-note arpeggio over the 7th chord with a gate pattern."""

    def plan(self, chord, nxt):
        self.bar = {}
        rng = self.rng
        tones = in_range(chord.pcs, self.lo, self.hi)
        seq = tones + tones[-2:0:-1]
        j = rng.randrange(len(seq))
        gate = [rng.random() < 0.75 or s % 4 == 0 for s in range(P)]
        for s in range(P):
            if gate[s]:
                self.put(s, seq[j % len(seq)], 0.8 if s in ACC else 0.5, 1)
                j += 1


PATTERNS = {"piano": Melody, "guitar": Guitar, "bass": Bass, "drums": Drums,
            "strings": Strings, "bells": Bells, "arp": Arp}


class Backing(Pattern):
    """Always on: shaker 8ths, soft rim on 2 & 4, sub root on the accents."""

    def __init__(self):
        super().__init__("backing", dict(voice="mix", lo=36, hi=47))

    def plan(self, chord, nxt):
        self.bar = {}
        root = in_range([chord.root], 36, 47)[0]
        for s in range(0, P, 2):
            self.put(s, ("drums", "shaker"), 0.45 if s % 4 == 0 else 0.3, 1)
        for s in (4, 12, 20, 28):
            self.put(s, ("drums", "rim"), 0.3, 1)
        acc = C.ACCENTS
        for i, s in enumerate(acc):
            nxt_s = acc[i + 1] if i + 1 < len(acc) else P
            self.put(s, ("sub", root), 0.5, nxt_s - s)

    def events(self, s):
        return [("backing", kind, m, v, d) for (kind, m), v, d in self.bar.get(s, [])]


class Composer:
    def __init__(self):
        self.parts = {name: PATTERNS[spec["voice"]](name, spec)
                      for name, spec in C.INSTRUMENTS.items()}
        self.backing = Backing()
        self.chord_index = 0

    @property
    def chord_name(self):
        return CHORDS[self.chord_index].name

    def step(self, step):
        s = step % P
        if s == 0:
            self.chord_index = (step // P) % len(CHORDS)
            chord = CHORDS[self.chord_index]
            nxt = CHORDS[(self.chord_index + 1) % len(CHORDS)]
            self.backing.plan(chord, nxt)
            for p in self.parts.values():
                p.plan(chord, nxt)
        events = self.backing.events(s)
        for p in self.parts.values():
            events.extend(p.events(s))
        return events
