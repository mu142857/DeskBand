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

The original conductor passed RTL simulation, full place-and-route, firmware
build, QSPI programming, and a physical Zybo smoke test. The current revision
adds automatic hardware bar generation and the performance control layer. Its
software/RTL tests, place-and-route, firmware, and BOOT.BIN build are complete,
but the new image has not yet been flashed or physically smoke-tested. Do not
mistake the older image currently in QSPI for this revision.
The Mac-side task remains to run the board smoke test, then listen to the full
Mac/Zybo audio loop and make only evidence-driven integration corrections.

The earlier physical test passed bidirectional UART, PL ID, 16 sequential timing
events and their masks, an envelope endpoint and a moving LFO. The complete
Mac audio test has not yet run because the development computer did not have
the target Mac, its audio dependencies or sample library.

## Mac quick start — follow this first

Use the `fpga-conductor` branch, not `main`. Commit `1d86a94` is the minimum
required version; later commits on that branch include documentation updates.

For a new checkout:

```bash
git clone --branch fpga-conductor https://github.com/mu142857/DeskBand.git
cd DeskBand
```

For an existing checkout:

```bash
cd /path/to/DeskBand
git fetch origin
git switch fpga-conductor
git pull --ff-only origin fpga-conductor
git merge-base --is-ancestor 1d86a94 HEAD
```

The last command must exit successfully. Do not merge this work into `main`
during bring-up.

The Mac requires Python 3.11, a webcam, and the Logic Pro or GarageBand sound
library. Create the environment and install both application and UART
dependencies:

```bash
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m venv .venv
.venv/bin/pip install ultralytics opencv-python sounddevice soundfile numpy scipy certifi pillow pyserial
```

The first application run downloads YOLO-World and CLIP weights. Internet is
needed for that first run, and macOS must be allowed to use the camera and
audio output.

The current Zybo has already been programmed. With power off, put JP5 on the
pair labelled `QSPI`; put JP6 on `USB` if J12 supplies power. Connect J12
`PROG/UART` to the Mac using a data-capable Micro-USB cable, power on and check
that the blue `DONE` LED lights. No SD card, Ethernet, Vivado, Vitis or external
TTL-UART adapter is needed on the Mac.

Discover the serial devices:

```bash
ls /dev/cu.usbserial-*
```

The UART is normally the FTDI `B` channel. If two ports appear and the suffix
is not clear, run the smoke test against each; the UART port is the one that
returns `PONG` and ID `44420101`.

From the repository root, prove the board before starting DeskBand:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

It must finish with:

```text
PASS: UART, PL ID, generated bars, sequencer, envelope, and LFO
```

Then open two terminals in the repository. Terminal A runs vision and audio:

```bash
.venv/bin/python main.py
```

Wait for the camera, sampler, and `[remote] listening on ...:9000` message.
Terminal B connects the FPGA:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge should report the serial device at 115200 baud and DeskBand UDP
port 9000. Press Zybo BTN0, the spacebar or the onscreen shutter once to take a
photo. The detected instruments must then loop continuously without taking
more photos. Press BTN0 again to return to the camera (the music keeps
playing). Use `p` or the on-screen button to pause and resume; mixer-mode BTN1
mutes the selected track, and performance-mode BTN1 locks its generated rhythm.

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
- step/beat/bar-quantized track-mask changes;
- 16-record timestamped event FIFO with sticky overflow reporting;
- four two-flop-synchronized, debounced buttons and four selector switches;
- seven Q8.16 level envelopes with exact final values;
- seven 24-bit triangle LFOs updated at 100 Hz; and
- AXI4-Lite registers, LEDs and status reporting.

Bar zero plays the Mac's base patterns exactly. Each later bar is generated
automatically: hardware chooses half, three-quarter, or full density and an
LFSR-derived phase, then distributes retained events across only valid base
hits. It protects downbeats, keeps bass/strings stable, and commits all changes
at a bar edge. Firmware emits `BAR` telemetry and the bridge displays it in the
debug overlay.

The Zynq Cortex-A9 bare-metal firmware parses line-oriented UART commands,
drives those AXI registers, drains the event FIFO and emits `EV`, `CV` and
`BTN` records. The Mac bridge converts those records to localhost UDP commands
understood by DeskBand.

