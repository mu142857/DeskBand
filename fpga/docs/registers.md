# PS/PL register contract

The onboard J12 USB-UART terminates at PS UART1. A bare-metal application on
the Cortex-A9 will parse serial messages and access the PL through AXI-Lite.
This document fixes that boundary before the AXI wrapper is implemented.

| Offset | Name | Direction | Meaning |
|---:|---|---|---|
| `0x00` | `ID_VERSION` | RO | `0x44420101` (`DB`, major 1, minor 1) |
| `0x04` | `CONTROL` | RW/pulse | bit 0 run, bit 1 transport reset |
| `0x08` | `CYCLES_PER_STEP` | RW | FPGA clocks per sixteenth note |
| `0x0C` | `ABSOLUTE_TICK` | RO | Tick currently being scheduled |
| `0x10` | `APPLIED_MASK` | RO | Current seven-track enable mask |
| `0x14` | `MASK_REQUEST` | WO | bits 6:0 mask, bits 9:8 quantization, bit 31 valid |
| `0x18` | `BUTTON_STATUS` | RW1C | button live 3:0, press 11:8, release 19:16, switches 27:24 |
| `0x1C` | `VARIATION_CONTROL` | RW | bit 0 enables automatic bar variation |
| `0x20` | `PATTERN_0` | RW | cup, low 16 bits |
| `0x24` | `PATTERN_1` | RW | pen |
| `0x28` | `PATTERN_2` | RW | bottle |
| `0x2C` | `PATTERN_3` | RW | book |
| `0x30` | `PATTERN_4` | RW | glasses |
| `0x34` | `PATTERN_5` | RW | cell phone |
| `0x38` | `PATTERN_6` | RW | laptop |
| `0x40` | `STATUS` | RO/W1C | count 7:0, overflow bit 31; write bit 31 to clear |
| `0x48` | `EVENT_LO` | RO | oldest event tick; does not pop |
| `0x4C` | `EVENT_HI` | RO/pop | step 3:0, event mask 10:4, active mask 17:11, mask-applied 18 |
| `0x58` | `ENVELOPE_ACTIVE` | RO | active bits 6:0; command-ready bit 31 |
| `0x5C` | `ENVELOPE_COMMAND` | WO | duration 31:16, target 15:8, track 2:0 |
| `0x60–0x78` | `LEVEL_0–6` | RO | current unsigned 8-bit level for each track |
| `0x80` | `LFO_COMMAND` | WO | valid 31, reset-phase 30, enable 29, depth 28:21, track 2:0 |
| `0x84` | `LFO_INCREMENT` | RW | 24-bit phase increment used by the next command |
| `0x88` | `LFO_STATUS` | RO | enabled bits 6:0 |
| `0x90–0xA8` | `LFO_VALUE_0–6` | RO | current unsigned 8-bit triangle value per track |
| `0xAC` | `VARIATION_STATUS` | RO | energy 1:0, energy-pending 2, locked 9:3, lock-pending 16:10, fill-pending 17, fill-active 18 |
| `0xB0` | `VARIATION_RANDOM` | RO | current 16-bit LFSR state |
| `0xB4` | `BAR_INDEX` | RO | generated bar number since transport reset |

Quantization values are `0 = next step`, `1 = next beat`, and `2 = next bar`.
Reserved values and bits must be written as zero.

Software must read `EVENT_LO` before `EVENT_HI`. Reading `EVENT_HI` removes
the oldest FIFO entry. The FIFO is 16 entries by default and preserves a
sticky overflow flag so missed events cannot be silent.

Envelope duration is measured in 100 Hz control updates by default. A duration
of zero sets the target immediately; nonzero durations use parallel signed
Q8.16 accumulators and force an exact final value. Slope division is iterative
and takes 25 FPGA clocks; software must wait for command-ready before writing
another nonzero-duration command.

Each enabled LFO adds its 24-bit phase increment on the same 100 Hz control
update. The triangle output is scaled by depth. For a desired frequency in Hz,
software uses `increment = round(frequency * 2^24 / 100)`; reset-phase makes
repeatable beat-synchronized modulation starts possible.

Variation is enabled after reset. Bar zero preserves every base-pattern hit.
On later bars a maximal-length 16-bit LFSR selects phase and either 1/2, 3/4,
or full density. Seven parallel modulo-four Bresenham accumulators operate only
on hits present in each base pattern, so hardware never invents a pitch/event
the Mac did not supply. Step zero is protected; bass (track 2) and strings
(track 4) remain harmonic anchors. Energy, track locks, and one-bar fills are
committed atomically at bar boundaries.

The AXI wrapper must use clock-domain crossing FIFOs if its AXI clock differs
from the timing core clock. The first implementation should use one shared
100 MHz `FCLK0` to avoid unnecessary CDC risk.
