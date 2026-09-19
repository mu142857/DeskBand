# DeskBand FPGA conductor

The Zybo Z7-20 is the real-time conductor and effects controller. The Mac
still performs vision, composes pitches/chords, and renders samples, while the
Zynq owns musical time, seven-track sequencing, quantized controls, envelopes,
LFO modulation, and physical interaction.

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
- track-mask changes quantized to step, beat, or bar boundaries;
- a 16-entry timestamped event FIFO with sticky overflow detection;
- four synchronized/debounced buttons and a four-switch track selector;
- seven parallel Q8.16 level envelopes with exact endpoints;
- seven independent 24-bit triangle LFOs at a 100 Hz control rate;
- robust AXI4-Lite register interface at `0x43C00000`;
- official Zybo Z7-20 PS preset, UART1 on J12, and 100 MHz FCLK0;
- bare-metal Cortex-A9 UART command/event firmware; and
- Mac serial-to-UDP bridge plus sample-accurate engine scheduling.

The switches select a track in binary (`0` through `6`; 7–15 wrap modulo
seven):

| Button | Action |
|---|---|
| BTN0 | start/stop FPGA transport and toggle DeskBand photo/retake |
| BTN1 | mute/unmute selected track on the next beat |
| BTN2 | fade selected track to/from silence over 400 control updates |
| BTN3 | enable/disable the selected track's hardware triangle LFO |

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

The image was programmed to the Zybo's 16 MiB Winbond QSPI and read-back
verified on 2026-09-19. To reproduce the write while JP5 is in `JTAG` mode:

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

Before starting DeskBand, verify the physical board path by itself:

```bash
.venv/bin/pip install pyserial
PYTHONPATH=. .venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

It checks the firmware/PL identity, all 16 sequential hardware events and their
default track masks, an envelope endpoint, and a moving LFO. It leaves the
transport stopped and restores track 0 to full level.

## Run with the Mac

```bash
.venv/bin/pip install pyserial
.venv/bin/python main.py
.venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge mirrors the Mac's vision-selected tracks and BPM into the FPGA,
forwards FPGA events/control streams back to DeskBand, and renews hardware
mode. See [registers.md](docs/registers.md) for the PS/PL contract.

At 100 MHz, `cycles_per_step = 100_000_000 * 60 / (BPM * 4)`. At 120 BPM,
this is `12_500_000` cycles.
