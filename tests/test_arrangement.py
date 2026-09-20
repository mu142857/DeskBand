"""Each capture rerolls its motif; saved scores survive app restarts."""

import json
import os
import subprocess
import sys
import tempfile
import threading

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import config as C
from wavelens.arrangement import build_snapshot
from wavelens.music import Composer, NoteEvent, score_cycle
from wavelens.motifs import MOTIF_VERSION, default_seed
from wavelens.shelf import Shelf
from wavelens.synth import Engine
from wavelens.score_view import score_strip


def photo():
    frame = np.zeros((240, 320, 3), np.uint8)
    frame[40:180, 60:200] = (100, 150, 220)
    return frame


def test_shelf_migration_and_restart():
    with tempfile.TemporaryDirectory() as folder:
        cv2.imwrite(os.path.join(folder, "cup.jpg"), np.full((144, 144, 3), 90, np.uint8))
        cv2.imwrite(os.path.join(folder, "book.jpg"), np.full((144, 144, 3), 140, np.uint8))
        with open(os.path.join(folder, "shelf.json"), "w") as f:
            json.dump({"cup": {"shown": "mug", "conf": 0.8, "saved_at": 100},
                       "book": {"shown": "book", "conf": 0.6, "saved_at": 200}}, f)
        shelf = Shelf(folder, C.INSTRUMENTS)
        assert shelf.order() == ["cup", "book"]
        assert shelf.entries["cup"].thumb.shape == (144, 144, 3)
        assert isinstance(shelf.entries["cup"].motif_seed, int)
        assert shelf.entries["cup"].motif_version == MOTIF_VERSION
        assert shelf.entries["cup"].instrument == "cup"
        assert shelf.selected() == set()  # old schema restarted with everything off
        with open(os.path.join(folder, "shelf.json")) as f:
            assert "motif_seed" in json.load(f)["cup"]

        shelf.select("cup", True)
        restored = Shelf(folder, C.INSTRUMENTS)
        assert restored.selected() == {"cup"}
        seed = restored.entries["cup"].motif_seed
        restored.add("cup", "cup", 0.9, photo(), [60, 40, 200, 180])
        assert restored.entries["cup"].motif_seed != seed
        assert restored.entries["cup"].saved_at == 100
        assert restored.entries["cup"].selected
        assert Shelf(folder, C.INSTRUMENTS).entries["cup"].motif_seed == restored.entries["cup"].motif_seed
        restored.clear_selection()
        assert Shelf(folder, C.INSTRUMENTS).selected() == set()


def test_app_restores_selection():
    import main

    with tempfile.TemporaryDirectory() as folder:
        old_folder = C.SHELF_DIR
        try:
            C.SHELF_DIR = folder
            shelf = Shelf(folder, C.INSTRUMENTS)
            shelf.add("cup", "cup", 0.8, photo(), [60, 40, 200, 180])
            shelf.select("cup", True)
            app = main.App()
            assert app.band == {"cup"}
            assert app.engine.parts["cup"].target == 0.0     # still loading: the band is silent
            app.start_band()                                 # loaded (or a photo): in at bar one
            assert app.engine.parts["cup"].target == 1.0
            assert app.arrangement_snapshot().selected == ("cup",)
            app.handle_command({"cmd": "fpga_bar", "bar": 3, "energy": 2,
                                "locks": 1, "fill": True, "enabled": True})
            assert app.state_dict()["fpga"]["energy"] == 2
            app.handle_command({"cmd": "fpga_mode", "on": False})
            assert app.state_dict()["fpga"] is None
            app.silence()  # existing 0-key/remote action clears persisted selection
            assert Shelf(folder, C.INSTRUMENTS).selected() == set()
        finally:
            C.SHELF_DIR = old_folder


def test_motif_score_repeats_and_matches_live_composer():
    names = ("cup", "pen", "book", "cell phone")
    composer = Composer()
    chords = composer.active_chords
    steps = C.STEPS_PER_PHRASE * len(chords)
    first, second = [], []
    for step in range(steps * 2):
        events = [event for event in composer.step(step) if event[0] in names]
        (first if step < steps else second).append(events)
    assert first == second

    flattened = tuple(NoteEvent(part, voice, note, step, duration, velocity, delay)
                      for step, events in enumerate(first)
                      for part, voice, note, velocity, duration, delay in events)
    assert score_cycle(chords, names) == flattened
    assert score_cycle(chords, names) == score_cycle(chords, names)
    changed_seeds = {"cup": default_seed("cup") + 1}
    assert score_cycle(chords, names, changed_seeds) != flattened

    short = (("C", 0, (48, 52, 55)), ("G", 7, (55, 59, 62)))
    short_composer = Composer(chords=short)
    short_steps = C.STEPS_PER_PHRASE * len(short)
    short_cycles = [tuple(tuple(e for e in short_composer.step(step) if e[0] in names)
                          for step in range(start, start + short_steps))
                    for start in (0, short_steps)]
    assert short_cycles[0] == short_cycles[1]

    # Python's hash randomization must not change the motif in a new process.
    source = "from wavelens.music import Composer, score_cycle; c=Composer(); print(repr(score_cycle(c.active_chords, ['cup'])[:12]))"
    outputs = []
    for value in ("1", "999"):
        env = dict(os.environ, PYTHONHASHSEED=value)
        outputs.append(subprocess.check_output([sys.executable, "-c", source], env=env).strip())
    assert outputs[0] == outputs[1]


