import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deskband.fpga_protocol import (command_envelope, command_lfo, command_mask,
                                    command_pattern, command_tempo, parse_fpga_line)


def test_fpga_protocol():
    event = parse_fpga_line(b"EV 42 10 45 7f 1\r\n")
    assert event.kind == "EV" and event.fields == (42, 10, 0x45, 0x7f, 1)
    controls = parse_fpga_line("CV " + " ".join(str(i) for i in range(14)))
    assert controls.fields[:7] == tuple(range(7)) and controls.fields[7:] == tuple(range(7, 14))
    assert parse_fpga_line("BTN 1 2 4 a").fields == (1, 2, 4, 10)
    assert command_tempo(120.2) == "TEMPO 120"
    assert command_mask(0x45, "bar") == "MASK 45 BAR"
    assert command_pattern(6, 0xA55A) == "PATTERN 6 A55A"
    assert command_envelope(3, 127, 250) == "ENV 3 127 250"
    assert command_lfo(2, 0x400000, 200) == "LFO 2 400000 200"
    for malformed in ("", "EV 1 2", "CV " + " ".join(["256"] * 14), "WHAT 1"):
        try:
            result = parse_fpga_line(malformed)
            assert result is None and not malformed
        except ValueError:
            pass


if __name__ == "__main__":
    test_fpga_protocol()
    print("PASS: Mac/Zybo protocol codec")
