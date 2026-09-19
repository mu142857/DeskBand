# DeskBand

> Put the things on your desk in front of the camera, shoot a photo, and they become a band that never plays out of tune.

Built at **Hack the North 2026** by Aaron Shangguan, Richard Cai and Hank Lee.

## What it does

DeskBand looks at a photo of your desk and turns every object it recognises into a member of a band. A laptop, a cup, a pen, a bottle, a book, a pair of glasses, a phone: each one has its own instrument, and whatever combination you shoot, the result is always in tune and always on the beat.

| Object | Instrument | Role |
|---|---|---|
| cup (or mug) | Concert Grand Piano, soft layer | rolled chords and a sparse melody |
| pen (pencil, marker) | Classical Guitar | fingerpicked chord tones |
| bottle | Double Bass, pizzicato | chord roots |
| book (notebook) | Trap Heat drum machine, played quietly | kick, rim, hats |
| glasses | King's Cross (Studio Strings ensemble) | sustained chords |
| cell phone | Glockenspiel | high sparkle |
| laptop or tablet | Soft FM electric piano (synthesised) | dotted-8th shimmer an octave up |

An empty desk is silent: the band is exactly what you photographed, played through a hall reverb. (An optional backing bed of vinyl noise, shaker and sub bass can be switched on in `deskband/config.py`.)

The exact sample files behind each instrument are listed in [INSTRUMENTS.txt](INSTRUMENTS.txt).

> Team members picking this up: read [HANDOFF.md](HANDOFF.md) first (in Chinese). It covers the exact environment, architecture, music design, detection trade-offs, the remote-control protocol for hardware and AI integrations, troubleshooting and the open issues.

## How it works

- **Vision:** YOLO-World (`ultralytics`) with the object names given as text prompts, so classes that are not in COCO (pen, glasses, tablet) work without training; each instrument accepts several synonyms. The large model runs on Apple Silicon via `mps` in its own thread at 960 px while a separate capture thread keeps the preview smooth, and the frozen photo gets one more pass at full resolution.
- **Music:** a fixed loop of four close voicings, one bar each at 120 BPM: `F A C E` → `G B D E` → `E G B D` → `E A B C`. They move by step and keep common tones, which gives the hovering, blurred harmony. The bass always plays the chord root (F, G, E, A). The piano rolls each voicing softly and lets it ring into the next bar, then adds a sparse line on top: one motif per trip round the loop, restated over each chord. Melodic notes come only from the C major pentatonic scale, which fits all four chords, so random choices always sound right. The rhythm skeleton is a 3-3-2 accent pattern (the quantise-everything idea is Mikutap's). Everything lands on a 16th-note grid.
- **Audio:** a small engine on top of `sounddevice`. Real instruments are sample-based (Logic Pro / GarageBand factory content read in place from the Mac), the synth parts are generated, and everything runs through a long Schroeder hall reverb. The engine runs at the output device's own sample rate, and the master bus uses a gain-riding limiter rather than clipping. The audio callback never blocks on vision; a slow frame only delays the picture.
- **Remote port:** JSON over UDP (port 9000) so a badge, an FPGA board or another program can take the photo, force parts on and off, change tempo and chords, play a sound in time, and subscribe to the beat. `tools/remote_sim.py` is a dependency-free simulator of it. Protocol in [HANDOFF.md](HANDOFF.md) section 10.
- **UI:** one window. Desaturated duotone image, colour kept inside detected objects, thin rounded outlines, SF Pro labels, a frosted card listing the band, and a shutter button. Press `space` (or click the shutter) to shoot, `space` again to retake.

## Requirements

- Apple Silicon Mac with Logic Pro or GarageBand sound library installed (the samples are read from `/Library/Application Support/Logic` and `/Library/Application Support/GarageBand`).
- Python 3.11 (`/Library/Frameworks/Python.framework/Versions/3.11`).
- A webcam.

## Setup

```bash
cd ~/Desktop/DeskBand
/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 -m venv .venv
.venv/bin/pip install ultralytics opencv-python sounddevice soundfile numpy scipy certifi pillow
```

The first run downloads the YOLO-World weights (`yolov8l-worldv2.pt`, ~90 MB; the 25 MB `yolov8s-worldv2.pt` is used if the large one is missing) and the CLIP text encoder (~340 MB), and macOS asks for camera access.

Optional but recommended, the two sounds the piece is written for (both are unpacked from Logic's library into `cache/`, which is not in the repo; without them the Yamaha Grand and Pop Strings sets are used):

```bash
.venv/bin/python tools/exs_extract.py "/Library/Application Support/Logic/Sampler Instruments/z_Internal/Studio Piano/Concert Grand Piano.exs" "/Library/Application Support/Logic/EXS Factory Samples/Studio Piano/Concert Grand Piano" cache/concert_grand_soft --velocity 45 --max-seconds 8
```

```bash
.venv/bin/python tools/make_kings_cross.py
```

## Run

```bash
.venv/bin/python main.py
```

Keys: `space` shoot / retake · `s` save the live frame to `cache/shots/` · `d` debug overlay · `f` fullscreen · `q` quit.

To get a double-clickable app:

```bash
tools/build_app.sh
```

which writes `dist/DeskBand.app`: a small native launcher (`tools/launcher.c`) that runs the project with its own `.venv`. It has to be native so macOS attributes the camera permission to DeskBand.

## Tools

- `tools/render_demo.py out.wav` renders the whole band offline, one instrument entering per phrase. Useful for tuning the music without a camera.
- `tools/check_pitch.py` measures the pitch of every sample and compares it with the note in the file name.
- `tools/write_instruments_txt.py` regenerates `INSTRUMENTS.txt` from `deskband/config.py`.
- `tools/exs_extract.py` unpacks a Logic "consolidated" EXS instrument (such as the Concert Grand Piano) into per-note WAVs the sampler can use.
- `tools/eval_prompts.py` replays the saved photos through the detector with any prompts, threshold, size or model.
- `tools/make_kings_cross.py` builds the King's Cross string ensemble (five sections layered) into `cache/kings_cross/`.
- `tests/` checks the reverb against a per-sample reference and the sample player for exactness: `.venv/bin/python tests/test_reverb.py`.

## Project layout

```
main.py                app, states (preview / show), drawing
deskband/config.py     tempo, chords, instrument table, sample paths
deskband/vision.py     camera + YOLO-World thread
deskband/music.py      composer: patterns per instrument
deskband/synth.py      audio engine, voices, sequencer
deskband/sampler.py    sample loading and key maps
deskband/fx.py         hall reverb
deskband/ui.py         drawing primitives (duotone, outlines, text, cards)
deskband/remote.py     UDP/JSON remote-control port
styles/                example chord loops for the remote "style" command
tools/                 demo renderer, checks, packaging
```

## Notes

All code was written during the hackathon. Sounds come from Apple's Logic Pro / GarageBand factory library on the local machine and are never copied into this repository.
