# DeskBand Zybo handoff for the Mac-side AI

Read this file first. It is the source of truth for finishing the physical
DeskBand demo on a Mac with Hank's Zybo Z7-20. Do not redesign the architecture
until the baseline acceptance procedure below has been run.

## Mission and current boundary

DeskBand turns one camera photo into a continuously playing band. The Mac owns
camera vision, composition, sample loading and audio synthesis. The Zybo owns
the real-time musical clock, seven-track sequencing, quantized physical
controls, envelopes and LFOs. It sends timestamped events/control values back
to the Mac, which schedules them at exact audio-sample offsets with two
sixteenth notes of lookahead.

The current source revision includes automatic hardware rhythm generation,
eighth-only/mixed-grid switching, four-tap hardware tempo, and compatibility
with the shelf/stage software. The previous image was programmed into QSPI and
read-back verified on 2026-09-19. The new image identified below has not yet
been flashed; Hank must program it once before Mac testing.
The Mac-side task is to run that smoke test, then listen to the full Mac/Zybo
audio loop and make only evidence-driven integration corrections.

The earlier physical test passed bidirectional UART, PL ID, 16 sequential timing
events and their masks, an envelope endpoint and a moving LFO. The complete
Mac audio test has not yet run because the development computer did not have
the target Mac, its audio dependencies or sample library.

## Mac quick start — follow this first

Use `main` at commit `790ae22` or later. The FPGA work and its compatibility
fixes have been merged there. The checked-in boot image must have the SHA-256
listed below.

For a new checkout:

```bash
git clone https://github.com/mu142857/DeskBand.git
cd DeskBand
```

For an existing checkout:

```bash
cd /path/to/DeskBand
git fetch origin
git switch main
git pull --ff-only origin main
git merge-base --is-ancestor 790ae22 HEAD
```

The last command must exit successfully.

The Mac requires Python 3.11, a webcam, and the Logic Pro or GarageBand sound
library. Create the environment and install both application and UART
dependencies:

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The first application run downloads YOLO-World and CLIP weights. Internet is
needed for that first run, and macOS must be allowed to use the camera and
audio output.

Do not assume the current QSPI contents are compatible. First have Hank program
the checked-in `BOOT.BIN` using the QSPI procedure below and confirm its smoke
test. Then, with power off, put JP5 on the pair labelled `QSPI`; put JP6 on
`USB` if J12 supplies power. Connect J12
`PROG/UART` to the Mac using a data-capable Micro-USB cable, power on and check
that the blue `DONE` LED lights. No SD card, Ethernet, Vivado, Vitis or external
TTL-UART adapter is needed on the Mac.

Discover the serial devices:

```bash
ls /dev/cu.usbserial-*
```

The UART is normally the FTDI `B` channel. If two ports appear and the suffix
is not clear, run the smoke test against each; the UART port is the one that
returns `PONG` and ID `44420102`.

From the repository root, prove the board before starting DeskBand:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

It must finish with:

```text
PASS: UART, PL ID, generated bars, sequencer, envelope, and LFO
```

Start vision and audio:

```bash
.venv/bin/python main.py
```

DeskBand automatically scans the FTDI ports, probes for `PONG DB01`, and starts
the bridge as a child process. Wait for `[remote] listening on ...:9000`, then
for `[zybo] board found on ...` and `connected` in the debug overlay. Only if
automatic detection fails, run the bridge manually in a second terminal:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge reports the serial device at 115200 baud and DeskBand UDP port
9000. Press Zybo BTN0, the spacebar or the onscreen shutter once to take a
photo. The detected instruments must then loop continuously without taking
more photos. Press BTN0 again to return to the camera (the music keeps
playing). Use `p` or the on-screen button to pause and resume. BTN1 toggles
Math melody mode, BTN2 toggles the FPGA rhythm grid on the next bar, and four
BTN3 taps set BPM.

## Do not change these architectural decisions

- The FPGA is the timing authority. Do not fall back to the Mac's internal
  sequencer while claiming an FPGA-driven demo.
- The Mac synthesizes audio. Raw audio is not streamed through the FPGA.
- This is a UART design, not an Ethernet design.
- The normal demo takes one photo, then music loops continuously until retake.
  Continuous camera re-detection is a later enhancement and does not require an
  FPGA architecture change.
