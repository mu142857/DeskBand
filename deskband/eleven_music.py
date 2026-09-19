"""ElevenLabs Music continuation of a rendered DeskBand loop.

The worker is called only after a separate UI confirmation. Network access is
injectable for tests, and neither credentials nor source audio enter job JSON.
"""

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import soundfile as sf

from . import config as C
from .cloud import TLS, key

UPLOAD_URL = "https://api.elevenlabs.io/v1/music/upload"
COMPOSE_URL = "https://api.elevenlabs.io/v1/music?output_format=mp3_48000_192"
MODEL = "music_v2_5"
MAX_REFERENCE_MS = 30_000
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class RenderedSong:
    fingerprint: str
    path: str
    sample_rate: int
    frames: int
    intro_ms: int
    source_path: str
    song_id: str
    model_id: str = MODEL

    @property
    def duration(self):
        return self.frames / self.sample_rate


def validate_source(snapshot, clip):
    """Check the exact, current PCM WAV before any paid/network operation."""
    if clip is None or clip.fingerprint != snapshot.fingerprint:
        raise ValueError("The loop changed; render it again before uploading")
    if not os.path.isfile(clip.path):
        raise FileNotFoundError("The rendered loop file is missing")
    info = sf.info(clip.path)
    if (info.format != "WAV" or info.subtype != "PCM_16" or info.channels != 2 or
            info.frames != clip.frames or info.samplerate != clip.sample_rate or
            info.frames < info.samplerate * 3):
        raise ValueError("Render a valid stereo PCM loop of at least three seconds")
    if clip.sha256:
        digest = hashlib.sha256()
        with open(clip.path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != clip.sha256:
            raise ValueError("The loop file changed; render it again before uploading")
    milliseconds = info.frames * 1000 // info.samplerate
    if milliseconds > MAX_REFERENCE_MS:
        raise ValueError("This loop exceeds the 30-second ElevenLabs reference limit")
    return milliseconds


def composition_plan(snapshot, song_id, intro_ms):
    """Preserve the full loop, then extend it into a short instrumental song."""
    if not song_id or not 3000 <= intro_ms <= MAX_REFERENCE_MS:
        raise ValueError("Invalid uploaded song or reference duration")
    instruments = [item.instrument_label for item in snapshot.items if item.selected]
    harmony = " → ".join(chord[0] for chord in snapshot.chords)
    styles = ["instrumental", "warm electronic", "clear layered arrangement",
              "gentle rhythmic pulse", "musical object soundscape", "consistent tempo"]
    styles.extend(instruments[:8])
    continuation_ms = max(20_000, min(35_000, 36_000 - intro_ms))
    reference = {"song_id": song_id, "range": {"start_ms": 0, "end_ms": intro_ms}}
    return {"chunks": [
        reference,
        {"text": ("[Instrumental continuation]\n"
                  f"{{Continue the intro's {snapshot.bpm:g} BPM pulse and {harmony} harmony; "
                  "develop its melodies with no lyrics or speech.}"),
         "duration_ms": continuation_ms,
         "positive_styles": styles,
         "negative_styles": ["singing", "spoken word", "abrupt transition"],
         "context_adherence": "high",
         "conditioning_ref": reference,
         "condition_strength": "high"},
    ]}


def _request(request, timeout):
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=TLS) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise RuntimeError("ElevenLabs response is too large")
            return data
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode(errors="replace")
        try:
            error = json.loads(detail)
            error = error.get("detail") or error.get("error") or error
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        except ValueError:
            pass
        raise RuntimeError(f"ElevenLabs HTTP {exc.code}: {detail[:220]}") from None


