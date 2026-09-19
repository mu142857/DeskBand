#!/usr/bin/env python3
"""Bridge the Zybo Z7-20 hardware conductor to DeskBand over localhost UDP.

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

from deskband.fpga_protocol import (command_mask, command_tempo,
                                    command_variation, parse_fpga_line)

TRACKS = ("cup", "pen", "bottle", "book", "glasses", "cell phone", "laptop")


def button_effects(pressed, switches, muted, btn1_master=False):
    """Route Mac controls and retain mixer mutes across later shelf changes.

    In performance mode BTN1 is owned by FPGA rhythm locking. In mixer mode
    it mutes a track unless the legacy master-play mapping was requested.
    """
    commands = []
    mask_changed = False
    if pressed & 1:
        commands.append({"cmd": "toggle"})
    if pressed & 2 and not switches & 8:
        if btn1_master:
            commands.append({"cmd": "play"})
        else:
            muted ^= 1 << ((switches & 7) % len(TRACKS))
            mask_changed = True
    return commands, muted, mask_changed


def send_json(sock, address, message):
    sock.sendto(json.dumps(message, separators=(",", ":")).encode(), address)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", help="Zybo J12 serial device, e.g. /dev/cu.usbserial-...")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--udp-port", type=int, default=9000)
    parser.add_argument("--lookahead", type=int, default=2, choices=range(1, 9))
    parser.add_argument("--btn1-master", action="store_true",
                        help="map mixer-mode BTN1 to app play/pause instead of track mute")
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
    hardware_mute = 0
    current_bpm = None
    current_run = None
    last_subscribe = 0.0

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
    print(f"[zybo] {args.port} @ {args.baud}; DeskBand udp://{args.host}:{args.udp_port}")
    try:
        while True:
            now = time.monotonic()
            if now - last_subscribe > 4.0:
                send_json(udp, address, {"cmd": "subscribe", "hz": 20})
                send_json(udp, address, {"cmd": "fpga_mode", "on": True,
                                          "lookahead_steps": args.lookahead,
                                          **({"bpm": current_bpm} if current_bpm else {})})
                last_subscribe = now

            raw = ser.readline()
            if raw:
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
                    commands, hardware_mute, mask_changed = button_effects(
                        pressed, switches, hardware_mute, args.btn1_master)
                    for command in commands:
                        send_json(udp, address, command)
                    if mask_changed:
                        # Recalculate the shelf mask with the persistent board mute.
                        current_mask = None
                    print(f"[zybo] buttons={live:x} pressed={pressed:x} selector={switches:x}")
                elif message and message.kind == "BAR":
                    bar, energy, locks, fill, queued, enabled, random_state = message.fields
                    send_json(udp, address, {"cmd": "fpga_bar", "bar": bar,
                              "energy": energy, "locks": locks, "fill": bool(fill),
                              "fill_queued": bool(queued), "enabled": bool(enabled),
                              "random": random_state})
                    print(f"[zybo] bar={bar} energy={energy} locks={locks:02x} "
                          f"fill={fill} queued={queued} rng={random_state:04x}")
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
                # The band lives on DeskBand's shelf and plays in preview too, so the
                # transport follows "is anything sounding", not the photo mode:
                # parts[x].on is already false for everything while paused.
                mask = 0
                for track, name in enumerate(TRACKS):
                    if packet.get("parts", {}).get(name, {}).get("on"):
                        mask |= 1 << track
                mask &= ~hardware_mute
                if mask != current_mask:
                    serial_command(command_mask(mask, "BEAT")); current_mask = mask
                run = mask != 0
                if run != current_run:
                    if run:
                        serial_command("RESET"); serial_command("START")
                    else:
                        serial_command("STOP")
                    current_run = run
            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\n[zybo] stopping")
    finally:
        serial_command("STOP")
        send_json(udp, address, {"cmd": "fpga_mode", "on": False})
        ser.close(); udp.close()


if __name__ == "__main__":
    main()
