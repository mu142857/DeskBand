"""Remote control: a tiny JSON-over-UDP port so hardware (badge, FPGA board,
lamp robot) and other programs (speech, LLM, sound generation) can drive
DeskBand and follow its beat without touching its code.

One UDP datagram = one JSON object. Every command gets a JSON reply to the
sender. Commands are only queued here; the app's main loop executes them, so
nothing in this thread can disturb audio or drawing.

  {"cmd": "ping"}
  {"cmd": "shoot"} | {"cmd": "retake"} | {"cmd": "toggle"}
  {"cmd": "play", "on": true}                     the master switch beside the shutter ("on": null or absent toggles);
                                                  paused = silent, but the selection on the shelf is kept
  {"cmd": "math", "on": true}                     math mode: melodies computed, never repeating (null toggles; from the next bar)
  {"cmd": "place", "name": "cup", "complexity": 0.7, "loudness": 0.4}
                                                  move a saved instrument on the stage, both 0..1 (either may be left out);
                                                  loudness 0.5 = its own level, complexity 0.5 = as written (from the next bar)
  {"cmd": "view", "stage": true}                  show the stage / the camera (null toggles, like tab)
  {"cmd": "select", "name": "cup", "on": true}    switch a saved instrument on/off on the shelf, like a click ("on": null toggles)
  {"cmd": "silence"}                              switch the whole shelf off (nothing is forgotten)
  {"cmd": "part", "name": "cup", "on": true}      force a part on/off, saved or not; "on": null = follow the shelf again
  {"cmd": "sfx", "file": "/abs/path.wav", "gain": 0.6}   play a sound on the next 8th note, through the reverb
  {"cmd": "bpm", "value": 110}
  {"cmd": "style", "chords": [["Fmaj7", 5, [53, 57, 60, 64]], ...], "bpm": 120}   new chord loop from the next loop start
  {"cmd": "fpga_bar", "bar": 12, "energy": 1, "eighths": false,
   "grid_queued": false, ...}                         bridge telemetry from the FPGA bar generator
  {"cmd": "subscribe", "hz": 20}                  stream state packets to the sender for 10 s (send again to renew)
  {"cmd": "state"}                                one state packet

State packet (what is *audible* now, already compensated for output latency):
  {"type": "state", "mode": "preview"|"show"|"summary", "bpm": 120, "bar": 12, "step": 6,
   "beat": 1, "beat_phase": 0.5, "chord": "G6", "chord_index": 1,
   "parts": {"cup": {"on": true, "glow": 0.83}, ...}, "detected": ["cup", "tablet"],
   "playing": true, "saved": ["cup", "pen"], "selected": ["cup"]}     (saved: top of the shelf first)
   ... "view": "camera"|"stage"|"summary", "placed": {"cup": {"complexity": 0.5, "loudness": 0.5}, ...},
   "fpga": {"bar": 12, "energy": 1, "eighths": false, ...} or null
"""

import json
import queue
import socket
import threading
import time

from . import config as C

COMMANDS = {"shoot", "retake", "toggle", "play", "math", "place", "view", "part", "select", "silence", "sfx", "bpm", "style",
            "fpga_mode", "fpga_event", "fpga_controls", "fpga_bar"}


def validate_style(chords):
    """-> cleaned chord list or raises ValueError with a readable reason."""
    if not isinstance(chords, list) or not 1 <= len(chords) <= 16:
        raise ValueError("chords must be a list of 1-16 entries")
    clean = []
    for c in chords:
        if not (isinstance(c, (list, tuple)) and len(c) == 3):
            raise ValueError('each chord is [name, root_pitch_class, [midi, ...]]')
        name, root, voicing = c
        if not isinstance(root, int) or not 0 <= root <= 11:
            raise ValueError(f"{name}: root must be a pitch class 0-11 (0 = C)")
        if not (isinstance(voicing, list) and 3 <= len(voicing) <= 5
                and all(isinstance(m, int) and 40 <= m <= 76 for m in voicing)):
            raise ValueError(f"{name}: voicing must be 3-5 MIDI notes between 40 and 76")
        clean.append((str(name)[:16], root, sorted(voicing)))
    return clean


class Remote(threading.Thread):
    def __init__(self, get_state):
        super().__init__(daemon=True)
        self.get_state = get_state
        self.commands = queue.Queue()
        self.subscribers = {}          # addr -> (expires, period)
        self.sock = None
        self.error = None
        self._halt = threading.Event()

    def stop(self):
        self._halt.set()

    def _send(self, obj, addr):
        try:
            self.sock.sendto(json.dumps(obj).encode(), addr)
        except OSError:
            pass

    def _handle(self, data, addr):
        try:
            msg = json.loads(data.decode())
            cmd = msg["cmd"]
        except Exception:
            return self._send({"ok": False, "error": "send one JSON object with a \"cmd\" field"}, addr)
        if cmd == "ping":
            return self._send({"ok": True, "pong": time.time()}, addr)
        if cmd == "state":
            return self._send(self.get_state(), addr)
        if cmd == "subscribe":
            hz = min(max(float(msg.get("hz", C.REMOTE_STATE_HZ)), 1.0), 60.0)
            self.subscribers[addr] = [time.time() + 10.0, 1.0 / hz, 0.0]
            return self._send({"ok": True, "subscribed_hz": hz, "renew_within_s": 10}, addr)
        if cmd not in COMMANDS:
            return self._send({"ok": False, "error": f"unknown cmd {cmd!r}", "known": sorted(COMMANDS | {'ping', 'state', 'subscribe'})}, addr)
        if cmd == "style":
            try:
                msg["chords"] = validate_style(msg.get("chords"))
            except ValueError as e:
                return self._send({"ok": False, "error": str(e)}, addr)
        self.commands.put(msg)
        self._send({"ok": True, "queued": cmd}, addr)

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((C.REMOTE_HOST, C.REMOTE_PORT))
            self.sock.settimeout(0.01)
        except OSError as e:
            self.error = f"remote control disabled: {e}"
            print(self.error, flush=True)
            return
        print(f"[remote] listening on udp://{C.REMOTE_HOST}:{C.REMOTE_PORT}", flush=True)
        while not self._halt.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                self._handle(data, addr)
            except socket.timeout:
                pass
            except OSError:
                break
            now = time.time()
            for addr, sub in list(self.subscribers.items()):
                expires, period, last = sub
                if now > expires:
                    del self.subscribers[addr]
                elif now - last >= period:
                    sub[2] = now
                    self._send(self.get_state(), addr)
        self.sock.close()
