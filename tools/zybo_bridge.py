#!/usr/bin/env python3
"""Bridge the Zybo Z7-20 hardware conductor to WaveLens over localhost UDP.

Install pyserial in the Mac virtual environment, then run:
  .venv/bin/pip install pyserial
  .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
"""

import argparse
import os
import sys
import json
import socket
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens.fpga_protocol import (LineBuffer, command_mask, command_tempo,
                                    command_variation, parse_fpga_line)
from wavelens import config as C

TRACKS = tuple(C.FPGA_TRACKS)


def button_effects(pressed):
    """Map the two Mac-owned board buttons to unambiguous UI actions."""
    commands = []
    if pressed & 1:
        commands.append({"cmd": "toggle"})
    if pressed & 2:
        commands.append({"cmd": "math"})
    return commands


def transport_effects(parts, current_mask, current_run):
    """Return serial commands and state for one WaveLens state packet.

    A transport reset clears the PL's pending and applied masks, so a new run
    must send RESET before MASK. Parts without a hardware track (currently the
    mouth/baritone sax) still need the FPGA clock, even though their mask is 0.
    """
    parts = parts or {}
    mask = 0
    for track, name in enumerate(TRACKS):
        if parts.get(name, {}).get("on"):
            mask |= 1 << track
    run = any(part.get("on") for part in parts.values()
              if isinstance(part, dict))

    commands = []
    if run != current_run:
        if run:
            commands.extend(("RESET", command_mask(mask, "BEAT"), "START"))
        else:
            commands.append("STOP")
        current_mask = mask
        current_run = run
    elif run and mask != current_mask:
        commands.append(command_mask(mask, "BEAT"))
        current_mask = mask
    return commands, current_mask, current_run


def send_json(sock, address, message):
    sock.sendto(json.dumps(message, separators=(",", ":")).encode(), address)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", help="Zybo J12 serial device, e.g. /dev/cu.usbserial-...")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=9000)
    parser.add_argument("--lookahead", type=int, default=2, choices=range(1, 9))
    args = parser.parse_args()

    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required: .venv/bin/pip install pyserial") from error

    ser = serial.Serial(args.port, args.baud, timeout=0.005)
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.setblocking(False)
    address = (args.host, args.udp_port)
    current_mask = None
    current_bpm = None
    current_run = None
    last_subscribe = 0.0
    lines = LineBuffer()

    def serial_command(command):
        ser.write((command + "\n").encode("ascii"))

    # READY may have been printed before the Mac opened the serial port.  These
    # commands are idempotent, so initialize immediately as well as on READY.
    serial_command("PING")
    serial_command("RESET")
    serial_command("STOP")
    serial_command(command_variation(True))
    send_json(udp, address, {"cmd": "fpga_mode", "on": True,
                              "lookahead_steps": args.lookahead})
    print(f"[zybo] {args.port} @ {args.baud}; WaveLens udp://{args.host}:{args.udp_port}")
    try:
        while True:
            now = time.monotonic()
            if now - last_subscribe > 4.0:
                send_json(udp, address, {"cmd": "subscribe", "hz": 20})
                send_json(udp, address, {"cmd": "fpga_mode", "on": True,
                                          "lookahead_steps": args.lookahead,
                                          **({"bpm": current_bpm} if current_bpm else {})})
                last_subscribe = now

            # Whole lines only: see LineBuffer. read() returns after 5 ms at the latest,
            # so UDP state packets below are still serviced promptly.
            for raw in lines.feed(ser.read(ser.in_waiting or 1)):
                try:
                    message = parse_fpga_line(raw)
                except ValueError as error:
                    print("[zybo]", error)
                    message = None
                if message and message.kind == "READY":
                    serial_command("RESET"); serial_command("STOP")
                    serial_command(command_variation(True))
                elif message and message.kind == "EV":
                    tick, step, events, active, changed = message.fields
                    send_json(udp, address, {"cmd": "fpga_event", "tick": tick,
                              "step": step, "events": events, "active": active,
                              "mask_changed": bool(changed)})
                elif message and message.kind == "CV":
                    send_json(udp, address, {"cmd": "fpga_controls",
                              "levels": message.fields[:7], "lfos": message.fields[7:]})
                elif message and message.kind == "BTN":
                    live, pressed, released, switches = message.fields
                    for command in button_effects(pressed):
                        send_json(udp, address, command)
                    print(f"[zybo] buttons={live:x} pressed={pressed:x} selector={switches:x}")
                elif message and message.kind == "BAR":
                    bar, energy, locks, fill, queued, enabled, random_state, eighths, grid_queued = message.fields
                    send_json(udp, address, {"cmd": "fpga_bar", "bar": bar,
                              "energy": energy, "locks": locks, "fill": bool(fill),
                              "fill_queued": bool(queued), "enabled": bool(enabled),
                              "random": random_state, "eighths": bool(eighths),
                              "grid_queued": bool(grid_queued)})
                    print(f"[zybo] bar={bar} energy={energy} locks={locks:02x} "
                          f"fill={fill} grid={'8th' if eighths else 'mixed'} "
                          f"queued={grid_queued} rng={random_state:04x}")
                elif message and message.kind == "TAP":
                    bpm, = message.fields
                    send_json(udp, address, {"cmd": "bpm", "value": bpm})
                    # The PL keeps the period it measured (say 119.6 BPM) while WaveLens
                    # takes the rounded figure. Left alone, the two clocks slide apart and
                    # notes start landing late. State the tempo again from WaveLens's next
                    # state packet so the board runs at exactly the BPM the Mac plays.
                    current_bpm = None
                    print(f"[zybo] four-tap tempo={bpm} BPM")
                elif message and message.kind in {"ERR", "FATAL"}:
                    print("[zybo]", raw.decode(errors="replace").strip())

            while True:
                try:
                    packet = json.loads(udp.recv(65535))
                except BlockingIOError:
                    break
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if packet.get("type") != "state":
                    continue
                bpm = int(round(packet.get("bpm", 120)))
                if bpm != current_bpm:
                    serial_command(command_tempo(bpm)); current_bpm = bpm
                commands, current_mask, current_run = transport_effects(
                    packet.get("parts", {}), current_mask, current_run)
                for command in commands:
                    serial_command(command)
            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\n[zybo] stopping")
    finally:
        serial_command("STOP")
        send_json(udp, address, {"cmd": "fpga_mode", "on": False})
        ser.close(); udp.close()


if __name__ == "__main__":
    main()
