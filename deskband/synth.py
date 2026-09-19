"""Real-time audio engine: voices, parts with reverb sends, and a
sample-accurate step sequencer running inside the sounddevice callback.
Nothing here blocks; the callback only slices preloaded arrays."""

import os
import threading
import time as _time
from collections import deque

import numpy as np
import sounddevice as sd
from scipy.signal import lfilter

from . import config as C
from . import sampler, vocals
from .fx import Reverb

SR = C.SAMPLE_RATE
TWO_PI = 2 * np.pi


def midi_to_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def blep_saw(t, f):
    """Band-limited sawtooth (polyBLEP): a naive saw aliases into audible grit."""
    dt = f / SR
    ph = (t * f) % 1.0
    saw = 2 * ph - 1
    lo = ph < dt
    x = ph[lo] / dt
    saw[lo] -= x + x - x * x - 1
    hi = ph > 1 - dt
    x = (ph[hi] - 1) / dt
    saw[hi] -= x * x + x + x + 1
    return saw


# ---------------------------------------------------------------- voices ----

class Voice:
    """One sounding note. render(n) -> (n, 2) float32."""
    done = False
    part = None
    offset = 0

    def release(self):
        pass


class SynthVoice(Voice):
    def __init__(self, kind, midi, vel, dur_samples):
        self.kind, self.midi, self.vel = kind, midi, vel
        self.f = midi_to_hz(midi)
        self.t = 0
        self.dur = dur_samples
        self.releasing = False
        self.rel_t = 0
        self.lp = np.zeros(1)
        self.pan = float(np.clip((midi - 66) / 40, -0.4, 0.4))

    def release(self):
        self.releasing = True

    def render(self, n):
        t = (self.t + np.arange(n)) / SR
        k = self.kind
        if k == "arp":       # saw pluck through a closing lowpass
            saw = blep_saw(t, self.f) + 0.5 * blep_saw(t, self.f * 1.005)
            env = np.exp(-t * 9.0)
            cut = 500 + 4500 * float(env[0]) * self.vel
            sig = self._lowpass(saw, cut) * env * 0.35
        elif k == "keys":    # mellow FM electric piano: sine carrier, decaying index
            att = np.minimum(t / 0.004, 1.0)
            env = np.exp(-t * 2.4)
            idx = 1.5 * np.exp(-t * 6.0) * self.vel
            ph = TWO_PI * self.f * t
            sig = np.sin(ph + idx * np.sin(ph)) * env * att * 0.4
            sig += np.sin(2 * ph) * np.exp(-t * 7.0) * 0.05
        elif k == "sub":     # soft sine bass to ground the harmony
            att = np.minimum(t / 0.01, 1.0)
            sig = (np.sin(TWO_PI * self.f * t) + 0.15 * np.sin(TWO_PI * 2 * self.f * t)) * att * 0.5
        else:
            sig = np.zeros(n)
        sig = sig * self.vel
        if self.releasing:
            r = np.arange(n) + self.rel_t
            rel = (0.35 if k == "keys" else 0.06) * SR
            sig = sig * np.clip(1 - r / rel, 0, 1)
            self.rel_t += n
            if self.rel_t > rel:
                self.done = True
        self.t += n
        if not self.releasing and self.t >= self.dur:
            self.release()
        if k in ("arp", "keys") and self.t > 3 * SR:
            self.done = True
        return self._stereo(sig)

    def _lowpass(self, x, cutoff):
        a = np.exp(-TWO_PI * cutoff / SR)
        y, self.lp = lfilter([1 - a], [1, -a], x, zi=self.lp)
        return y

    def _stereo(self, sig):
        l = sig * (0.5 - self.pan) * 2 ** 0.5
        r = sig * (0.5 + self.pan) * 2 ** 0.5
        return np.stack([l, r], axis=1).astype(np.float32)


