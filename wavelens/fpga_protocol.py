"""Pure-Python codec for the Zybo UART line protocol (no serial dependency)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FpgaMessage:
    kind: str
    fields: tuple


class LineBuffer:
    """Reassemble the UART byte stream into whole lines.

    USB serial adapters hand bytes over in bursts that end wherever they end,
    often in the middle of a record. A timed readline() returns such a piece as
    if it were a line; both halves then fail to parse and the record (a step of
    the beat clock) is lost. Feed whatever has arrived; only lines that have
    actually been terminated come back, the rest waits for the next burst."""

    def __init__(self, limit=4096):
        self.pending = b""
        self.limit = limit

    def feed(self, data):
        self.pending += data
        *lines, self.pending = self.pending.split(b"\n")
        if len(self.pending) > self.limit:          # noise with no newline: do not grow forever
            self.pending = b""
        return [line for line in lines if line.strip()]


def parse_fpga_line(line):
    if isinstance(line, bytes):
        line = line.decode("ascii", "strict")
    words = line.strip().split()
    if not words:
        return None
    kind = words[0]
    try:
        if kind == "READY" and len(words) >= 2:
            return FpgaMessage(kind, tuple(words[1:]))
        if kind == "EV" and len(words) == 6:
            return FpgaMessage(kind, (int(words[1]), int(words[2]), int(words[3], 16),
                                             int(words[4], 16), int(words[5])))
        if kind == "CV" and len(words) == 15:
            values = tuple(int(value) for value in words[1:])
            if any(value < 0 or value > 255 for value in values):
                raise ValueError("control value outside 0..255")
            return FpgaMessage(kind, values)
        if kind == "BTN" and len(words) == 5:
            return FpgaMessage(kind, tuple(int(value, 16) for value in words[1:]))
        if kind == "BAR" and len(words) == 10:
            values = (int(words[1]), int(words[2]), int(words[3], 16),
                      int(words[4]), int(words[5]), int(words[6]),
                      int(words[7], 16), int(words[8]), int(words[9]))
            if not (values[0] >= 0 and 0 <= values[1] <= 2 and
                    0 <= values[2] <= 0x7f and
                    values[3] in (0, 1) and values[4] in (0, 1) and
                    values[5] in (0, 1) and 0 <= values[6] <= 0xffff and
                    values[7] in (0, 1) and values[8] in (0, 1)):
                raise ValueError("bar-generation value outside valid range")
            return FpgaMessage(kind, values)
        if kind == "TAP" and len(words) == 2:
            bpm = int(words[1])
            if not 60 <= bpm <= 180:
                raise ValueError("tap tempo outside 60..180 BPM")
            return FpgaMessage(kind, (bpm,))
        if kind in {"OK", "ERR", "PONG", "ID", "ST", "BUSY", "FATAL"}:
            return FpgaMessage(kind, tuple(words[1:]))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"malformed FPGA line: {line!r}") from error
    raise ValueError(f"unknown FPGA line: {line!r}")


def command_tempo(bpm):
    bpm = min(max(int(round(float(bpm))), 20), 400)
    return f"TEMPO {bpm}"


def command_mask(mask, quantization="BEAT"):
    quantization = quantization.upper()
    if quantization not in {"STEP", "BEAT", "BAR"}:
        raise ValueError("quantization must be STEP, BEAT, or BAR")
    if not 0 <= int(mask) <= 0x7f:
        raise ValueError("track mask must fit seven bits")
    return f"MASK {int(mask):02X} {quantization}"


def command_pattern(track, pattern):
    if not 0 <= int(track) < 7 or not 0 <= int(pattern) <= 0xffff:
        raise ValueError("invalid track or 16-step pattern")
    return f"PATTERN {int(track)} {int(pattern):04X}"


def command_envelope(track, target, duration):
    if not 0 <= int(track) < 7 or not 0 <= int(target) <= 255 or not 0 <= int(duration) <= 65535:
        raise ValueError("invalid envelope command")
    return f"ENV {int(track)} {int(target)} {int(duration)}"


def command_lfo(track, increment, depth):
    if not 0 <= int(track) < 7 or not 0 <= int(increment) <= 0xffffff or not 0 <= int(depth) <= 255:
        raise ValueError("invalid LFO command")
    return f"LFO {int(track)} {int(increment):06X} {int(depth)}"


def command_variation(enabled=True):
    return f"VARIATION {'ON' if enabled else 'OFF'}"
