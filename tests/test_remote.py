"""Remote port end to end (no camera, no window, no sound device):
commands arrive over UDP, the app applies them, state comes back."""

import json
import os
import socket
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C

C.REMOTE_HOST, C.REMOTE_PORT = "127.0.0.1", 9055          # not the live app's port

import main as M                                           # noqa: E402
import soundfile as sf                                     # noqa: E402


def pump(app, blocks=1):
    for _ in range(blocks):
        app.engine._callback(np.zeros((C.BLOCK_SIZE, 2), np.float32), C.BLOCK_SIZE, None, None)


def test_remote():
    app = M.App()
    app.engine.load_instruments(log=lambda s: None)
    app.remote.start()
    time.sleep(0.2)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)

    def ask(obj):
        sock.sendto(json.dumps(obj).encode(), (C.REMOTE_HOST, C.REMOTE_PORT))
        reply = json.loads(sock.recvfrom(65535)[0].decode())
        app.process_commands()
        return reply

    assert ask({"cmd": "ping"})["ok"]
    assert not ask({"cmd": "nonsense"})["ok"]
    assert not ask({"cmd": "style", "chords": [["bad", 99, [1, 2, 3]]]})["ok"]

    # force a part on, then hand it back to the photo
    assert ask({"cmd": "part", "name": "cup", "on": True})["ok"]
    assert app.engine.parts["cup"].target == 1.0
    ask({"cmd": "part", "name": "cup", "on": None})
    assert app.engine.parts["cup"].target == 0.0

    # tempo
    ask({"cmd": "bpm", "value": 100})
    assert app.engine.bpm == 100 and app.engine.step_len == round(60 / 100 / 4 * C.SAMPLE_RATE)
    ask({"cmd": "bpm", "value": 120})

    # a new chord loop lands on the next loop start, never mid-loop
    ask({"cmd": "part", "name": "bottle", "on": True})
    with open(os.path.join(C.ROOT, "styles", "descending.json")) as f:
        style = json.load(f)
    pump(app, 4)
    assert ask({"cmd": "style", "chords": style["chords"]})["ok"]
    names = []
    for _ in range(int(17 * C.SAMPLE_RATE / C.BLOCK_SIZE)):           # rest of this loop + all of the next
        pump(app)
        if not names or names[-1] != app.composer.chord_name:
            names.append(app.composer.chord_name)
    assert "Dm7" in names and "Cmaj7" in names, names
    i = names.index("Dm7")
    assert names[i - 2:i] == ["Fmaj7", "Em7"], names              # entered at the top of the new loop

    # a three-note voicing must not break any pattern
    for n in C.INSTRUMENTS:
        ask({"cmd": "part", "name": n, "on": True})
    ask({"cmd": "style", "chords": [["C", 0, [48, 52, 55]], ["F#dim", 6, [54, 57, 60]]]})
    pump(app, int(10 * C.SAMPLE_RATE / C.BLOCK_SIZE))
    assert app.composer.chord_name in ("C", "F#dim")

    # one-shot sound: starts on an 8th note, goes through the engine
    path = os.path.join(C.CACHE_DIR, "_test_sfx.wav")
    sf.write(path, (np.sin(np.arange(4800) / 10) * 0.5).astype(np.float32), 48000)
    before = len(app.engine.voices)
    assert ask({"cmd": "sfx", "file": path, "gain": 0.5})["ok"]
    assert app.engine.pending_sfx
    pump(app, int(0.3 * C.SAMPLE_RATE / C.BLOCK_SIZE) + 1)
    assert not app.engine.pending_sfx
    os.remove(path)

    st = ask({"cmd": "state"})
    assert st["type"] == "state" and set(st["parts"]) == set(C.INSTRUMENTS) and 0 <= st["step"] < 16
    assert ask({"cmd": "subscribe", "hz": 30})["ok"]
    got = json.loads(sock.recvfrom(65535)[0].decode())
    assert got["type"] == "state"
    app.remote.stop()
    print("state sample:", {k: st[k] for k in ("mode", "bpm", "bar", "step", "beat", "chord")})


if __name__ == "__main__":
    test_remote()
    print("ok")