class SampleVoice(Voice):
    """Plays a stereo buffer at a pitch ratio with linear interpolation."""

    def __init__(self, buf, ratio, vel, dur_samples, release_s=0.25, loop=False, pan=0.0):
        self.buf, self.ratio, self.vel = buf, ratio, vel
        self.pos = 0.0
        self.dur = dur_samples
        self.t = 0
        self.releasing = False
        self.rel_t = 0
        self.rel_len = release_s * SR
        self.loop = loop
        self.pan = pan

    def release(self):
        self.releasing = True

    def render(self, n):
        length = len(self.buf)
        idx = self.pos + np.arange(n) * self.ratio
        if self.loop:
            idx = idx % (length - 1)
        i0 = idx.astype(np.int64)
        last = length - 2
        if i0[0] >= last:
            self.done = True
            return np.zeros((n, 2), np.float32)
        i0 = np.minimum(i0, last)
        frac = (idx - i0)[:, None].astype(np.float32)
        out = self.buf[i0] * (1 - frac) + self.buf[i0 + 1] * frac
        out *= self.vel
        if self.pan:
            out[:, 0] *= (1 - self.pan)
            out[:, 1] *= (1 + self.pan)
        if self.releasing:
            r = np.arange(n) + self.rel_t
            out *= np.clip(1 - r / self.rel_len, 0, 1)[:, None]
            self.rel_t += n
            if self.rel_t > self.rel_len:
                self.done = True
        self.pos += n * self.ratio
        self.t += n
        if not self.releasing and self.dur and self.t >= self.dur:
            self.release()
        return out


RELEASE = {"piano": 1.6, "guitar": 0.6, "bass": 0.15, "strings": 0.7, "bells": 1.2, "vocal": 0.5}


# ---------------------------------------------------------------- engine ----

class Part:
    """A mixer channel: smoothed gain (fade in/out) and a reverb send."""

    def __init__(self, name, level=1.0, send=0.0):
        self.name = name
        self.level = level
        self.send = send
        self.target = 0.0
        self.gain = 0.0
        self.trim = self.trim_to = 1.0     # loudness set on the stage, glides ~50 ms

    @property
    def audible(self):
        return self.target > 0 or self.gain > 1e-3


