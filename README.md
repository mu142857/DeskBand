# DeskBand

> Put the things on your desk in front of the camera, shoot a photo, and they become a band that never plays out of tune.

Built at **Hack the North 2026** by Aaron Shangguan, Richard Cai and Hank Lee.

## What it does

DeskBand looks at a photo of your desk and turns every object it recognises into a member of a band. A laptop, a cup, a pen, a bottle, a book, a lamp, a phone: each one has its own instrument, and whatever combination you shoot, the result is always in tune and always on the beat.

| Object | Instrument | Role |
|---|---|---|
| cup | Grand Piano | melody |
| pen | Classical Guitar | fingerpicked chords |
| bottle | Double Bass | bass line |
| book | Trap Heat Drums | drums |
| lamp | Strings | sustained pad |
| cell phone | Glockenspiel | high sparkle |
| laptop | Synth Arp | 16th-note arpeggio |

An empty desk is silent: the band is exactly what you photographed, played through a hall reverb. (An optional backing bed of vinyl noise, shaker and sub bass can be switched on in `deskband/config.py`.)

The exact sample files behind each instrument are listed in [INSTRUMENTS.txt](INSTRUMENTS.txt).

## How it works

- **Vision:** YOLO-World (`ultralytics`) with the object names given as text prompts, so classes that are not in COCO (pen, lamp) work without training. Runs on Apple Silicon via `mps` in its own thread.
- **Music:** a fixed chord loop (Fmaj7 – G – Em – Am, two bars each) at 120 BPM. The bass, the guitar's low string and the bottom voice of the strings always play the chord root; the piano invents one motif per trip round the loop and restates it over each chord. Melodic parts only pick notes from the C major pentatonic scale, which fits every chord in the loop, so random choices always sound right. The rhythm skeleton is the 3-3-3-3-2-2 accent pattern borrowed from Mikutap. Everything is quantised to a 16th-note grid.
- **Audio:** a small engine on top of `sounddevice`. Real instruments are sample-based (Logic Pro / GarageBand factory content read in place from the Mac), the synth parts are generated, and everything runs through a Schroeder hall reverb. The audio callback never blocks on vision; a slow frame only delays the picture.
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

The first run downloads the YOLO-World weights (~25 MB) and the CLIP text encoder (~340 MB), and macOS asks for camera access.

Optional, for the better piano: unpack Logic's Concert Grand once (88 MB into `cache/`, read by the sampler automatically; without it the Yamaha Grand set is used):

```bash
.venv/bin/python tools/exs_extract.py "/Library/Application Support/Logic/Sampler Instruments/z_Internal/Studio Piano/Concert Grand Piano.exs" "/Library/Application Support/Logic/EXS Factory Samples/Studio Piano/Concert Grand Piano" cache/concert_grand --velocity 84
```

## Run

```bash
.venv/bin/python main.py
```

Keys: `space` shoot / retake · `d` debug overlay · `f` fullscreen · `q` quit.

To get a double-clickable app:

```bash
tools/build_app.sh
```

which writes `dist/DeskBand.app`, a launcher that runs the project with its own `.venv`.

## Tools

- `tools/render_demo.py out.wav` renders the whole band offline, one instrument entering per phrase. Useful for tuning the music without a camera.
- `tools/check_pitch.py` measures the pitch of every sample and compares it with the note in the file name.
- `tools/write_instruments_txt.py` regenerates `INSTRUMENTS.txt` from `deskband/config.py`.
- `tools/exs_extract.py` unpacks a Logic "consolidated" EXS instrument (such as the Concert Grand Piano) into per-note WAVs the sampler can use.

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
tools/                 demo renderer, checks, packaging
```

## Notes

All code was written during the hackathon. Sounds come from Apple's Logic Pro / GarageBand factory library on the local machine and are never copied into this repository.
