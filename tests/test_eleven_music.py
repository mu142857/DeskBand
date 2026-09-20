"""ElevenLabs Music requests, persistence, validation, and explicit UI consent."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
from dataclasses import replace
from unittest.mock import patch

import cv2
import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import config as C
from wavelens.clip import ClipPlayer
from wavelens.eleven_music import (MODEL, MusicHTTP, RenderedSong, composition_plan,
                                  continue_song, load_saved_song, validate_source)
from wavelens.export import render_loop
from wavelens.summary import CANCEL_UPLOAD, CONFIRM_UPLOAD


def helper(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(__file__), path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mp3_seconds(seconds=36):
    rate = 48_000
    frames = round(seconds * rate)
    wave = 0.08 * np.sin(2 * np.pi * 220 * np.arange(frames) / rate)
    data = np.column_stack((wave, wave)).astype(np.float32)
    output = io.BytesIO()
    sf.write(output, data, rate, format="MP3", subtype="MPEG_LAYER_III")
    return output.getvalue()


class FakeMusicHTTP:
    def __init__(self, audio, *, upload_error=None, compose_error=None):
        self.audio = audio
        self.upload_error = upload_error
        self.compose_error = compose_error
        self.uploads = []
        self.plans = []

    def upload(self, path, api_key):
        self.uploads.append((path, api_key))
        if self.upload_error:
            raise self.upload_error
        return "uploaded-123"

    def compose(self, plan, api_key):
        self.plans.append((plan, api_key))
        if self.compose_error:
            raise self.compose_error
        return self.audio


def source(folder):
    score = helper("test_export.py", "export_helpers").snapshot(folder, ("cup", "book"))
    return score, render_loop(score, folder=folder)


def test_source_and_plan():
    with tempfile.TemporaryDirectory() as folder:
        score, clip = source(folder)
        intro_ms = validate_source(score, clip)
        plan = composition_plan(score, "uploaded-123", intro_ms)
        assert plan["chunks"][0] == {"song_id": "uploaded-123",
                                      "range": {"start_ms": 0, "end_ms": intro_ms}}
        generated = plan["chunks"][1]
        assert generated["conditioning_ref"] == plan["chunks"][0]
        assert generated["context_adherence"] == "high"
        assert generated["condition_strength"] == "high"
        assert 30_000 <= intro_ms + generated["duration_ms"] <= 45_000
        assert "Concert Grand" in " ".join(generated["positive_styles"])
        try:
            validate_source(replace(score, fingerprint="changed"), clip)
        except ValueError as exc:
            assert "changed" in str(exc)
        else:
            raise AssertionError("stale clip was accepted")
        with open(clip.path, "ab") as output:
            output.write(b"tampered")
        try:
            validate_source(score, clip)
        except ValueError as exc:
            assert "file changed" in str(exc)
        else:
            raise AssertionError("modified WAV was accepted")
        os.remove(clip.path)
        try:
            validate_source(score, clip)
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing WAV was accepted")


def test_http_request_construction():
    with tempfile.TemporaryDirectory() as folder:
        _, clip = source(folder)
        requests = []

        def fake_request(req, timeout):
            requests.append((req, timeout))
            return b'{"song_id":"uploaded-123"}' if len(requests) == 1 else b"music bytes"

        with patch("wavelens.eleven_music._request", fake_request):
            client = MusicHTTP()
            assert client.upload(clip.path, "test-secret") == "uploaded-123"
            assert client.compose({"chunks": []}, "test-secret") == b"music bytes"
        upload, compose = (item[0] for item in requests)
        assert upload.full_url.endswith("/v1/music/upload")
        assert b'Content-Disposition: form-data; name="file"' in upload.data
        assert open(clip.path, "rb").read() in upload.data
        assert upload.get_header("Xi-api-key") == "test-secret"
        assert compose.full_url.endswith("output_format=mp3_48000_192")
        assert json.loads(compose.data)["model_id"] == MODEL


def test_http_rejects_invalid_key():
    error = urllib.error.HTTPError("https://api.elevenlabs.io/v1/music/upload", 401,
                                   "Unauthorized", {}, io.BytesIO(b'{"detail":"invalid key"}'))
    with patch("wavelens.eleven_music.urllib.request.urlopen", side_effect=error):
        try:
            MusicHTTP().compose({"chunks": []}, "test-secret")
        except RuntimeError as exc:
            assert "401" in str(exc) and "invalid key" in str(exc)
            assert "test-secret" not in str(exc)
        else:
            raise AssertionError("invalid key was accepted")


def test_success_and_explicit_retry():
    with tempfile.TemporaryDirectory() as folder:
        score, clip = source(folder)
        audio = mp3_seconds()
        first = FakeMusicHTTP(audio, compose_error=TimeoutError("uncertain result"))
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: "test-secret"}):
            try:
                continue_song(score, clip, client=first, folder=folder)
            except TimeoutError:
                pass
            else:
                raise AssertionError("compose timeout was accepted")
            job_path = next(os.path.join(folder, name) for name in os.listdir(folder)
                            if name.startswith("job-") and name.endswith(".json"))
            with open(job_path) as f:
                pending = json.load(f)
            assert pending["status"] == "uncertain" and pending["song_id"] == "uploaded-123"
            assert "test-secret" not in json.dumps(pending)
            second = FakeMusicHTTP(audio)
            result = continue_song(score, clip, client=second, folder=folder)
        assert isinstance(result, RenderedSong) and not second.uploads
        assert result.duration > 33 and result.intro_ms > 7900
        assert os.path.isfile(result.path) and result.path.endswith(".mp3")
        with open(job_path) as f:
            done = json.load(f)
        assert done["status"] == "done" and done["attempts"] == 2
        assert done["output_path"] == result.path and os.path.exists(clip.path)
        restored = load_saved_song(score, folder=folder)
        assert restored is not None and os.path.samefile(restored.path, result.path)
        assert load_saved_song(replace(score, fingerprint="another"), folder=folder) is None

        class FakeStream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
            def start(self):
                pass
            def stop(self):
                pass
            def close(self):
                pass

        with patch("wavelens.clip.sd.OutputStream", FakeStream):
            player = ClipPlayer()
            player(result, True)
            out = np.zeros((256, 2), np.float32)
            player.stream.callback(out, 256, None, None)
            assert np.abs(out).max() > 0
            player.stop()


def test_app_restores_saved_song_after_restart():
    with tempfile.TemporaryDirectory() as folder:
        app = helper("test_summary.py", "summary_helpers_restore").make_app(folder, ("cup",))
        score = app.current_summary()
        clip = render_loop(score, folder=folder)
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: "test-secret"}):
            song = continue_song(score, clip, client=FakeMusicHTTP(mp3_seconds()),
                                 folder=os.path.join(folder, "songs"))
        with patch.object(C, "CACHE_DIR", folder):
            app.enter_summary()
        assert app.song_jobs.status == "done"
        assert os.path.samefile(app.song_jobs.result.path, song.path)
        assert app.song_jobs.fingerprint == score.fingerprint


def test_rejection_invalid_output_and_missing_key():
    with tempfile.TemporaryDirectory() as folder:
        score, clip = source(folder)
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: ""}):
            try:
                continue_song(score, clip, client=FakeMusicHTTP(b""), folder=folder)
            except RuntimeError as exc:
                assert C.ELEVENLABS_KEY_ENV in str(exc)
            else:
                raise AssertionError("missing key was accepted")
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: "test-secret"}):
            rejected = FakeMusicHTTP(b"", upload_error=RuntimeError("copyright screening"))
            try:
                continue_song(score, clip, client=rejected, folder=folder)
            except RuntimeError as exc:
                assert "copyright" in str(exc)
            else:
                raise AssertionError("upload rejection was accepted")
            invalid = FakeMusicHTTP(mp3_seconds(5))  # a decodable but partial response
            try:
                continue_song(score, clip, client=invalid, folder=folder)
            except RuntimeError:
                pass
            else:
                raise AssertionError("partial song was accepted")
        assert os.path.exists(clip.path)
        assert not any(name.endswith(".mp3") for name in os.listdir(folder))


def test_ui_requires_second_click():
    with tempfile.TemporaryDirectory() as folder:
        app = helper("test_summary.py", "summary_helpers").make_app(folder, ("cup",))
        app.enter_summary()
        score = app.current_summary()
        clip = render_loop(score, folder=folder)
        app.summary_jobs.status = "done"
        app.summary_jobs.result = clip
        app.summary_jobs.fingerprint = score.fingerprint
        calls = []

        def worker(_score, _clip, _progress):
            calls.append("generated")
            return RenderedSong(score.fingerprint, "fake.mp3", 48_000, 48_000 * 36,
                                8000, clip.path, "uploaded-123")

        app.extend_worker = worker
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: ""}):
            app.summary_action("extend")
            assert not app.confirm_upload and C.ELEVENLABS_KEY_ENV in app.song_notice
        with patch.dict(os.environ, {C.ELEVENLABS_KEY_ENV: "test-secret"}):
            app.summary_action("extend")
            assert app.confirm_upload and not calls and app.song_jobs.status == "idle"
            assert app.summary_view.hit(30, 640, score, confirm_upload=True) == (None, None)
            app.on_mouse(cv2.EVENT_LBUTTONDOWN, *CANCEL_UPLOAD[:2], 0, None)
            assert not app.confirm_upload and not calls
            app.summary_action("extend")
            app.engine.set_bpm(100)
            app.on_mouse(cv2.EVENT_LBUTTONDOWN, *CONFIRM_UPLOAD[:2], 0, None)
            assert not calls and not app.confirm_upload
            app.engine.set_bpm(120)
            app.summary_action("extend")
            app.on_mouse(cv2.EVENT_LBUTTONDOWN, *CONFIRM_UPLOAD[:2], 0, None)
            for _ in range(100):
                app.render(0.033)
                if app.song_jobs.status == "done":
                    break
                time.sleep(0.002)
            assert calls == ["generated"] and app.song_jobs.status == "done"
            assert app.summary_view.hit(*CONFIRM_UPLOAD[:2], score, confirm_upload=True) == ("confirm_extend", None)


if __name__ == "__main__":
    test_source_and_plan()
    test_http_request_construction()
    test_http_rejects_invalid_key()
    test_success_and_explicit_retry()
    test_app_restores_saved_song_after_restart()
    test_rejection_invalid_output_and_missing_key()
    test_ui_requires_second_click()
    print("ok")
