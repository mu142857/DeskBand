"""Cloud APIs: Gemini describes the photo, ElevenLabs makes the vocal samples.

Plain HTTPS through urllib (no SDKs to install). Keys are read from the
environment (config.GEMINI_KEY_ENV, config.ELEVENLABS_KEY_ENV); without one the
feature is off and nothing else changes. Every call here blocks, so callers run
them off the main and audio threads."""

import base64
import json
import os
import ssl
import threading
import urllib.error
import urllib.request

import cv2

from . import config as C

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SOUND_URL = "https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128"

try:                                   # python.org builds ship without a CA bundle
    import certifi
    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = None


def key(env):
    return os.environ.get(env, "").strip() or None


def post(url, headers, body):
    """POST a JSON body -> response bytes. Raises RuntimeError with the API's
    own message on an HTTP error."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=C.API_TIMEOUT_S, context=TLS) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:2000].decode(errors="replace")
        try:                   # Google: {"error": {"message"}}, ElevenLabs: {"detail": {"message"}} or {"detail": "..."}
            err = json.loads(detail)
            err = err.get("error") or err.get("detail") or err
            detail = str(err.get("message", err) if isinstance(err, dict) else err)
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f"HTTP {e.code}: {detail[:200]}") from None


# ---------------------------------------------------------------- Gemini ----

def describe(frame, api_key):
    """One or two sentences about the object in a BGR frame."""
    h, w = frame.shape[:2]
    if w > 1024:                                   # plenty for a caption, and a smaller upload
        frame = cv2.resize(frame, (1024, int(h * 1024 / w)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("could not encode the photo")
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpg.tobytes()).decode()}},
        {"text": C.GEMINI_PROMPT},
    ]}]}
    reply = json.loads(post(GEMINI_URL.format(model=C.GEMINI_MODEL), {"x-goog-api-key": api_key}, body))
    parts = (reply.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = " ".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
    text = " ".join(text.replace("*", "").split())
    if not text:
        raise RuntimeError("empty reply")
    return text


class Describer:
    """Asks Gemini about each photo in the background. The UI reads `text` /
    `status`; a retake (clear) or a newer photo makes an older answer stale,
    and a stale answer is dropped when it arrives."""

    def __init__(self):
        self.job = 0
        self.text = None
        self.status = None                 # None, "off", "looking", "done", "error"
        self._lock = threading.Lock()

    def request(self, frame):
        api_key = key(C.GEMINI_KEY_ENV)
        with self._lock:
            self.job += 1
            job = self.job
            self.text = None
            self.status = "looking" if api_key else "off"
        if api_key:
            threading.Thread(target=self._run, args=(job, frame.copy(), api_key), daemon=True).start()

    def latest(self):
        """(job, status, text) read together, so a caller never mixes two photos."""
        with self._lock:
            return self.job, self.status, self.text

    def clear(self):
        with self._lock:
            self.job += 1
            self.text = self.status = None

    def _run(self, job, frame, api_key):
        try:
            text, status = describe(frame, api_key), "done"
        except Exception as e:                         # network, quota, bad key: say so, carry on
            text, status = str(e) or e.__class__.__name__, "error"
            print("[gemini]", text, flush=True)
        with self._lock:
            if job == self.job:
                self.text, self.status = text, status


# ------------------------------------------------------------ ElevenLabs ----

def sound(prompt, seconds, api_key):
    """A generated sound (text-to-sound-effects) -> MP3 bytes."""
    body = {"text": prompt, "duration_seconds": seconds, "prompt_influence": 0.7}
    return post(SOUND_URL, {"xi-api-key": api_key}, body)