def test_snapshot_timelines_style_and_fingerprint():
    with tempfile.TemporaryDirectory() as folder:
        shelf = Shelf(folder, C.INSTRUMENTS)
        shelf.add("cup", "mug", 0.8, photo(), [60, 40, 200, 180])
        shelf.add("book", "book", 0.9, photo(), [60, 40, 200, 180])
        shelf.select("cup", True)
        composer = Composer(motif_seeds={n: e.motif_seed for n, e in shelf.entries.items()})
        engine = Engine(composer)
        original = build_snapshot(shelf, composer, engine)
        assert original.bars == 4 and original.selected == ("cup",)
        assert [i.name for i in original.items] == ["cup", "book"]
        cup, book = original.items
        assert cup.kind == "notes" and cup.events and not cup.rhythm_steps
        assert book.kind == "rhythm" and book.events and book.rhythm_steps
        assert all(isinstance(ev.note, str) for ev in book.events)
        assert all(isinstance(ev.note, int) for ev in cup.events)
        note_image = score_strip(cup, original.bars)
        beat_image = score_strip(book, original.bars)
        assert note_image.shape == beat_image.shape == (56, 256, 3)
        assert not np.array_equal(note_image, beat_image)
        assert beat_image.max() > 180 and len(book.rhythm_steps) > 0
        assert all(ev.part == "cup" for ev in original.events)
        assert original.events == score_cycle(original.chords, original.selected,
                                              {"cup": cup.motif_seed})
        offline = original.make_composer()
        offline_events = tuple(NoteEvent(part, voice, note, step, duration, velocity, delay)
                               for step in range(original.bars * C.STEPS_PER_PHRASE)
                               for part, voice, note, velocity, duration, delay in offline.step(step)
                               if part in original.selected)
        assert offline_events == original.events
        assert not original.style_pending

        # Stage placement and math mode affect the score that will be exported.
        shelf.place("cup", (0.95, 0.75))
        staged = build_snapshot(shelf, composer, engine)
        assert staged.items[0].stage_pos == (0.95, 0.75)
        assert staged.fingerprint != original.fingerprint
        assert staged.events != original.events
        staged_composer = staged.make_composer()
        staged_events = tuple(NoteEvent(part, voice, note, step, duration, velocity, delay)
                              for step in range(staged.bars * C.STEPS_PER_PHRASE)
                              for part, voice, note, velocity, duration, delay in staged_composer.step(step)
                              if part in staged.selected)
        assert staged_events == staged.events
        composer.set_math(True)
        mathematical = build_snapshot(shelf, composer, engine)
        assert mathematical.math_mode and mathematical.fingerprint != staged.fingerprint
        assert mathematical.make_composer().math
        composer.set_math(False)
        shelf.place("cup", (0.5, 0.5))

        # A new photo rerolls this category's melody, including a re-shot.
        original_seed = shelf.entries["cup"].motif_seed
        shelf.add("cup", "cup", 0.95, photo(), [60, 40, 200, 180])
        assert shelf.entries["cup"].motif_seed != original_seed
        composer.set_motif_seed("cup", shelf.entries["cup"].motif_seed)
        assert build_snapshot(shelf, composer, engine).fingerprint != original.fingerprint
        shelf.select("book", True)
        with_book = build_snapshot(shelf, composer, engine)
        assert with_book.fingerprint != original.fingerprint
        assert {ev.part for ev in with_book.events} == {"cup", "book"}
        engine.set_bpm(104)
        assert build_snapshot(shelf, composer, engine).fingerprint != with_book.fingerprint
        shelf.select("book", False)
        engine.set_bpm(C.BPM)

        shelf.entries["cup"].motif_seed += 1
        changed_motif = build_snapshot(shelf, composer, engine)
        assert changed_motif.fingerprint != original.fingerprint
        shelf.entries["cup"].motif_seed -= 1

        # The request is pending until a bar boundary. An immutable published
        # tuple is read, never the chord list the callback is about to mutate.
        new_style = [("C", 0, [48, 52, 55]), ("G", 7, [55, 59, 62])]
        composer.request_style(new_style)
        pending = build_snapshot(shelf, composer, engine)
        assert pending.style_pending and pending.chords == original.chords
        composer.step(0)
        updated = build_snapshot(shelf, composer, engine)
        assert not updated.style_pending and updated.bars == 2
        assert updated.chords[0] == ("C", 0, (48, 52, 55))
        assert updated.fingerprint != original.fingerprint
        assert original.chords[0][0] == "Fmaj7"  # frozen snapshot did not mutate
        assert max(ev.step for ev in updated.items[0].events) < 2 * C.STEPS_PER_PHRASE


def test_snapshot_during_style_publication():
    with tempfile.TemporaryDirectory() as folder:
        shelf = Shelf(folder, C.INSTRUMENTS)
        shelf.add("cup", "cup", 0.8, photo(), [60, 40, 200, 180])
        shelf.select("cup", True)
        composer = Composer()
        engine = Engine(composer)
        original_specs = composer._chord_specs
        entered, release = threading.Event(), threading.Event()

        def delayed_publish():
            entered.set()
            assert release.wait(2)
            return original_specs()

        composer._chord_specs = delayed_publish
        composer.request_style([("C", 0, [48, 52, 55])])
        worker = threading.Thread(target=lambda: composer.step(0))
        worker.start()
        try:
            assert entered.wait(2)
            during = build_snapshot(shelf, composer, engine)
            assert during.style_pending and during.chords[0][0] == "Fmaj7"
        finally:
            release.set()
            worker.join(2)
        assert not worker.is_alive()
        after = build_snapshot(shelf, composer, engine)
        assert not after.style_pending and after.chords == (("C", 0, (48, 52, 55)),)


if __name__ == "__main__":
    test_shelf_migration_and_restart()
    test_app_restores_selection()
    test_motif_score_repeats_and_matches_live_composer()
    test_snapshot_timelines_style_and_fingerprint()
    test_snapshot_during_style_publication()
    print("ok")