- The Mac bridge's repeated `fpga_mode` keepalive must remain idempotent. It
  must not clear queued hardware events every four seconds.
- The transport follows the band, not the photo mode. DeskBand keeps shot
  instruments on a shelf and the band plays in preview as well, so the bridge
  resets/starts the transport when the first track starts sounding and stops it
  when the band is paused (`play` command, `p`) or empty. The engine
  re-anchors its tick-to-sample mapping whenever ticks restart or arrive late,
  so every restart keeps the scheduling lookahead.

## Verified implementation

Programmable logic at AXI base `0x43C00000` contains:

- 100 MHz programmable sixteenth-note clock and absolute tick counter;
- seven parallel 16-step pattern sequencers;
- a maximal-length 16-bit LFSR and seven parallel divider-free
  Euclidean/Bresenham bar generators;
- eighth-only/mixed eighth-and-sixteenth rhythm grids and a 100 MHz four-tap
  tempo analyzer;
- step/beat/bar-quantized track-mask changes;
- 16-record timestamped event FIFO with sticky overflow reporting;
- four two-flop-synchronized, debounced buttons and four selector switches;
- seven Q8.16 level envelopes with exact final values;
- seven 24-bit triangle LFOs updated at 100 Hz; and
- AXI4-Lite registers, LEDs and status reporting.

Bar zero plays the Mac's base patterns exactly. Each later bar is generated
automatically: hardware chooses a musically bounded density and LFSR-derived
phase, then places onsets on safe eighth/sixteenth grids. These grids are wider
than the written patterns, so hardware can add rhythmic notes; the Mac maps new
onsets to nearby chord-safe pitches or quiet hi-hats. It protects downbeats,
keeps bass/strings stable, and commits BTN2 grid changes at a bar edge.

The Zynq Cortex-A9 bare-metal firmware parses line-oriented UART commands,
drives those AXI registers, drains the event FIFO and emits `EV`, `CV` and
`BTN` records. The Mac bridge converts those records to localhost UDP commands
understood by DeskBand.

Full implementation results for `xc7z020clg400-1` at 100 MHz:

- setup WNS `+0.032 ns`, setup TNS `0`, zero failing endpoints;
- hold WHS `+0.028 ns`, hold THS `0`, zero failing endpoints;
- zero implementation DRC errors and zero unrouted nets;
- 3,128 slice LUTs (5.88%) and 2,397 registers (2.25%).

The official Digilent PS preset emits known negative DDR DQS-skew warnings.
They come from the board preset and did not cause timing or DRC failure.

## Important files

| Path | Purpose |
|---|---|
| `fpga/build/BOOT.BIN` | Prebuilt SD/QSPI boot image: FSBL + final bitstream + firmware |
| `fpga/README.md` | Build, boot, physical test and run instructions |
| `fpga/docs/registers.md` | Exact PS/PL register contract |
| `fpga/rtl/` | Timing core, AXI peripheral, debounce, envelope and LFO RTL |
| `fpga/ps/src/` | Bare-metal Cortex-A9 firmware |
| `deskband/fpga_protocol.py` | Dependency-free UART codec |
| `tools/zybo_smoke.py` | Board-only physical acceptance test |
| `tools/zybo_bridge.py` | Production UART-to-DeskBand bridge |
| `tests/test_fpga_engine.py` | Mac audio lookahead/gating regression test |
| `tests/test_fpga_protocol.py` | Mac/firmware protocol codec test |

The checked-in `BOOT.BIN` is intentionally the only generated board artifact
to distribute. Other files below `fpga/build/` remain ignored and reproducible.
Its expected SHA-256 is:

```
482c6c200a258fe6d55a2ddb43bcf579341402ace83fc039595c37aa7b82a427
```

It targets the **Zybo Z7-20**, not the Z7-10.

## Hardware and cabling

Required:

- Zybo Z7-20;
- FAT32 microSD card, unless Hank programs the onboard QSPI first;
- data-capable Micro-USB cable from the Mac to J12 `PROG/UART`;
- USB-C adapter if the Mac has no USB-A port; and
- Mac speakers, wired speakers or headphones for the first test.

