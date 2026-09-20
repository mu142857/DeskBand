#!/usr/bin/env python3
"""Physical Zybo UART/FPGA smoke test, independent of the WaveLens app."""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wavelens.fpga_protocol import parse_fpga_line


PATTERNS = (0x5551, 0x5555, 0x1041, 0x5555, 0x0001, 0x4444, 0x4924)
RESET_SEED = 0x1ACE


def next_lfsr(state):
    feedback = ((state >> 15) ^ (state >> 13) ^
                (state >> 12) ^ (state >> 10)) & 1
    value = ((state << 1) & 0xFFFF) | feedback
    return value or RESET_SEED


def euclidean_subset(candidates, numerator, phase):
    result = 0
    accumulator = phase
    for step in range(16):
        if candidates & (1 << step):
            if (numerator == 1 and (accumulator & 3) == 0) or \
                    (numerator == 2 and not (accumulator & 1)) or \
                    (numerator == 3 and (accumulator & 3) != 3) or \
                    numerator >= 4:
                result |= 1 << step
            accumulator = (accumulator + 1) & 7
    if candidates & 1:
        result |= 1
    return result


def candidate_grid(track, eighths=False):
    if track == 5:
        return 0x5554 if eighths else 0x7776
    return 0x5555 if eighths else 0x7777


def patterns_for_bar(bar):
    if bar == 0:
        return PATTERNS
    state = RESET_SEED
    for _ in range(bar):
        state = next_lfsr(state)
    generated = []
    for track, pattern in enumerate(PATTERNS):
        dense = ((state >> track) ^ (state >> (track + 7))) & 1
        numerator = 2 + dense
        if track == 3:
            numerator = 1 + dense
        generated.append(euclidean_subset(
            candidate_grid(track), numerator,
            (state >> (track * 2)) & 0x3))
    return tuple(generated)


def expected_events(tick):
    step = tick % 16
    patterns = patterns_for_bar(tick // 16)
    return sum(((pattern >> step) & 1) << track
               for track, pattern in enumerate(patterns))


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
        if not pong or identity != "44420103":
            raise RuntimeError(f"firmware/PL identity failed: pong={pong}, id={identity}")

        send("STOP")
        send("RESET")
        send("TEMPO 240")
        send("VARIATION ON")
        send("MASK 7F STEP")
        send("START")
        events = []
        for message in messages(3.0):
            if message.kind == "EV":
                events.append(message.fields)
                if len(events) == 32:
                    break
        if len(events) != 32:
            raise RuntimeError(f"received {len(events)}/32 timing events")
        for index, (tick, step, event_mask, active_mask, _changed) in enumerate(events):
            expected = expected_events(index)
            wanted = (index, index % 16, expected, 0x7F)
            if (tick, step, event_mask, active_mask) != wanted:
                raise RuntimeError(
                    f"event {index}: got {(tick, step, event_mask, active_mask)}, "
                    f"expected {wanted}"
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

        print("PASS: UART, PL ID, generated bars, sequencer, envelope, and LFO")
    finally:
        send("LFOOFF 0")
        send("ENV 0 255 0")
        send("STOP")
        ser.close()


if __name__ == "__main__":
    main()
