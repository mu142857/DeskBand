"""Cloud features offline: the network calls are replaced by canned replies.
ElevenLabs takes are pitch-checked, retuned and filed as a keymap; Gemini's
answer reaches the UI only for the photo it belongs to."""

import io
import json
import os
import sys
import tempfile
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens import cloud, sampler, vocals
from wavelens import config as C

SR = C.SAMPLE_RATE


def sung(midi, seconds=3.0, wobble=0.0, sr=44100):
    """A fake sung note as MP3 bytes: harmonics, soft vibrato, silence around it."""
    t = np.arange(int(seconds * sr)) / sr
    f0 = 440 * 2 ** ((midi - 69) / 12) * 2 ** (wobble * np.sin(2 * np.pi * 0.7 * t) / 12
                                                + 0.1 * np.sin(2 * np.pi * 5 * t) / 12)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    x = sum(np.sin(k * phase) / k for k in range(1, 6)) * 0.3
    x = np.concatenate([np.zeros(sr // 4), x, np.zeros(sr // 4)]).astype(np.float32)
    out = io.BytesIO()
    sf.write(out, x, sr, format="MP3")
    return out.getvalue()


def test_vocals():
    C.VOCAL_DIR = tempfile.mkdtemp(prefix="wavelens_vocal_")
    os.environ[C.ELEVENLABS_KEY_ENV] = "test"
    takes = iter([sung(63.3), sung(66, wobble=3.0), sung(70.8)])      # steady, wandering, steady
    cloud.sound = lambda prompt, seconds, api_key: next(takes)
    km = vocals.load(log=lambda s: None)
    assert km is not None and list(km.keys) == [63, 71], km.keys
    for m in km.keys:                       # retuned onto the semitone it is filed under
        heard = np.median(vocals.pitch_track(km.notes[m].mean(axis=1)))
        assert abs(heard - m) < 0.15, (m, heard)
    zones = json.load(open(os.path.join(C.VOCAL_DIR, "keymap.json")))
    assert [z["midi"] for z in zones] == [63, 71]
    # a second start reads the folder and never calls the API
    cloud.sound = lambda *a: (_ for _ in ()).throw(AssertionError("called the API again"))
    assert list(vocals.load(log=lambda s: None).keys) == [63, 71]

    # no key: nothing is made, nothing breaks
    C.VOCAL_DIR = tempfile.mkdtemp(prefix="wavelens_vocal_")
    del os.environ[C.ELEVENLABS_KEY_ENV]
    assert vocals.load(log=lambda s: None) is None


def test_describer():
    frame = np.full((720, 1280, 3), 128, np.uint8)
    sent = {}

    def fake_post(url, headers, body):
        sent.update(url=url, headers=headers, body=body)
        time.sleep(0.1)
        return json.dumps({"candidates": [{"content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": "A **white** ceramic mug."}]}}]}).encode()

    cloud.post = fake_post
    d = cloud.Describer()
    os.environ.pop(C.GEMINI_KEY_ENV, None)
    d.request(frame)
    assert d.status == "off"
    os.environ[C.GEMINI_KEY_ENV] = "test"
    d.request(frame)
    assert d.status == "looking"
    for _ in range(50):
        if d.status != "looking":
            break
        time.sleep(0.02)
    assert d.status == "done" and d.text == "A white ceramic mug.", (d.status, d.text)
    assert C.GEMINI_MODEL in sent["url"] and sent["headers"]["x-goog-api-key"] == "test"
    parts = sent["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg" and parts[1]["text"] == C.GEMINI_PROMPT

    d.request(frame)                        # retake before the answer: it is dropped
    d.clear()
    time.sleep(0.3)
    assert d.status is None and d.text is None

    def failing(url, headers, body):
        raise RuntimeError("HTTP 429: quota")
    cloud.post = failing
    d.request(frame)
    time.sleep(0.1)
    assert d.status == "error" and "429" in d.text
    del os.environ[C.GEMINI_KEY_ENV]


if __name__ == "__main__":
    test_vocals()
    test_describer()
    print("ok")