Do not buy or wire a TTL UART dongle. J12 already connects an FTDI FT2232HQ
USB-UART bridge to Zynq UART1 on MIO48/MIO49. Ethernet is unused. Digilent's
official manual is:
https://digilent.com/reference/_media/reference/programmable-logic/zybo-z7/zybo-z7_rm.pdf

For SD boot:

1. Copy `fpga/build/BOOT.BIN` to the root of a FAT32 microSD card with the exact
   filename `BOOT.BIN`.
2. Insert the card into J4.
3. Put JP5 across the leftmost pair labelled `SD`.
4. For USB power, put JP6 in `USB`; otherwise select the external 5 V source.
5. Connect J12 and turn on the board. The blue `DONE` LED should illuminate.
6. On macOS, run `ls /dev/cu.usbserial-*`. If there is no device, first suspect
   a charge-only cable. UART traffic also flashes LD10/LD11.

Hank programmed and read-back verified an older image in the board's 16 MiB
Winbond QSPI on 2026-09-19. It does not contain this final BTN2/BTN3 behavior.
Program the current 4,213,904-byte image with the command below; only after it
passes verification should the powered-off board be moved from `JTAG` to
`QSPI`. Never move JP5 while powered.

On Hank's Vivado/Vitis laptop, attach J12 to WSL, leave JP5 on `JTAG`, and run
from the repository root:

```bash
source /home/leech/Xilinx/2025.2/Vitis/settings64.sh
program_flash -f fpga/build/BOOT.BIN -offset 0 \
  -flash_type qspi-x4-single \
  -fsbl fpga/build/vitis_workspace/deskband_platform/zynq_fsbl/build/fsbl.elf \
  -verify
```

After `Program/Verify Operation successful`, turn the board off, move JP5 to
`QSPI`, and power it back on. The Mac only needs J12 after that; it does not
need Vivado, Vitis, an SD card, or Ethernet.

## Mac preparation

Use the existing project `.venv` if it is already configured. Otherwise follow
the top-level `README.md`; `requirements.txt` includes the vision/audio packages
and `pyserial`. The sample library still comes from Apple Logic/GarageBand.

The repo intentionally does not include model weights, Logic samples or camera
captures. Missing sample libraries can make individual instruments silent even
when FPGA integration is correct, so inspect the application's `[sampler]`
startup lines before blaming UART.

## Phase 1: prove the board without DeskBand

Do this before opening the camera or audio application:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

Expected final output:

```
PASS: UART, PL ID, generated bars, sequencer, envelope, and LFO
```

The test requires PL ID `44420102`, receives 32 events (the exact opening bar
plus a generated second bar), checks their track masks against a host mirror of
the LFSR/math, observes at least three LFO values, and requires
the track-0 envelope to reach zero. Its `finally` block disables that LFO,
restores track 0 to level 255 and stops transport.

Failure isolation:

- No `/dev/cu.usbserial-*`: cable/adapter/driver/J12 problem, not RTL.
- Port opens but no `PONG`: board did not boot firmware, wrong port, or wrong
  baud. It must be 115200 8-N-1.
- `FATAL PL_ID`: firmware and bitstream do not match; recopy the supplied image.
- Correct ID but missing/wrong `EV`: PL/AXI or stale boot image; save raw UART.
- Sequencer passes but LFO/envelope fails: save all `CV` and command-response
  lines before modifying code.

## Phase 2: run the complete demo

Normally, run only:

```bash
.venv/bin/python main.py
```

Wait for camera, sampler, remote port, and automatic Zybo detection. Manual
fallback only:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge sends `PING`, `RESET`, `STOP`, subscribes to DeskBand state, mirrors
integer BPM and the seven hardware-backed shelf-selected parts into hardware, then
forwards events and continuous controls. It renews FPGA mode every four seconds
without disturbing the event timeline.

The four switches no longer change the button layer. While transport is
stopped the LEDs mirror them, which is useful as an input/LED sanity check.

Physical controls:

- BTN0: DeskBand shutter. Preview → take photo (its objects join the band);
  show → back to the camera. The music keeps playing either way.
- BTN1: toggle the Mac's Math melody mode; the melodic change begins on the
  next bar because composition is bar-planned.
