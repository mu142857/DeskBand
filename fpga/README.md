# DeskBand FPGA conductor

The Zybo Z7-20 is the real-time conductor and effects controller. The Mac
still performs vision, composes pitches/chords, and renders samples, while the
Zynq owns musical time, seven-track sequencing, generated rhythm, four-tap
tempo measurement, quantized controls, envelopes, LFOs, and physical input.

```
camera -> Mac vision/composer -> UART commands -> Cortex-A9 -> AXI-Lite
                                                         -> FPGA timing core
FPGA event FIFO/envelopes/LFOs -> Cortex-A9 -> UART -> Mac sample scheduler
```

The Mac buffers hardware events by two sixteenth notes. This absorbs USB-UART
and UI-thread jitter; event spacing and track decisions still come from the
FPGA, and playback enters the audio callback at exact sample offsets.

## Implemented hardware

- programmable master sixteenth-note clock and absolute tick counter;
- seven parallel 16-step sequencers;
- automatic per-bar variation from a 16-bit maximal LFSR and seven parallel
  divider-free Euclidean/Bresenham phase accumulators;
- a 100 MHz four-tap tempo analyzer that averages three measured intervals;
- track-mask changes quantized to step, beat, or bar boundaries;
- a 16-entry timestamped event FIFO with sticky overflow detection;
- four synchronized/debounced buttons and four status switches;
- seven parallel Q8.16 level envelopes with exact endpoints;
- seven independent 24-bit triangle LFOs at a 100 Hz control rate;
- robust AXI4-Lite register interface at `0x43C00000`;
- official Zybo Z7-20 PS preset, UART1 on J12, and 100 MHz FCLK0;
- bare-metal Cortex-A9 UART command/event firmware; and
- Mac serial-to-UDP bridge plus sample-accurate engine scheduling.

The buttons have one fixed meaning; the switches do not change their layer:

| Button | Action |
|---|---|
| BTN0 | DeskBand shutter: photo/retake |
| BTN1 | toggle the Mac's Math melody mode at the next bar |
| BTN2 | toggle generated rhythm between mixed 8th/16th and eighth-only at the next bar |
| BTN3 | tap four times at quarter-note speed to set BPM |

Automatic variation is the default base behavior; no button press is needed.
The FPGA advances a repeatable 16-bit LFSR once per bar and uses parallel
modulo-four phase accumulators to place an evenly spaced quarter, half, three
quarters, or full set of onsets on safe musical grids. Those grids are wider
than the written patterns, so hardware can create new rhythmic onsets. The Mac
maps each new onset to a nearby chord-safe note, or a quiet hi-hat for drums.
Downbeats are protected and bass/strings remain stable.

The bridge sends BTN0/BTN1 to DeskBand as shutter/Math commands. BTN2 is
committed by the PL at a bar boundary. BTN3 is measured entirely against the
100 MHz FPGA clock: four valid taps provide three intervals, their average is
converted to a sixteenth-note period, clamped to 60–180 BPM, and reported to
the Mac so its sample scheduler adopts the same tempo. Retaking a photo does
not restart the musical clock.

While stopped, the four LEDs mirror the switches. While running, they display
the low four bits of the 16-step position.

## Verification

```bash
make -C fpga test lint ps-test
python3 tests/test_fpga_protocol.py
```

After sourcing Vivado, `make -C fpga vivado-check` runs out-of-context
synthesis. The script targets `xc7z020clg400-1` and fails on negative WNS.

## Build the board image

```bash
git clone --depth 1 https://github.com/Digilent/vivado-boards.git /tmp/digilent-vivado-boards
source /path/to/Vivado/2025.2/settings64.sh
vivado -mode batch -source fpga/vivado/build_project.tcl \
  -tclargs /tmp/digilent-vivado-boards/new/board_files bitstream
```

