"""Remote port end to end (no camera, no window, no sound device):
commands arrive over UDP, the app applies them, state comes back."""

import json
import os
import socket
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband import config as C

C.REMOTE_HOST, C.REMOTE_PORT = "127.0.0.1", 9055          # not the live app's port
C.SHELF_DIR = tempfile.mkdtemp(prefix="deskband_shelf_")  # nor its saved instruments

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

    # the shelf: only a saved instrument can be selected; selecting it starts it
    ask({"cmd": "select", "name": "pen", "on": True})
    assert app.engine.parts["pen"].target == 0.0
    photo = np.full((720, 1280, 3), 90, np.uint8)
    app.shelf.add("pen", "pencil", 0.6, photo, [100, 100, 300, 180])
    ask({"cmd": "select", "name": "pen", "on": True})
    assert app.engine.parts["pen"].target == 1.0
    st = ask({"cmd": "state"})
    assert st["saved"] == ["pen"] and st["selected"] == ["pen"]
    # the master switch: paused is silent, the selection survives
    ask({"cmd": "play", "on": False})
    st = ask({"cmd": "state"})
    assert app.engine.parts["pen"].target == 0.0 and not st["playing"] and not st["parts"]["pen"]["on"]
    assert st["selected"] == ["pen"]
    ask({"cmd": "play"})                                   # no "on": toggle
    assert app.engine.parts["pen"].target == 1.0 and ask({"cmd": "state"})["playing"]
    # the shelf fills in the order things were shot, and a re-shot keeps its place
    app.shelf.add("cup", "mug", 0.7, photo, [400, 300, 600, 500])
    app.shelf.add("pen", "pen", 0.8, photo, [100, 100, 300, 180])
    assert ask({"cmd": "state"})["saved"] == ["pen", "cup"]
    app.shelf.remove("cup")
    ask({"cmd": "select", "name": "pen"})                  # no "on": toggle
    assert app.engine.parts["pen"].target == 0.0
    ask({"cmd": "select", "name": "pen", "on": True})
    ask({"cmd": "silence"})
    assert app.engine.parts["pen"].target == 0.0 and "pen" in app.shelf.entries

    # force a part on, then hand it back to the shelf
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
    fd, path = tempfile.mkstemp(prefix="deskband_sfx_", suffix=".wav")
    os.close(fd)
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