class MusicHTTP:
    """Small urllib adapter; tests supply an object with upload and compose."""

    def upload(self, wav_path, api_key):
        boundary = "deskband-" + uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{os.path.basename(wav_path)}\"\r\n"
                "Content-Type: audio/wav\r\n\r\n").encode()
        with open(wav_path, "rb") as source:
            body += source.read()
        body += f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            UPLOAD_URL, data=body, method="POST",
            headers={"xi-api-key": api_key,
                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        reply = json.loads(_request(request, 120))
        song_id = reply.get("song_id")
        if not isinstance(song_id, str) or not song_id:
            raise RuntimeError("ElevenLabs upload returned no song ID")
        return song_id

    def compose(self, plan, api_key):
        body = json.dumps({"model_id": MODEL, "composition_plan": plan}).encode()
        request = urllib.request.Request(
            COMPOSE_URL, data=body, method="POST",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"})
        return _request(request, 240)


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix=".music-job-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output, indent=2)
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.remove(pending)


def _job_path(folder, clip):
    identity = hashlib.sha256(os.path.abspath(clip.path).encode()).hexdigest()[:12]
    return os.path.join(folder, f"job-{clip.fingerprint[:10]}-{identity}.json")


def _validate_song(path, expected_seconds):
    info = sf.info(path)
    if (info.format != "MP3" or info.channels not in (1, 2) or info.frames <= 0 or
            not 8_000 <= info.samplerate <= 96_000):
        raise RuntimeError("ElevenLabs returned invalid audio")
    if abs(info.duration - expected_seconds) > 3.0:
        raise RuntimeError("ElevenLabs returned an unexpected song length")
    audio, _ = sf.read(path, dtype="float32", always_2d=True)
    if not np.isfinite(audio).all() or np.abs(audio).max() < 1e-5:
        raise RuntimeError("ElevenLabs returned silent or invalid audio")
    return info


def load_saved_song(snapshot, *, folder=None):
    """Find a completed song for this arrangement without contacting ElevenLabs."""
    folder = os.path.realpath(folder or os.path.join(C.CACHE_DIR, "songs"))
    if not os.path.isdir(folder):
        return None
    jobs = []
    for name in os.listdir(folder):
        if name.startswith("job-") and name.endswith(".json"):
            path = os.path.join(folder, name)
            try:
                jobs.append((os.path.getmtime(path), path))
            except OSError:
                continue
    for _, job_path in sorted(jobs, reverse=True):
        try:
            with open(job_path) as source:
                job = json.load(source)
            if job.get("status") != "done" or job.get("fingerprint") != snapshot.fingerprint:
                continue
            path = os.path.realpath(job["output_path"])
            if os.path.commonpath((folder, path)) != folder or not path.endswith(".mp3"):
                continue
            info = sf.info(path)
            if info.format != "MP3" or info.frames <= 0 or info.samplerate <= 0:
                continue
            intro_ms = int(job["intro_ms"])
            if info.duration <= intro_ms / 1000 or not job.get("song_id"):
                continue
            return RenderedSong(snapshot.fingerprint, path, info.samplerate, info.frames,
                                intro_ms, job["source_path"], job["song_id"])
        except (OSError, ValueError, KeyError, TypeError, sf.LibsndfileError):
            continue
    return None


def continue_song(snapshot, clip, progress=lambda message: None, *, client=None, folder=None):
    """One confirmed job. Explicit retries may reuse a saved upload ID."""
    intro_ms = validate_source(snapshot, clip)
    api_key = key(C.ELEVENLABS_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Set {C.ELEVENLABS_KEY_ENV} before generating a song")
    client = client or MusicHTTP()
    folder = os.path.abspath(folder or os.path.join(C.CACHE_DIR, "songs"))
    os.makedirs(folder, exist_ok=True)
    job_path = _job_path(folder, clip)
    try:
        with open(job_path) as source:
            previous = json.load(source)
    except (OSError, ValueError):
        previous = {}
    if (previous.get("source_path") != os.path.abspath(clip.path) or
            previous.get("fingerprint") != clip.fingerprint or
            previous.get("source_sha256") != clip.sha256):
        previous = {}
    job = {"fingerprint": clip.fingerprint, "source_path": os.path.abspath(clip.path),
           "source_sha256": clip.sha256, "model_id": MODEL, "intro_ms": intro_ms,
           "song_id": previous.get("song_id"), "status": "preparing",
           "attempts": int(previous.get("attempts", 0)) + 1}
    _save_json(job_path, job)
    try:
        if not job["song_id"]:
            progress("Uploading loop to ElevenLabs…")
            job["status"] = "uploading"
            _save_json(job_path, job)
            job["song_id"] = client.upload(clip.path, api_key)
            _save_json(job_path, job)
        plan = composition_plan(snapshot, job["song_id"], intro_ms)
        job["plan"] = plan
        job["status"] = "composing"
        _save_json(job_path, job)
        progress("Generating instrumental continuation…")
        # A timeout after this request may already have consumed credits.
        audio = client.compose(plan, api_key)
        if not isinstance(audio, bytes) or len(audio) < 1000:
            raise RuntimeError("ElevenLabs returned no usable audio")
        job["status"] = "saving"
        _save_json(job_path, job)
        progress("Checking and saving full song…")
        fd, pending = tempfile.mkstemp(prefix=".music-", suffix=".mp3", dir=folder)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(audio)
            expected = (intro_ms + plan["chunks"][1]["duration_ms"]) / 1000
            info = _validate_song(pending, expected)
            name = f"deskband-song-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{clip.fingerprint[:10]}.mp3"
            path = os.path.join(folder, name)
            os.replace(pending, path)
        finally:
            if os.path.exists(pending):
                os.remove(pending)
        job.update(status="done", output_path=path, duration_seconds=info.duration)
        _save_json(job_path, job)
        progress("Full song ready")
        return RenderedSong(clip.fingerprint, path, info.samplerate, info.frames,
                            intro_ms, os.path.abspath(clip.path), job["song_id"])
    except Exception as exc:
        # No automatic compose retry: the failed request might have been charged.
        job["status"] = "uncertain" if job["status"] in ("composing", "saving") else "error"
        job["error"] = str(exc)[:500]
        _save_json(job_path, job)
        raise