```bash
source /path/to/Vitis/2025.2/settings64.sh
XILINX_VITIS_DATA_DIR=/tmp/deskband-vitis-data \
  vitis -s fpga/vitis/build_firmware.py
bootgen -arch zynq -image fpga/vitis/boot.bif -o fpga/build/BOOT.BIN -w
```

Generated outputs are the Vivado bitstream, the Cortex-A9 firmware ELF, and
`fpga/build/BOOT.BIN`.

## Boot the Zybo Z7-20

No Ethernet cable or external USB-to-TTL module is used. J12 contains the
board's FT2232 USB-JTAG/UART bridge, so one data-capable Micro-USB cable carries
the 115200 8-N-1 serial link (and can also power/program the board).

### From microSD

1. Format a microSD card as FAT32 and copy `fpga/build/BOOT.BIN` to its root.
2. Insert it into J4 and place the JP5 mode jumper across the two pins labelled
   `SD` (the leftmost pair when reading the board label normally).
3. Connect J12 `PROG/UART` to the Mac with a Micro-USB data cable. If powering
   over USB, set JP6 to `USB`; otherwise select the external 5 V source.
4. Turn on the board. The blue `DONE` LED should light after configuration,
   and UART activity appears on LD10/LD11.
5. On macOS, locate the serial port with `ls /dev/cu.usbserial-*`. A charge-only
   cable will power the board but will not create this device.

### From QSPI (no microSD required)

The final BTN2 grid / BTN3 tap-tempo image was programmed to the Zybo's 16 MiB
Winbond QSPI and fully read-back verified on 2026-09-19. To reprogram it later,
use:

```bash
source /path/to/Vitis/2025.2/settings64.sh
program_flash -f fpga/build/BOOT.BIN -offset 0 \
  -flash_type qspi-x4-single \
  -fsbl fpga/build/vitis_workspace/deskband_platform/zynq_fsbl/build/fsbl.elf \
  -verify
```

After programming completes, turn the board **off**, move JP5 to the pair
labelled `QSPI`, and turn it back on. Never move JP5 while powered. The blue
`DONE` LED should light and UART should emit `READY DESKBAND 1.0`.

Current image SHA-256: `482c6c200a258fe6d55a2ddb43bcf579341402ace83fc039595c37aa7b82a427`
(4,213,904 bytes, PL ID `44420102`). This exact image was built and verified
in software, written to QSPI, and fully read-back verified on 2026-09-19.
Cold-boot smoke testing is still required.

Before starting DeskBand, verify the physical board path by itself:

```bash
.venv/bin/pip install pyserial
PYTHONPATH=. .venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

It checks the firmware/PL identity, 32 sequential events covering the full
opening bar and a mathematically generated second bar, an envelope endpoint,
and a moving LFO. It leaves the
transport stopped and restores track 0 to full level.

## Run with the Mac

```bash
.venv/bin/pip install pyserial
.venv/bin/python main.py
```

`main.py` (and `dist/DeskBand.app`) finds the board by itself: every two
seconds it sends `PING` to each `/dev/cu.usbserial-*` UART, skipping the
JTAG half of the FT2232 pair, and starts `tools/zybo_bridge.py` as a child
process on the port that answers `PONG`. If the board is unplugged, DeskBand
returns to its own clock and keeps looking, so the board can be connected at
any time. A dot beside the title shows the state at a glance (unlit, steady,
or beating once a bar while the board conducts), and the debug panel (`d`)
shows the link and which clock is running. Do not also run the bridge by
hand while DeskBand is open; two readers would split the serial stream.
Running it by hand is still useful without the app:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge mirrors the Mac's vision-selected tracks and BPM into the FPGA,
forwards FPGA events/control streams and `BAR` generation telemetry back to
DeskBand, and renews hardware mode. See [registers.md](docs/registers.md) for
the PS/PL contract.

At 100 MHz, `cycles_per_step = 100_000_000 * 60 / (BPM * 4)`. At 120 BPM,
this is `12_500_000` cycles.
