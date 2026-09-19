#!/usr/bin/env python3
"""Physical Zybo UART/FPGA smoke test, independent of the DeskBand app."""

import argparse
import time

from deskband.fpga_protocol import parse_fpga_line


PATTERNS = (0x5551, 0x5555, 0x1041, 0x5555, 0x0001, 0x4444, 0x4924)


def expected_events(step):
    return sum(((pattern >> step) & 1) << track
               for track, pattern in enumerate(PATTERNS))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("port", help="J12 serial port, e.g. /dev/cu.usbserial-...")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required: python -m pip install pyserial") from error

    ser = serial.Serial(args.port, args.baud, timeout=0.05)

    def send(command):
        ser.write((command + "\n").encode("ascii"))

    def messages(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            raw = ser.readline()
            if not raw:
                continue
            try:
                message = parse_fpga_line(raw)
            except ValueError:
                continue
            if message is not None:
                yield message

    try:
        ser.reset_input_buffer()
        send("PING")
        send("ID")
        identity = None
        pong = False
        for message in messages(1.0):
            pong |= message.kind == "PONG"
            if message.kind == "ID" and message.fields:
                identity = message.fields[0].upper()
            if pong and identity is not None:
                break
        if not pong or identity != "44420100":
            raise RuntimeError(f"firmware/PL identity failed: pong={pong}, id={identity}")

        send("STOP")
        send("RESET")
        send("TEMPO 240")
        send("MASK 7F STEP")
        send("START")
        events = []
        for message in messages(3.0):
            if message.kind == "EV":
                events.append(message.fields)
                if len(events) == 16:
                    break
        if len(events) != 16:
            raise RuntimeError(f"received {len(events)}/16 timing events")
        for index, (tick, step, event_mask, active_mask, _changed) in enumerate(events):
            expected = expected_events(index)
            if (tick, step, event_mask, active_mask) != (index, index, expected, 0x7F):
                raise RuntimeError(
                    f"event {index}: got {(tick, step, event_mask, active_mask)}, "
                    f"expected {(index, index, expected, 0x7F)}"
                )

        send("LFO 0 400000 255")
        lfo_values = set()
        for message in messages(0.5):
            if message.kind == "CV":
                lfo_values.add(message.fields[7])
                if len(lfo_values) >= 3:
                    break
        if len(lfo_values) < 3:
            raise RuntimeError(f"LFO did not move through three values: {sorted(lfo_values)}")

        send("LFOOFF 0")
        send("ENV 0 0 4")
        envelope_reached_zero = False
        for message in messages(0.5):
            if message.kind == "CV" and message.fields[0] == 0:
                envelope_reached_zero = True
                break
        if not envelope_reached_zero:
            raise RuntimeError("track-0 envelope did not reach zero")

        print("PASS: physical UART, PL ID, 16-step sequencer, envelope, and LFO")
    finally:
        send("LFOOFF 0")
        send("ENV 0 255 0")
        send("STOP")
        ser.close()


if __name__ == "__main__":
    main()
