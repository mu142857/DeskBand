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
- automatic per-bar variation from a 16-bit maximal LFSR and seven parallel
  divider-free Euclidean/Bresenham phase accumulators;
- track-mask changes quantized to step, beat, or bar boundaries;
- a 16-entry timestamped event FIFO with sticky overflow detection;
- four synchronized/debounced buttons and a four-switch track selector;
- seven parallel Q8.16 level envelopes with exact endpoints;
- seven independent 24-bit triangle LFOs at a 100 Hz control rate;
- robust AXI4-Lite register interface at `0x43C00000`;
- official Zybo Z7-20 PS preset, UART1 on J12, and 100 MHz FCLK0;
- bare-metal Cortex-A9 UART command/event firmware; and
- Mac serial-to-UDP bridge plus sample-accurate engine scheduling.

SW3 chooses the control layer. SW2:SW0 select a track in binary (`0` through
`6`; `7` wraps to track zero):

| Button | SW3=0: mixer | SW3=1: generative performance |
|---|---|---|
| BTN0 | DeskBand shutter: photo/retake | DeskBand shutter: photo/retake |
| BTN1 | mute selected track on next beat | lock/unlock its generated rhythm on next bar |
| BTN2 | four-second hardware fade | next-bar energy: sparse → normal → full |
| BTN3 | toggle hardware triangle LFO | queue one full-density fill bar |

Automatic variation is the default base behavior; no button press is needed.
The FPGA advances a repeatable 16-bit LFSR once per bar and uses parallel
modulo-four phase accumulators to keep an evenly spaced half, three quarters,
or all of each track's valid base hits. It never creates a hit where the Mac's
pattern has none, always preserves a step-zero downbeat, and leaves bass and
strings stable. Every performance action commits exactly at a bar edge.

The bridge sends BTN0 to DeskBand as the shutter. The shelf owns the band, so
retaking a photo leaves music running in preview. The bridge holds mixer-mode
BTN1 mutes across later shelf changes; app play/pause stays available through
`p`, the on-screen button, and the remote `play` command. To use the earlier
hardware BTN1 play/pause mapping, launch `tools/zybo_bridge.py --btn1-master`
in mixer mode; performance-mode BTN1 still locks the generated rhythm.

Firmware reports BTN0 and mixer BTN1 without changing transport or masks
locally. The bridge owns those actions, so taking another photo cannot restart
the musical clock and a mute cannot be applied twice. The transport runs when
an unmuted selected track sounds and stops when the band is paused, empty, or
fully muted.

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

The current automatic-bar image was programmed to the Zybo's 16 MiB Winbond
QSPI and fully read-back verified on 2026-09-19. Reprogram it only when the
image changes, with JP5 in `JTAG` mode:

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

Current image SHA-256: `ce1deea16831f150d23fe3474cb592255ed635bae3fedbe1043449fa6cbd0685`
(4,213,904 bytes, PL ID `44420101`).

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
seconds it sends `PING` to each `/dev/cu.usbserial-*` UART, skipping the JTAG
half of the FT2232 pair, and starts `tools/zybo_bridge.py` as a child process
on the port that answers `PONG`. If the board is unplugged, DeskBand returns to
its own clock and keeps looking, so the board can be connected at any time. The
debug panel (`d`) shows the link and which clock is running. Do not also run
the bridge by hand while DeskBand is open; two readers would split the serial
stream. Running it by hand is still useful without the app:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge mirrors the Mac's vision-selected tracks and BPM into the FPGA,
forwards FPGA events/control streams and `BAR` generation telemetry back to
DeskBand, and renews hardware mode. See [registers.md](docs/registers.md) for
the PS/PL contract.

At 100 MHz, `cycles_per_step = 100_000_000 * 60 / (BPM * 4)`. At 120 BPM,
this is `12_500_000` cycles.
