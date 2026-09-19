"""Local WAV preview without taking over the live engine's audio stream."""

import os

import numpy as np
import sounddevice as sd
import soundfile as sf


class ClipPlayer:
    def __init__(self):
        self.stream = None
        self.playing = False
        self._audio = None
        self._position = 0

    def __call__(self, clip, on):
        self.stop()
        if not on:
            return
        if clip is None or not os.path.isfile(clip.path):
            raise FileNotFoundError("Rendered loop file is missing")
        audio, rate = sf.read(clip.path, dtype="float32", always_2d=True)
        if len(audio) != clip.frames or rate != clip.sample_rate or audio.shape[1] not in (1, 2):
            raise ValueError("Audio file no longer matches the saved result")
        if audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)
        self._audio = np.ascontiguousarray(audio)
        self._position = 0

        def callback(out, frames, _time, _status):
            count = min(frames, len(self._audio) - self._position)
            out[:count] = self._audio[self._position:self._position + count]
            out[count:] = 0
            self._position += count
            if count < frames:
                raise sd.CallbackStop

        stream = None

        def finished():
            if self.stream is stream:
                self.playing = False

        try:
            stream = sd.OutputStream(samplerate=rate, channels=2, dtype="float32",
                                     callback=callback, finished_callback=finished)
            self.stream = stream
            stream.start()
            self.playing = True
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.playing = False
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self._audio = None
