"""Talk to a running DeskBand over its UDP port. Examples:

  remote_test.py ping
  remote_test.py shoot | retake | toggle | silence
  remote_test.py play | play on | play off                       the master switch (no word = toggle)
  remote_test.py select cup on | select cup off | select cup     a saved instrument on the shelf (no word = toggle)
  remote_test.py part cup on | part cup off | part cup auto
  remote_test.py sfx /path/to/sound.wav 0.6
  remote_test.py bpm 110
  remote_test.py style styles/descending.json
  remote_test.py state
  remote_test.py watch            print the beat for 10 s (what a badge or LED strip would follow)
"""

import json
import os
import socket
import sys
import time

HOST, PORT = os.environ.get("DESKBAND_HOST", "127.0.0.1"), int(os.environ.get("DESKBAND_PORT", 9000))


def ask(sock, obj):
    sock.sendto(json.dumps(obj).encode(), (HOST, PORT))
    return json.loads(sock.recvfrom(65535)[0].decode())


def main(argv):
    if not argv:
        sys.exit(__doc__)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    cmd = argv[0]
    if cmd in ("ping", "shoot", "retake", "toggle", "silence", "state"):
        print(ask(sock, {"cmd": cmd}))
    elif cmd == "play":
        print(ask(sock, {"cmd": "play", "on": {"on": True, "off": False}.get(argv[1]) if len(argv) > 1 else None}))
    elif cmd == "select":
        on = {"on": True, "off": False}.get(argv[2]) if len(argv) > 2 else None
        print(ask(sock, {"cmd": "select", "name": argv[1], "on": on}))
    elif cmd == "part":
        on = {"on": True, "off": False, "auto": None}[argv[2]]
        print(ask(sock, {"cmd": "part", "name": argv[1], "on": on}))
    elif cmd == "sfx":
        print(ask(sock, {"cmd": "sfx", "file": os.path.abspath(argv[1]), "gain": float(argv[2]) if len(argv) > 2 else 0.6}))
    elif cmd == "bpm":
        print(ask(sock, {"cmd": "bpm", "value": float(argv[1])}))
    elif cmd == "style":
        with open(argv[1]) as f:
            style = json.load(f)
        print(ask(sock, {"cmd": "style", "chords": style["chords"], "bpm": style.get("bpm")}))
    elif cmd == "watch":
        print(ask(sock, {"cmd": "subscribe", "hz": 20}))
        end, last = time.time() + 10, None
        while time.time() < end:
            st = json.loads(sock.recvfrom(65535)[0].decode())
            key = (st["bar"], st["beat"])
            if key != last:
                last = key
                on = [n for n, p in st["parts"].items() if p["on"]]
                print(f"bar {st['bar']:3d} beat {st['beat'] + 1}  {st['chord']:9s} {st['mode']:8s} playing: {', '.join(on) or '-'}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (socket.timeout, TimeoutError):
        sys.exit(f"no answer from udp://{HOST}:{PORT}: is DeskBand (or tools/remote_sim.py) running there?")
