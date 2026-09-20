"""A stand-in for WaveLens's remote port: same UDP/JSON protocol, no camera,
no audio, no dependencies (plain python3 on any OS). Use it to develop a
badge, an FPGA console, a lamp robot or an AI script without the real app.

  python3 tools/remote_sim.py [port]

It keeps a fake clock at 120 BPM, walks the chord loop, accepts every command
and prints what the real app would do."""

import json
import socket
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
PARTS = ["cup", "pen", "bottle", "book", "glasses", "cell phone", "laptop"]
chords = ["Fmaj7", "G6", "Em7", "Am(add9)"]
bpm, mode, t0 = 120.0, "preview", time.time()
on = {p: False for p in PARTS}
saved = []                   # the shelf: instruments kept from earlier photos, first shot first
playing = True               # the master switch beside the shutter
subs = {}


def state():
    beats = (time.time() - t0) * bpm / 60
    step = int(beats * 4)
    bar = step // 16
    return {"type": "state", "mode": mode, "bpm": bpm, "bar": bar, "step": step % 16,
            "beat": int(beats) % 4, "beat_phase": round(beats % 1, 3),
            "chord": chords[bar % len(chords)], "chord_index": bar % len(chords),
            "parts": {p: {"on": on[p] and playing,
                          "glow": round(max(0.0, 1 - (beats % 1) * 2), 3) if on[p] and playing else 0.0} for p in PARTS},
            "detected": [p for p in PARTS if on[p]] if mode == "show" else [],
            "playing": playing, "saved": saved, "selected": [p for p in saved if on[p]]}


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))
sock.settimeout(0.01)
print(f"WaveLens simulator on udp://0.0.0.0:{PORT}")
while True:
    try:
        data, addr = sock.recvfrom(65535)
        try:
            msg = json.loads(data.decode())
            cmd = msg["cmd"]
        except Exception:
            sock.sendto(b'{"ok": false, "error": "send one JSON object with a \\"cmd\\" field"}', addr)
            continue
        reply = {"ok": True, "queued": cmd}
        if cmd == "ping":
            reply = {"ok": True, "pong": time.time()}
        elif cmd == "state":
            reply = state()
        elif cmd == "subscribe":
            hz = min(max(float(msg.get("hz", 20)), 1), 60)
            subs[addr] = [time.time() + 10, 1 / hz, 0.0]
            reply = {"ok": True, "subscribed_hz": hz, "renew_within_s": 10}
        elif cmd in ("shoot", "retake", "toggle"):
            mode = "show" if (cmd == "shoot" or (cmd == "toggle" and mode == "preview")) else "preview"
            if mode == "show":                    # pretend each photo finds the next unsaved thing
                found = next((p for p in PARTS if p not in saved), PARTS[0])
                if found not in saved:
                    saved.append(found)
                on[found] = True                  # going back to preview leaves the band playing
        elif cmd == "select" and msg.get("name") in on:
            name = msg["name"]
            if name in saved:                     # only a saved instrument can be selected
                on[name] = (not on[name]) if msg.get("on") is None else bool(msg["on"])
        elif cmd == "play":
            playing = (not playing) if msg.get("on") is None else bool(msg["on"])
        elif cmd == "silence":
            on = {p: False for p in PARTS}
        elif cmd == "part" and msg.get("name") in on:
            on[msg["name"]] = bool(msg.get("on"))
        elif cmd == "bpm":
            bpm = float(min(max(msg.get("value", 120), 60), 180))
        elif cmd == "style":
            chords = [c[0] for c in msg.get("chords", [])] or chords
        elif cmd == "sfx":
            pass
        else:
            reply = {"ok": False, "error": f"unknown cmd {cmd!r}"}
        if cmd != "state":
            print(f"{addr[0]}: {msg}")
        sock.sendto(json.dumps(reply).encode(), addr)
    except socket.timeout:
        pass
    now = time.time()
    for addr, sub in list(subs.items()):
        if now > sub[0]:
            del subs[addr]
        elif now - sub[2] >= sub[1]:
            sub[2] = now
            sock.sendto(json.dumps(state()).encode(), addr)