Full implementation results for `xc7z020clg400-1` at 100 MHz:

- setup WNS `+0.116 ns`, setup TNS `0`, zero failing endpoints;
- hold WHS `+0.039 ns`, hold THS `0`, zero failing endpoints;
- zero implementation DRC errors and zero unrouted nets;
- 3,203 slice LUTs (6.02%) and 2,319 registers (2.18%).

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
7c45b9c5c9ed8483f13b09867c2b388ea42623f7445737145fd5866e097bd5da
```

It targets the **Zybo Z7-20**, not the Z7-10.

## Hardware and cabling

Required:

- Zybo Z7-20;
- FAT32 microSD card, unless using the already-programmed onboard QSPI;
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

The board's QSPI was programmed and fully read-back verified with the previous
image on 2026-09-19. Reprogram the current 4,213,968-byte `BOOT.BIN` before
testing PL ID `44420101`. With the board powered off, move JP5 to `JTAG` for
programming, then back to `QSPI` for cold boot. Never move JP5 while powered.
See `fpga/README.md` for the exact command.

## Mac preparation

Use the existing project `.venv` if it is already configured. Otherwise follow
the top-level `README.md`; the full application needs its existing vision/audio
packages and Apple Logic/GarageBand sample library. Add only `pyserial`:

```bash
.venv/bin/pip install pyserial
```

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

The test requires PL ID `44420101`, receives 32 events (the exact opening bar
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

Terminal A:

```bash
.venv/bin/python main.py
```

Wait for camera, sampler and `[remote] listening on udp://...:9000` startup.

Terminal B:

```bash
PYTHONPATH=. .venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge sends `PING`, `RESET`, `STOP`, subscribes to DeskBand state, mirrors
integer BPM and the seven hardware-backed shelf-selected parts into hardware, then
forwards events and continuous controls. It renews FPGA mode every four seconds
without disturbing the event timeline.

Track selector mapping (switch value interpreted as binary):

| Value | Object / track |
|---:|---|
| 0 | cup / piano |
| 1 | pen / guitar |
| 2 | bottle / bass |
| 3 | book / drums |
| 4 | glasses / strings |
| 5 | cell phone / glockenspiel |
| 6 | laptop / soft keys |

SW2:SW0 value 7 wraps to track zero. SW3 selects mixer/performance mode and is
not part of the track number.

Physical controls (SW2:SW0 select track 0–6; value 7 wraps to zero):

- BTN0: DeskBand shutter. Preview → take photo (its objects join the band);
  show → back to the camera. The music keeps playing either way.
- SW3=0 mixer mode: BTN1 mute/unmute the selected track at the next beat,
  BTN2 fade over four seconds, BTN3 toggle the hardware triangle LFO.
- SW3=1 performance mode: BTN1 lock/unlock the selected generated rhythm at
  the next bar, BTN2 queue the next energy state (sparse/normal/full), BTN3
  queue one full-density fill bar, after which automatic generation resumes.
- DeskBand's `p` key, on-screen button, and remote `play` command still pause
  and resume the whole band. For the older hardware BTN1 master play/pause
  mapping, start the bridge with `--btn1-master` (mixer mode only).
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
5. With SW3=0, verify BTN1 quantized track mute, BTN2 four-second fade, and
   BTN3 LFO. Verify `p` or the on-screen button pauses/resumes the entire band.
6. With SW3=1, verify BTN1 freezes/unfreezes one track only at a bar edge.
7. Verify BTN2 cycles sparse/normal/full on bar edges and BTN3 produces exactly
   one full-density fill before generated bars resume.
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

The FPGA engine test was written and syntax-checked on the development host but
could not execute there because that host lacked NumPy, SciPy, sounddevice and
the Mac audio environment. It is therefore a required Mac-side gate.

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
BAR index energy locked_mask_hex fill_active fill_pending enabled random_hex
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
- Preserve `main` and continue work only on the feature branch.

When all ten acceptance checks pass, update this file and `HANDOFF.md` with the
actual Mac model, serial-device name, audio device, observed latency/lookahead,
test duration and any integration change made.
