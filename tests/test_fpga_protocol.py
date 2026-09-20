import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband.fpga_protocol import (LineBuffer, command_envelope, command_lfo, command_mask,
                                    command_pattern, command_tempo,
                                    command_variation, parse_fpga_line)
from deskband.remote import COMMANDS
from tools.zybo_bridge import button_effects, transport_effects


def test_line_buffer():
    """The UART arrives in bursts that stop mid-record (seen on the real board:
    'EV 904 8 01 1D' then ' 0\\r\\n'). No piece may be parsed, no record lost."""
    lines = LineBuffer()
    got = []
    for burst in (b"EV 904 8 01 1D", b" 0\r\nEV ", b"910 14 09 1D 0\r\nBTN 8 8 0 ", b"0\r\n", b"\r\n", b"TAP 114\r\nE"):
        got += lines.feed(burst)
    assert [parse_fpga_line(raw).kind for raw in got] == ["EV", "EV", "BTN", "TAP"]
    assert parse_fpga_line(got[0]).fields == (904, 8, 0x01, 0x1D, 0)
    assert lines.pending == b"E"                         # still waiting for the rest
    assert lines.feed(b"x" * 5000) == [] and lines.pending == b""      # noise cannot pile up


def test_fpga_protocol():
    event = parse_fpga_line(b"EV 42 10 45 7f 1\r\n")
    assert event.kind == "EV" and event.fields == (42, 10, 0x45, 0x7f, 1)
    controls = parse_fpga_line("CV " + " ".join(str(i) for i in range(14)))
    assert controls.fields[:7] == tuple(range(7)) and controls.fields[7:] == tuple(range(7, 14))
    assert parse_fpga_line("BTN 1 2 4 a").fields == (1, 2, 4, 10)
    bar = parse_fpga_line("BAR 12 1 09 1 0 1 ace1 1 0")
    assert bar.kind == "BAR" and bar.fields == (12, 1, 9, 1, 0, 1, 0xACE1, 1, 0)
    assert parse_fpga_line("TAP 137").fields == (137,)
    assert command_tempo(120.2) == "TEMPO 120"
    assert command_mask(0x45, "bar") == "MASK 45 BAR"
    assert command_pattern(6, 0xA55A) == "PATTERN 6 A55A"
    assert command_envelope(3, 127, 250) == "ENV 3 127 250"
    assert command_lfo(2, 0x400000, 200) == "LFO 2 400000 200"
    assert command_variation() == "VARIATION ON"
    assert command_variation(False) == "VARIATION OFF"
    assert {"play", "math", "place", "view", "select", "silence", "fpga_bar"} <= COMMANDS
    assert button_effects(1) == [{"cmd": "toggle"}]
    assert button_effects(2) == [{"cmd": "math"}]
    assert button_effects(3) == [{"cmd": "toggle"}, {"cmd": "math"}]

    # RESET clears pending/applied masks, so MASK must follow it on startup.
    commands, mask, run = transport_effects({"cup": {"on": True}}, None, False)
    assert commands == ["RESET", "MASK 01 BEAT", "START"]
    assert mask == 1 and run is True

    # The eighth software instrument has no mask bit but still needs FPGA ticks.
    commands, mask, run = transport_effects({"mouth": {"on": True}}, 0, False)
    assert commands == ["RESET", "MASK 00 BEAT", "START"]
    assert mask == 0 and run is True

    commands, mask, run = transport_effects(
        {"cup": {"on": True}, "pen": {"on": True}}, 1, True)
    assert commands == ["MASK 03 BEAT"] and mask == 3 and run is True
    commands, mask, run = transport_effects({"cup": {"on": False}}, mask, run)
    assert commands == ["STOP"] and run is False
    for malformed in ("", "EV 1 2", "CV " + " ".join(["256"] * 14),
                      "BAR -1 1 01 0 0 1 1234", "WHAT 1"):
        try:
            result = parse_fpga_line(malformed)
            assert result is None and not malformed
        except ValueError:
            pass


if __name__ == "__main__":
    test_line_buffer()
    test_fpga_protocol()
    print("PASS: Mac/Zybo protocol codec")
