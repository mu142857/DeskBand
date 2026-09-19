"""Milestone 3: the saved score and offline WAV must describe one cycle."""

import json
import os
import sys
import tempfile
import time
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C
from deskband.arrangement import build_snapshot
from deskband.clip import ClipPlayer
from deskband.export import render_loop
from deskband.music import Composer
from deskband.shelf import Entry, Shelf
from deskband.synth import Engine
from main import App


def snapshot(folder, names, *, bpm=120, math=False, chords=None):
    shelf = Shelf(folder, C.INSTRUMENTS)
    for name in names:
        shelf.entries[name] = Entry(name, name, 1.0, np.full((144, 144, 3), 80, np.uint8),
                                    selected=True, pos=(0.5, 0.5))
    composer = Composer(chords=chords, motif_seeds={n: e.motif_seed for n, e in shelf.entries.items()})
    composer.set_math(math)
    engine = Engine(composer)
    engine.set_bpm(bpm)
    engine.set_fpga_mode(True)  # export still uses its own Mac clock
    return build_snapshot(shelf, composer, engine)


def test_one_cycle_and_repeat():
    with tempfile.TemporaryDirectory() as folder:
        chords = tuple(C.CHORDS[:2])
        score = snapshot(folder, ("cup",), bpm=90, chords=chords)
        first = render_loop(score, folder=folder)
        second = render_loop(score, folder=folder)
        assert first.path != second.path and os.path.exists(first.path)
        assert first.frames == round(60 / 90 / C.STEPS_PER_BEAT * C.SAMPLE_RATE) * 32
        assert first.sample_rate == C.SAMPLE_RATE and first.duration > 5
        info = sf.info(first.path)
        assert (info.channels, info.frames, info.subtype) == (2, first.frames, "PCM_16")
        a, _ = sf.read(first.path, dtype="float32")
        b, _ = sf.read(second.path, dtype="float32")
        assert np.array_equal(a, b) and 0.001 < np.abs(a).max() <= 1
        assert np.abs(a[-1]).max() == 0


def test_math_mode_fresh_cycle():
    with tempfile.TemporaryDirectory() as folder:
        score = snapshot(folder, ("cup", "laptop"), math=True)
        clip = render_loop(score, folder=folder)
        assert score.math_mode and score.events
        assert 7.9 < clip.duration < 8.1
        audio, _ = sf.read(clip.path, dtype="float32")
        assert np.isfinite(audio).all() and 0.001 < np.abs(audio).max() <= 1


def test_all_eight_with_existing_vocal_take():
    with tempfile.TemporaryDirectory() as folder:
        old_vocal_dir = C.VOCAL_DIR
        C.VOCAL_DIR = os.path.join(folder, "vocal")
        try:
            os.makedirs(C.VOCAL_DIR)
            tone = 0.1 * np.sin(2 * np.pi * 440 * np.arange(C.SAMPLE_RATE) / C.SAMPLE_RATE)
            sf.write(os.path.join(C.VOCAL_DIR, "69.wav"), tone, C.SAMPLE_RATE)
            with open(os.path.join(C.VOCAL_DIR, "keymap.json"), "w") as f:
                json.dump([{"midi": 69, "file": "69.wav"}], f)
            score = snapshot(folder, tuple(C.INSTRUMENTS))
            clip = render_loop(score, folder=folder)
            assert clip.frames > 0 and sf.info(clip.path).frames == clip.frames
            assert 7.9 < clip.duration < 8.1
            audio, _ = sf.read(clip.path, dtype="float32")
            assert np.isfinite(audio).all() and 0.001 < np.abs(audio).max() <= 1
            assert {event.part for event in score.events} == set(C.INSTRUMENTS)
        finally:
            C.VOCAL_DIR = old_vocal_dir


def test_empty_and_pending_are_rejected():
    from dataclasses import replace
    with tempfile.TemporaryDirectory() as folder:
        empty = snapshot(folder, ())
        try:
            render_loop(empty, folder=folder)
        except ValueError as exc:
            assert "Choose" in str(exc)
        else:
            raise AssertionError("empty arrangement was rendered")
        pending = replace(snapshot(folder, ("cup",)), style_pending=True)
        try:
            render_loop(pending, folder=folder)
        except ValueError as exc:
            assert "pending" in str(exc)
        else:
            raise AssertionError("pending harmony was rendered")


def test_missing_voice_samples_report_an_error():
    with tempfile.TemporaryDirectory() as folder:
        old_vocal_dir = C.VOCAL_DIR
        C.VOCAL_DIR = os.path.join(folder, "missing-voice")
        try:
            try:
                render_loop(snapshot(folder, ("headphones",)), folder=folder)
            except RuntimeError as exc:
                assert "Voice samples" in str(exc)
            else:
                raise AssertionError("missing voice samples were accepted")
            assert not any(name.endswith(".wav") for name in os.listdir(folder))
        finally:
            C.VOCAL_DIR = old_vocal_dir


def test_summary_render_and_stale_clip():
    with tempfile.TemporaryDirectory() as folder:
        old_shelf_dir = C.SHELF_DIR
        C.SHELF_DIR = folder
        try:
            shelf = Shelf(folder, C.INSTRUMENTS)
            frame = np.full((120, 160, 3), 70, np.uint8)
            shelf.add("cup", "cup", 0.9, frame, [30, 20, 125, 105])
            shelf.select("cup", True)
            app = App()
            assert app.engine.parts["cup"].target == 1
            app.render_worker = lambda score, progress: render_loop(score, progress, folder=folder)
            app.enter_summary()
            assert app.engine.parts["cup"].target == 0
            app.summary_action("render")
            for _ in range(100):
                app.render(0.033)
                if app.summary_jobs.status != "running":
                    break
                time.sleep(0.01)
            assert app.summary_jobs.status == "done", app.summary_jobs.message
            clip = app.summary_jobs.result
            assert app.current_clip_ready() and os.path.exists(clip.path)
            stops = []
            app.clip_player = lambda _clip, on: stops.append(on)
            app.clip_playing = True
            app.engine.set_bpm(100)
            app.render(0.033)
            assert stops == [False] and not app.clip_playing and not app.current_clip_ready()
            app.engine.set_bpm(120)
            app.summary_action("toggle", "cup")
            assert not app.current_clip_ready() and os.path.exists(clip.path)
            app.leave_summary()
            assert app.playing and app.engine.parts["cup"].target == 0
            app.select("cup")
            assert app.engine.parts["cup"].target == 1
            app.play(False)
            app.enter_summary()
            app.leave_summary()
            assert not app.playing and app.engine.parts["cup"].target == 0
        finally:
            C.SHELF_DIR = old_shelf_dir


def test_local_preview_uses_separate_output_stream():
    class FakeStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.closed = False

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            self.closed = True

    with tempfile.TemporaryDirectory() as folder:
        clip = render_loop(snapshot(folder, ("cup",)), folder=folder)
        player = ClipPlayer()
        with patch("deskband.clip.sd.OutputStream", FakeStream):
            player(clip, True)
            assert player.playing
            out = np.empty((256, 2), np.float32)
            player.stream.callback(out, 256, None, None)
            assert np.abs(out).max() > 0
            stream = player.stream
            player(clip, False)
            assert not player.playing and stream.closed


if __name__ == "__main__":
    test_one_cycle_and_repeat()
    test_math_mode_fresh_cycle()
    test_all_eight_with_existing_vocal_take()
    test_empty_and_pending_are_rejected()
    test_missing_voice_samples_report_an_error()
    test_summary_render_and_stale_clip()
    test_local_preview_uses_separate_output_stream()
    print("ok")