class Engine:
    def __init__(self, composer):
        self.composer = composer
        self.voices = []
        self.parts = {}
        self.keymaps = {}
        self.drums = {}
        self.loaded = set()
        self.reverb = Reverb()
        self.bpm = float(C.BPM)
        self.step_len = int(round(60 / C.BPM / C.STEPS_PER_BEAT * SR))
        self.pos = 0
        self.step = 0
        self.next_step_at = 0
        self.stream = None
        self.cpu = 0.0
        self.xruns = 0               # callbacks that reported an under/overflow
        self.pre_peak = 0.0          # level going into the limiter
        self.latency = 0.0
        self.makeup = 1.0
        self.lim_gain = 1.0
        self.gain_reduction_db = 0.0
        self.pulse = 0.0
        self.hits = {}               # part -> last trigger time (for the UI)
        self.bar_marks = ()          # the last few (sample position, Composer.BarView) bar lines (for the UI)
        self.transport = False       # the clock waits: see start_transport
        for name, spec in C.INSTRUMENTS.items():
            self.parts[name] = Part(name, spec["level"], spec["send"])
        self.parts["backing"] = Part("backing", C.BACKING["level"], C.BACKING["send"])
        self.parts["backing"].target = 1.0
        self.parts["sfx"] = Part("sfx", 1.0, 0.30)       # one-shots from the remote port
        self.parts["sfx"].target = 1.0
        self.pending_sfx = []        # (buffer, gain), started on the next 8th note
        self.sfx_cache = {}
        self.fpga_mode = False
        self.fpga_lookahead_steps = 2
        self.fpga_input = deque()       # main/network thread appends; callback drains
        self.fpga_pending = deque()     # (sample position, tick, event mask, active mask)
        self.fpga_origin_tick = None
        self.fpga_origin_sample = None
        self.fpga_controls = (tuple([255] * 7), tuple([0] * 7))
        self.fpga_track_names = tuple(C.FPGA_TRACKS)
        self.fpga_track_index = {name: track for track, name in enumerate(self.fpga_track_names)}

    # -- loading (background thread; parts become audible as they land)
    def load_instruments(self, log=print):
        t0 = _time.time()
        km = sampler.load_concert_grand()
        if km is not None:
            self.keymaps["piano"] = km
            self.loaded.add("piano")
            log(f"[sampler] piano: {os.path.basename(km.source)}, {len(km.keys)} notes")
        km = sampler.load_kings_cross()
        if km is not None:
            self.keymaps["strings"] = km
            self.loaded.add("strings")
            log(f"[sampler] strings: King's Cross, {len(km.keys)} notes")
        for kind in C.SAMPLE_SETS:
            if kind in self.loaded:
                continue
            km = sampler.load_set(kind)
            self.keymaps[kind] = km
            self.loaded.add(kind)
            log(f"[sampler] {kind}: {len(km.keys)} notes")
        self.drums = sampler.load_drums()
        self.loaded.add("drums")
        log(f"[sampler] drums: {len(self.drums)} hits")
        try:
            if not C.BACKING["vinyl"]:
                raise LookupError("disabled in config")
            vinyl = sampler.load_loop(C.VINYL_LOOP, "vinyl")
            v = SampleVoice(vinyl, 1.0, C.VINYL_LEVEL, 0, loop=True)
            v.part = self.parts["backing"]
            self.voices.append(v)
            log(f"[sampler] vinyl loop: {len(vinyl) / SR:.1f}s")
        except Exception as e:
            log(f"[sampler] vinyl loop unavailable: {e}")
        log(f"[sampler] all loaded in {_time.time() - t0:.1f}s")
        try:                                # last: the first time, this waits on ElevenLabs
            km = vocals.load(log)
            if km is not None:
                self.keymaps["vocal"] = km
                self.loaded.add("vocal")
                log(f"[sampler] vocal: {len(km.keys)} notes")
        except Exception as e:
            log(f"[vocal] unavailable: {e!r}")

    def set_bpm(self, bpm):
        old_step_len = self.step_len
        self.bpm = float(min(max(bpm, 60), 180))
        self.step_len = int(round(60 / self.bpm / C.STEPS_PER_BEAT * SR))
        if self.fpga_mode and self.step_len != old_step_len:
            self.fpga_input.clear()
            self.fpga_pending.clear()
            self.fpga_origin_tick = None
            self.fpga_origin_sample = None

    def play_file(self, path, gain=0.6):
        """Queue a sound file to start on the next 8th note (so even a spoken
        line or a generated effect lands in time). Decoding happens here, in
        the caller's thread; the audio callback only picks up the buffer."""
        buf = self.sfx_cache.get(path)
        if buf is None:
            buf = sampler.fade_tail(sampler.read_audio(path, 20.0))
            if len(self.sfx_cache) > 32:
                self.sfx_cache.clear()
            self.sfx_cache[path] = buf
        self.pending_sfx.append((buf, float(min(max(gain, 0.0), 1.5))))

    def set_active(self, name, active):
        self.parts[name].target = 1.0 if active else 0.0

    def set_trim(self, name, gain):
        """Loudness from the stage, on top of the part's level."""
        self.parts[name].trim_to = float(gain)

    def set_fpga_mode(self, enabled, lookahead_steps=2):
        """Select the external hardware conductor. A small fixed playback
        delay absorbs UART/UDP jitter while preserving FPGA event spacing."""
        enabled = bool(enabled)
        lookahead_steps = min(max(int(lookahead_steps), 1), 8)
        if enabled == self.fpga_mode and lookahead_steps == self.fpga_lookahead_steps:
            return
        self.fpga_mode = enabled
        self.fpga_lookahead_steps = lookahead_steps
        self.fpga_input.clear()
        self.fpga_pending.clear()
        self.fpga_origin_tick = None
        self.fpga_origin_sample = None
        if not self.fpga_mode:
            self.next_step_at = self.pos

    def queue_fpga_event(self, tick, step, event_mask, active_mask):
        if self.fpga_mode:
            self.fpga_input.append((int(tick), int(step), int(event_mask) & 0x7f,
                                    int(active_mask) & 0x7f))

    def set_fpga_controls(self, levels, lfos):
        if len(levels) != 7 or len(lfos) != 7:
            raise ValueError("FPGA controls require seven envelope and seven LFO values")
        self.fpga_controls = (tuple(min(max(int(v), 0), 255) for v in levels),
                              tuple(min(max(int(v), 0), 255) for v in lfos))

    def warm_up(self):
        """First calls into numpy/scipy are slow; pay for them before audio runs."""
        self.reverb.process(np.zeros(C.BLOCK_SIZE, np.float32))
        SynthVoice("keys", 60, 0.1, SR).render(C.BLOCK_SIZE)
        SampleVoice(np.zeros((SR, 2), np.float32), 1.01, 0.1, SR).render(C.BLOCK_SIZE)

    def start(self):
        self.warm_up()
        threading.Thread(target=self.load_instruments, daemon=True).start()
        self.stream = sd.OutputStream(
            samplerate=SR, channels=2, dtype="float32",
            blocksize=C.BLOCK_SIZE, latency="high", callback=self._callback)
        self.stream.start()
        self.latency = float(self.stream.latency)     # the UI delays its glow by this

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()

    # -- composer events -> voices
    def _trigger(self, ev, block_offset):
        part, kind, midi, vel, dur_steps = ev[:5]
        if len(ev) > 5 and ev[5]:                       # rolled chords: start a little late
            block_offset += int(ev[5] * self.step_len)
        p = self.parts[part]
        if not p.audible:
            return
        dur = int(dur_steps * self.step_len)
        v = None
        if kind == "drums":
            buf = self.drums.get(midi)          # midi field carries the hit name
            if buf is not None:
                v = SampleVoice(buf, 1.0, vel, 0, release_s=0.05)
        elif kind in self.keymaps and self.keymaps[kind].ready:     # silent, not broken, if a library is missing
            km = self.keymaps[kind]
            buf, ratio = km.lookup(midi)
            # spread the upper register a little; keep bass centred
            pan = 0.0 if kind == "bass" else float(np.clip((midi - 66) / 80, -0.25, 0.25))
            v = SampleVoice(buf, ratio, vel, dur, RELEASE.get(kind, 0.25), pan=pan)
        elif kind in ("arp", "keys", "sub"):
            v = SynthVoice(kind, midi, vel, dur)
        if v is None:
            return
        v.part = p
        v.offset = block_offset
        self.voices.append(v)
        self.hits[part] = self.pos + block_offset

    def start_transport(self):
        """Start the music, at step 0 of bar one. The stream opens with the app
        and the mix runs from the first block, but no step is played until this
        is called, so the App can stay silent while it loads and still begin at
        the top of the chord loop. Calling it again does nothing."""
        self.transport = True

    def _mark_bar(self, at):
        """A bar line at sample `at`: keep what the composer just planned for it.
        The tuple is replaced whole, so the UI thread never sees it half built."""
        self.bar_marks = self.bar_marks[-2:] + ((at, self.composer.bar_view),)

    def bar_now(self):
        """-> (seconds into the bar that is audible now, its Composer.BarView),
        or (0.0, None) before the first bar line has been heard."""
        heard = self.pos - int(self.latency * SR)
        for at, view in reversed(self.bar_marks):
            if at <= heard:
                return (heard - at) / SR, view
        return 0.0, None

    def _callback(self, out, frames, time_info, status):
        t0 = _time.perf_counter()
        end = self.pos + frames
        if not self.transport:
            self.next_step_at = end          # held at bar one, so nothing has to catch up later
        elif self.fpga_mode:
            while self.fpga_input:
                tick, step, event_mask, active_mask = self.fpga_input.popleft()
                at = None
                if self.fpga_origin_tick is not None:
                    at = self.fpga_origin_sample + (tick - self.fpga_origin_tick) * self.step_len
                # First tick, or the transport was stopped / reset / restarted (pause,
                # a new photo): the old mapping would put this tick in the past, so
                # anchor again and keep the lookahead.
                if at is None or tick <= self.fpga_origin_tick or at < self.pos - self.step_len:
                    self.fpga_origin_tick = tick
                    self.fpga_origin_sample = self.pos + self.fpga_lookahead_steps * self.step_len
                    at = self.fpga_origin_sample
                self.fpga_pending.append((at, tick, event_mask, active_mask))
            while self.fpga_pending and self.fpga_pending[0][0] < end:
                at, tick, event_mask, active_mask = self.fpga_pending.popleft()
                offset = max(0, at - self.pos)
                allowed = event_mask & active_mask
                for ev in self.composer.step(tick):
                    track = self.fpga_track_index.get(ev[0], -1)
                    if track >= 0 and (allowed & (1 << track)):
                        self._trigger(ev, offset)
                    elif track < 0 and ev[0] in C.INSTRUMENTS:     # no track on the board: clock only
                        self._trigger(ev, offset)
                if tick % C.STEPS_PER_PHRASE == 0:
                    self._mark_bar(self.pos + offset)
                if tick % 2 == 0 and self.pending_sfx:
                    pending, self.pending_sfx = self.pending_sfx, []
                    for buf, gain in pending:
                        v = SampleVoice(buf, 1.0, gain, 0, release_s=0.05)
                        v.part, v.offset = self.parts["sfx"], offset
                        self.voices.append(v)
                self.step = tick + 1
        else:
            while self.next_step_at < end:
                offset = self.next_step_at - self.pos
                for ev in self.composer.step(self.step):
                    self._trigger(ev, offset)
                if self.step % C.STEPS_PER_PHRASE == 0:
                    self._mark_bar(self.next_step_at)
                if self.step % 2 == 0 and self.pending_sfx:       # 8th-note grid
                    pending, self.pending_sfx = self.pending_sfx, []
                    for buf, gain in pending:
                        v = SampleVoice(buf, 1.0, gain, 0, release_s=0.05)
                        v.part, v.offset = self.parts["sfx"], offset
                        self.voices.append(v)
                self.step += 1
                self.next_step_at += self.step_len
        # part gains: one linear ramp per block, ~0.5 s fade
        ramp = np.linspace(0, 1, frames, dtype=np.float32)[:, None]
        gains, sends = {}, {}
        control_levels, control_lfos = self.fpga_controls
        for p in self.parts.values():
            g0 = p.gain
            g1 = g0 + (p.target - g0) * min(1.0, frames / (0.5 * SR))
            p.gain = g1
            t0 = p.trim
            p.trim = t1 = t0 + (p.trim_to - t0) * min(1.0, frames / (0.05 * SR))
            g0, g1 = g0 * t0, g1 * t1
            control_gain = 1.0
            track = self.fpga_track_index.get(p.name)
            if self.fpga_mode and track is not None:
                control_gain = (control_levels[track] / 255.0) * (1.0 - control_lfos[track] / 255.0)
            g = (g0 + (g1 - g0) * ramp) * p.level * control_gain
            gains[p.name] = g
            sends[p.name] = g[:, 0] * p.send
        dry = np.zeros((frames, 2), np.float32)
        send = np.zeros(frames, np.float32)
        alive = []
        for v in self.voices:
            off = v.offset
            if off >= frames:                 # starts in a later block
                v.offset -= frames
                alive.append(v)
                continue
            blk = v.render(frames - off)
            g = gains[v.part.name]
            if off:
                dry[off:] += blk * g[off:]
                send[off:] += blk.mean(axis=1) * sends[v.part.name][off:]
                v.offset = 0
            else:
                dry += blk * g
                send += blk.mean(axis=1) * sends[v.part.name]
            if not v.done:
                alive.append(v)
        self.voices = alive
        mix = dry + self.reverb.process(send)
        if status:
            self.xruns += 1
        # makeup for sparse bands, smoothed over ~1 s
        active = sum(1 for n, p in self.parts.items() if n not in ("backing", "sfx") and p.target > 0)
        want = C.MAKEUP.get(active, 1.0)
        self.makeup += (want - self.makeup) * min(1.0, frames / (1.0 * SR))
        mix *= self.makeup
        peak = float(np.abs(mix).max())
        self.pre_peak = max(self.pre_peak * 0.999, peak)
        # limiter: ride the gain, never bend the waveform. Attack within 32
        # samples, slow release; the clip below only ever catches stray samples.
        need = min(1.0, C.CEILING / peak) if peak > 0 else 1.0
        g0 = self.lim_gain
        if need < g0:
            g1 = need
            ramp_g = np.full(frames, g1, np.float32)
            k = min(32, frames)
            ramp_g[:k] = np.linspace(g0, g1, k, dtype=np.float32)
        else:
            g1 = g0 + (need - g0) * min(1.0, frames / (C.LIMITER_RELEASE_S * SR))
            ramp_g = np.linspace(g0, g1, frames, dtype=np.float32)
        self.lim_gain = g1
        self.gain_reduction_db = -20 * np.log10(max(g1, 1e-6))
        np.clip(mix * ramp_g[:, None], -1.0, 1.0, out=out)
        self.pos = end
        beat = self.step_len * C.STEPS_PER_BEAT
        self.pulse = (self.pos % beat) / beat
        self.cpu = (_time.perf_counter() - t0) / (frames / SR)
