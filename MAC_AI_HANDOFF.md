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

The source, RTL simulations, full Vivado place-and-route, Vitis firmware build
and Bootgen packaging have been completed. The remaining task is deliberately
narrow: prove the real J12 UART link and listen to the complete Mac/Zybo loop,
then make only integration-level corrections if the evidence requires them.

What has **not** yet been run is the physical board smoke test or Mac audio test.
The development computer did not have the target Mac, its audio dependencies,
or the board's USB connection.

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
- Preview mode stops the FPGA transport. Entering show mode resets/starts it.
  This keeps BTN0, the spacebar and the onscreen shutter consistent.

## Verified implementation

Programmable logic at AXI base `0x43C00000` contains:

- 100 MHz programmable sixteenth-note clock and absolute tick counter;
- seven parallel 16-step pattern sequencers;
- step/beat/bar-quantized track-mask changes;
- 16-record timestamped event FIFO with sticky overflow reporting;
- four two-flop-synchronized, debounced buttons and four selector switches;
- seven Q8.16 level envelopes with exact final values;
- seven 24-bit triangle LFOs updated at 100 Hz; and
- AXI4-Lite registers, LEDs and status reporting.

The Zynq Cortex-A9 bare-metal firmware parses line-oriented UART commands,
drives those AXI registers, drains the event FIFO and emits `EV`, `CV` and
`BTN` records. The Mac bridge converts those records to localhost UDP commands
understood by DeskBand.

Full implementation results for `xc7z020clg400-1` at 100 MHz:

- setup WNS `+0.155 ns`, setup TNS `0`, zero failing endpoints;
- hold WHS `+0.028 ns`, hold THS `0`, zero failing endpoints;
- zero implementation DRC errors and zero unrouted nets;
- 2,744 slice LUTs (5.16%) and 2,136 registers (2.01%).

The official Digilent PS preset emits known negative DDR DQS-skew warnings.
They come from the board preset and did not cause timing or DRC failure.

## Important files

| Path | Purpose |
|---|---|
| `fpga/build/BOOT.BIN` | Prebuilt SD boot image: FSBL + final bitstream + firmware |
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
462e2e786c00ad9c306f376e03dcfd568be0a4c17298c3a1cc725c0ec6ea9d0e
```

It targets the **Zybo Z7-20**, not the Z7-10.

## Hardware and cabling

Required:

- Zybo Z7-20;
- FAT32 microSD card;
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
.venv/bin/python tools/zybo_smoke.py /dev/cu.usbserial-XXXXXXXX
```

Expected final output:

```
PASS: physical UART, PL ID, 16-step sequencer, envelope, and LFO
```

The test requires PL ID `44420100`, receives ticks/steps 0 through 15, checks
all default track-event masks, observes at least three LFO values, and requires
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
.venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The bridge sends `PING`, `RESET`, `STOP`, subscribes to DeskBand state, mirrors
integer BPM and the seven visible/photo-selected parts into hardware, then
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

Values 7–15 wrap modulo seven.

Physical controls:

- BTN0: preview → take photo, reset/start transport; show → retake, stop.
- BTN1: mute/unmute the selected track at the next beat boundary.
- BTN2: fade selected track to/from zero over 400 × 10 ms = 4 seconds.
- BTN3: toggle the selected track's hardware triangle-LFO modulation.
- LEDs: switches while stopped; low four bits of the step while running.

## Final acceptance checklist

Record the result of every item rather than changing several layers at once:

1. Board smoke test prints its exact PASS line.
2. In preview, music is silent and LEDs mirror the switches.
3. BTN0 takes one photo; within the fixed scheduling lookahead, the detected
   instruments begin and the LEDs count continuously through 16 steps.
4. Music continues looping without taking another photo.
5. Select an audible track and verify BTN1 changes it on a beat, not midway
   through an arbitrary step.
6. BTN2 audibly reaches silence/full scale after approximately four seconds.
7. BTN3 creates/removes periodic amplitude modulation on that track.
8. BTN0 retakes/stops; spacebar and onscreen shutter also start/stop correctly.
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
`TEMPO`, `CYCLES`, `MASK`, `PATTERN`, `ENV`, `LFO` and `LFOOFF`. Examples:

```
TEMPO 120
MASK 7F BEAT
ENV 2 0 400
LFO 2 051EB8 64
```

Board records:

```
EV tick step event_mask_hex active_mask_hex mask_changed
CV level0 ... level6 lfo0 ... lfo6
BTN live_hex pressed_hex released_hex switches_hex
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