- BTN2: toggle the FPGA generator between mixed 8th/16th and eighth-only
  onsets; the queued change commits on the next bar.
- BTN3: tap exactly four times at the desired quarter-note pulse. The FPGA
  averages the three intervals, clamps to 60–180 BPM, changes its clock, and
  sends the BPM to the Mac audio scheduler.
- DeskBand's `p` key, on-screen button, and remote `play` command pause and
  resume the whole band.
- LEDs: switches while stopped; low four bits of the step while running.

## Final acceptance checklist

Record the result of every item rather than changing several layers at once:

1. Board smoke test prints its exact PASS line.
2. With an empty shelf (or everything deselected with `0`), music is silent and
   the LEDs mirror the switches.
3. BTN0 takes one photo; within the fixed scheduling lookahead, the detected
   instruments begin and the LEDs count continuously through 16 steps.
4. BTN0 again returns to the camera and the music keeps looping; a second photo
   of another object adds it to the band.
5. Verify BTN1 toggles `math on/off` and takes musical effect at the next bar.
6. Press BTN2 and verify the overlay changes from `8th+16th` to `8th` at the
   next bar; press again and verify mixed timing returns.
7. Tap BTN3 four times at a steady pulse and verify the terminal reports the
   measured BPM, both FPGA and Mac adopt it, and the music remains aligned.
8. Spacebar and the on-screen shutter behave like BTN0; music continues after
   retaking the photo.
9. Change BPM through the existing remote/UI path and verify board events and
   Mac audio remain aligned after the resynchronization.
10. Run for at least ten minutes: no `ERR FIFO_OVERFLOW`, no growing drift, no
    four-second discontinuity, and the debug overlay should keep `xruns` at 0.

If USB scheduling is unusually jittery but all logic is correct, increase the
bridge `--lookahead` from 2 to 3 before changing RTL. This increases startup
latency by one sixteenth note but preserves deterministic FPGA event spacing.

## Automated regression commands

On any Linux development host with Verilator and a C compiler:

```bash
make -C fpga test lint ps-test
python3 tests/test_fpga_protocol.py
```

On the fully configured Mac:

```bash
.venv/bin/python tests/test_fpga_protocol.py
.venv/bin/python tests/test_fpga_engine.py
.venv/bin/python tests/test_reverb.py
.venv/bin/python tests/test_voice.py
.venv/bin/python tests/test_remote.py
```

All 22 repository software tests passed on the development host using a
test-only audio-device shim. The Mac must still rerun the listed tests against
its real NumPy/SciPy/sounddevice environment and audio hardware.

## UART protocol quick reference

Mac/host commands include `PING`, `ID`, `START`, `STOP`, `RESET`, `STATUS`,
`TEMPO`, `CYCLES`, `MASK`, `PATTERN`, `ENV`, `LFO`, `LFOOFF`, and
`VARIATION`. Examples:

```
TEMPO 120
MASK 7F BEAT
ENV 2 0 400
LFO 2 051EB8 64
VARIATION ON
```

Board records:

```
EV tick step event_mask_hex active_mask_hex mask_changed
CV level0 ... level6 lfo0 ... lfo6
BTN live_hex pressed_hex released_hex switches_hex
BAR index energy locked_mask_hex fill_active fill_pending enabled random_hex eighth_only eighth_pending
TAP bpm
```

Do not parse these ad hoc; use `deskband/fpga_protocol.py`.

## If a change is necessary

Keep the failure localized:

- If `zybo_smoke.py` fails, do not modify the audio engine.
- If it passes but the bridge shows malformed UART, save raw lines and inspect
  `fpga_protocol.py` plus firmware formatting.
- If events reach DeskBand but audio timing is wrong, inspect
  `tests/test_fpga_engine.py`, the two-step origin, BPM resynchronization and
  callback offsets before touching RTL.
- If audio timing is correct but a control sounds weak/strong, tune only the
  envelope/LFO mapping after recording the received `CV` values.
- If a code change is required, create a new feature branch from `main`; do not
  make emergency edits directly on `main` during bring-up.

When all ten acceptance checks pass, update this file and `HANDOFF.md` with the
actual Mac model, serial-device name, audio device, observed latency/lookahead,
test duration and any integration change made.
