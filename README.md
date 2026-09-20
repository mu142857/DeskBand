# WaveLens

> Put the things on your desk in front of the camera, shoot a photo, and they become a band that never plays out of tune.

Built at **Hack the North 2026** by Aaron Shangguan, Richard Cai and Hank Lee.

## What it does

WaveLens looks at a photo of your desk and turns every object it recognises into a member of a band. A laptop, a cup, a pen, a bottle, a book, a pair of glasses, a phone: each one has its own instrument, and whatever combination you shoot, the result is always in tune and always on the beat.

| Object | Instrument | Role |
|---|---|---|
| cup (or mug) | Concert Grand Piano, soft layer | rolled chords and a sparse melody |
| pen (pencil, marker) | Classical Guitar | fingerpicked chord tones |
| bottle | Double Bass, pizzicato | chord roots |
| book (notebook) | Trap Heat drum machine, played quietly | kick, rim, hats |
| glasses | King's Cross (Studio Strings ensemble) | sustained chords |
| cell phone | Glockenspiel | high sparkle |
| laptop or tablet | Soft FM electric piano (synthesised) | dotted-8th shimmer an octave up |
| an open mouth (MediaPipe face landmarks, largest face) | Studio Baritone Sax (Logic Studio Horns) | the lead: a legato one-note-at-a-time tune, its motif drawn from the item's seed |

Every object you shoot is kept on a shelf down the right edge of the window as a thumbnail cut from the photo. The shelf starts empty and fills from the top in the order things were shot. The band is whatever is switched on there, so it can be built one photo at a time and brought back later with a click; nothing has to stay in front of the camera. Each capture gives that category a fresh random seed; its saved seed and selection survive a restart until it is captured again. A play / pause button beside the shutter silences the band without losing the selection. Nothing plays while the camera and the detector load: the restored band comes in at bar one once they are ready, and a photo, a tile or `p` brings it in sooner. Press `0` to clear the selection. An empty shelf is silent, and everything is played through a hall reverb. (An optional backing bed of vinyl noise, shaker and sub bass can be switched on in `wavelens/config.py`.)

The exact sample files behind each instrument are listed in [INSTRUMENTS.txt](INSTRUMENTS.txt).

> Team members picking this up: read [HANDOFF.md](HANDOFF.md) first (in Chinese). It covers the exact environment, architecture, music design, detection trade-offs, the remote-control protocol for hardware and AI integrations, troubleshooting and the open issues.

> Mac-side AI finishing the Zybo integration: start with [MAC_AI_HANDOFF.md](MAC_AI_HANDOFF.md). It contains the frozen architecture, prebuilt-image checksum, physical acceptance sequence, expected outputs and failure isolation.

## How it works

- **Vision:** YOLO-World (`ultralytics`) with the object names given as text prompts, so classes that are not in COCO (pen, glasses, tablet) work without training; each instrument accepts several synonyms, and one object read under two names is counted once. The app shows and saves one target at a time, with a smoothly moving outline. The large model runs on Apple Silicon via `mps` in its own thread at 960 px while a separate capture thread keeps the preview smooth, and the frozen photo gets one more pass at full resolution.
- **Music:** a fixed loop of four close voicings, one bar each at 120 BPM: `F A C E` → `G B D E` → `E G B D` → `E A B C`. They move by step and keep common tones, which gives the hovering, blurred harmony. The bass always plays the chord root (F, G, E, A). The piano rolls each voicing softly and lets it ring into the next bar, then adds a sparse line on top: one motif per trip round the loop, restated over each chord. Melodic notes come only from the C major pentatonic scale, which fits all four chords, so random choices always sound right. The rhythm skeleton is a 3-3-2 accent pattern (the quantise-everything idea is Mikutap's). Everything lands on a 16th-note grid.
- **Math mode** (`m`, or the φ button left of the shutter): the melodic parts (piano line, guitar, keys, glockenspiel, voices) stop restating patterns and are computed bar by bar, so the music never comes round again. Rhythms are Euclidean (k onsets spread evenly over the bar, turned; E(3,8) is the 3-3-2 above), and how many onsets and how far they turn comes from the logistic map in its chaotic range. Pitches walk, mostly by step, towards a 1/f contour built by Voss's method from irrational rotations (Weyl sequences), so no value ever recurs. Notes are still pentatonic with chord tones on the accents, so it stays in tune. It switches on the next bar line; bass, drums and strings keep their patterns.
- **Baritone sax:** `tools/make_bari_sax.py` cuts Logic's Studio Horns "Studio Baritone Sax" into 22 single notes in `cache/bari_sax/` (each note there is stored as a 35 ms attack zone plus a body zone; the tool joins them). Until it has been run the open-mouth instrument is silent.
- **Voices (ElevenLabs), not used by default:** set `voice="vocal"` on an instrument in `config.py` to use them. The first start with `ELEVENLABS_API_KEY` set asks ElevenLabs' sound-effects model for a few sustained sung notes, pitch-tracks each take, drops any that wander, retunes the rest to the nearest semitone and files them in `cache/vocal/` as an ordinary sample keymap. From then on they are played like any other sampler instrument, following the chords. Delete `cache/vocal/` to make new ones, or run `.venv/bin/python -m wavelens.vocals`.
- **Photo description (Gemini):** with `GEMINI_API_KEY` set, every photo is sent to Gemini (`GEMINI_MODEL` in `wavelens/config.py`) in the background, and its one- or two-sentence description of the object appears under the title while the photo is shown. The words are then kept with that object on the shelf, so the Collections page still shows them long afterwards; the first description an object is given stays, even when it is photographed again. It changes nothing in the music.
- **Saved motifs:** every successful capture generates a new random motif seed for its category, even when the same category is photographed again. The latest seed and selected state are saved. In standard mode, parts that use randomness repeat their resulting pattern on every full chord cycle; bass and strings are determined by the chords and do not change notes when reseeded. Math mode intentionally keeps evolving. If a style changes the chords, the saved seed produces notes harmonized to the new progression. `App.arrangement_snapshot()` freezes the saved items, selected parts, current BPM, and the active chord progression into an immutable score for a **new complete cycle beginning at bar one**. A pending style is marked in the snapshot. Pitched parts have note timelines; drums have hit steps for a beat grid.
- **Audio:** a small engine on top of `sounddevice`. Real instruments are sample-based (Logic Pro / GarageBand factory content read in place from the Mac), the synth parts are generated, and everything runs through a long Schroeder hall reverb. The engine runs at the output device's own sample rate, and the master bus uses a gain-riding limiter rather than clipping. The audio callback never blocks on vision; a slow frame only delays the picture.
- **Remote port:** JSON over UDP (port 9000) so a badge, an FPGA board or another program can take the photo, switch saved instruments on and off, change tempo and chords, play a sound in time, receive FPGA bar telemetry, and subscribe to the beat. `tools/remote_sim.py` is a dependency-free simulator of it. Protocol in [HANDOFF.md](HANDOFF.md) section 10.
- **FPGA conductor:** a Zybo Z7-20 owns the master beat clock, seven-track sequencer, automatic LFSR/Euclidean bar generation, eighth-only/mixed rhythm quantization, and four-tap tempo measurement. Its Cortex-A9 firmware bridges the programmable logic to the Mac over UART, while the Mac keeps vision and audio synthesis. BTN0 is the shutter, BTN1 toggles Math melody mode, BTN2 toggles the hardware rhythm grid at the next bar, and four BTN3 taps set BPM. See [fpga/README.md](fpga/README.md).
- **UI:** one window. Desaturated duotone image, colour back inside detected objects under the instrument's own colour filter, thin rounded outlines, SF Pro labels, a frosted card listing the band (one dot in each instrument's colour), the shelf of saved instruments (each thumbnail under the same filter; colours are `tint` in `INSTRUMENTS`), and a shutter button. Press `space` (or click the shutter) to shoot, `space` again to retake. Press `e` or click **Collections** to inspect the saved collection, view each part's actual note/rhythm strip, read what Gemini said about the photo that collected it (two lines on the card, the whole thing while the pointer rests on it), and choose the items in this song. **Render loop** saves one complete chord cycle to `cache/exports/`; **Play clip** previews it, and **Reveal file** shows it in Finder. With `ELEVENLABS_API_KEY` set, **Continue with ElevenLabs** opens a separate upload confirmation and can generate a longer instrumental song with the original loop as its intro. **Play song** and **Reveal song** use files in `cache/songs/`. The live band is muted on this screen and resumes when you go Back. A small dot beside the title is the Zybo light: unlit when no board has answered on USB, steady once one has, and beating on the downbeat while the board's clock conducts.
- **Stage:** `tab` (or the button at the left of the row) swaps the camera for a plane on which the band is laid out by hand. Drag a thumbnail from the shelf onto it to bring that instrument in, drag its token off (or right-click it) to take it out. Up is loudness (the part's own level in the middle, −24 dB at the bottom, +9 dB at the top), across is complexity: the middle band plays the part as written, to the left notes drop away from the weakest beats first down to the downbeat alone, to the right passing notes and 16th grace notes fill in. Loudness follows the hand at once, complexity from the next bar line. Where each instrument stands is kept on the shelf, so it comes back to the same spot; one that joins without being dragged in lands at random about the middle of the plane, clear of the others and of the edges. The die at the right of the row (or `r`) deals the whole stage again: one of the parts math mode computes is put out front at the top, the others are kept below the middle, the drums stand high in the middle, and the rest fall where they like. In math mode the grid gives way to a golden-angle field and each computed part wears a ring of the bar's 16ths, its onsets lit in the instrument's colour and joined up, with a hand at the step being heard — so the shape changes every bar. Both switch on the bar line where math mode is first heard; until then the φ button pulses.

## Requirements

- Apple Silicon Mac with Logic Pro or GarageBand sound library installed (the samples are read from `/Library/Application Support/Logic` and `/Library/Application Support/GarageBand`).
- Python 3.11 (the project uses only its `.venv` for packages).
- A webcam.

Camera frames use their original orientation and WaveLens shows the entire frame supplied by the device, including with iPhone Continuity Camera. The image is fitted inside the window without cropping. For a mirrored selfie-style preview, set `MIRROR_CAMERA = True` in `wavelens/config.py`. Detection boxes and saved photos use the same orientation as the preview. If Continuity Camera itself is zoomed, use the macOS Video menu to turn off Center Stage, set Zoom to 1×, and choose the iPhone Main camera.

## Setup

```bash
cd ~/Desktop/WaveLens
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# face model for the open-mouth instrument (mediapipe 1.0.x crashes on macOS: Metal "Service is unavailable")
mkdir -p weights && curl -L -o weights/face_landmarker.task https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
```

Optional Gemini key (without one, descriptions are off):

```bash
export GEMINI_API_KEY=...        # photo descriptions
```

```bash
read -rsp 'ElevenLabs API key: ' WAVELENS_KEY; echo
umask 077
mkdir -p cache
printf '%s\n' "$WAVELENS_KEY" > cache/elevenlabs_api_key
unset WAVELENS_KEY
```

Put a working key in the ignored `cache/elevenlabs_api_key` file when you are ready; this project has no `local.env` file or parser. Keep the key file readable only by your user (`chmod 600 cache/elevenlabs_api_key`). `tools/run_app.sh` and the rebuilt `WaveLens.app` load it into the app process; no system environment change is needed. An existing `ELEVENLABS_API_KEY` process variable takes precedence. For Gemini in Finder, start the app from a terminal with that variable set or use `launchctl setenv GEMINI_API_KEY ...` once per login.

All Python packages are installed in `.venv`; the ElevenLabs and Gemini calls use standard-library HTTPS and need no SDK. Never commit API keys. Rendered loop WAVs are in the ignored `cache/exports/` directory, and generated MP3s plus job state are in ignored `cache/songs/`. A selected headphones part requires existing voice takes in `cache/vocal/` before local export. Music upload and generation can both use paid credits, and upload screening can reject a source; verify your rights to the samples before confirming. The app does not retry a possibly charged composition request automatically.

The ElevenLabs continuation uses `music_v2_5` and requires Music API access on the account. The current team's key authenticated on the user endpoint but the Music endpoint returned `paid_plan_required` on 2026-09-19. Local loop rendering, playback, and file reveal still work without Music access. Once a full song has been generated, its saved MP3 is found again on the Collections page after restarting WaveLens when the same arrangement is selected; no network request is needed to play it.

The first run downloads the YOLO-World weights (`yolov8l-worldv2.pt`, ~90 MB; the 25 MB `yolov8s-worldv2.pt` is used if the large one is missing) and the CLIP text encoder (~340 MB), and macOS asks for camera access.

Optional but recommended, the two sounds the piece is written for (both are unpacked from Logic's library into `cache/`, which is not in the repo; without them the Yamaha Grand and Pop Strings sets are used):

```bash
.venv/bin/python tools/exs_extract.py "/Library/Application Support/Logic/Sampler Instruments/z_Internal/Studio Piano/Concert Grand Piano.exs" "/Library/Application Support/Logic/EXS Factory Samples/Studio Piano/Concert Grand Piano" cache/concert_grand_soft --velocity 45 --max-seconds 8
```

```bash
.venv/bin/python tools/make_kings_cross.py
.venv/bin/python tools/make_bari_sax.py
```

## Run

```bash
tools/run_app.sh
```

Keys: `space` shoot / retake · click a shelf thumbnail or `1`–`8` (counting from the top) switch a saved instrument on or off · `e` open the summary; `b`, `e`, or Escape returns (on the summary, `1`–`8` toggle its cards) · `p` or return play / pause · `m` math mode on / off · `g` rhythm grid, 8ths only / 8ths + 16ths (the board's BTN2) · `t` or click the tempo pill four times to tap the tempo, held to 60–180 BPM (BTN3); `-` / `=` step it by 2 · `tab` camera / stage · `r` deal the stage again (on the stage) · `0` deselect them all · right-click a slot (or hover and press `x`) forget it · `s` save the live frame to `cache/shots/` · `d` debug overlay · `f` fullscreen · `q` quit.

With the Zybo's J12 `PROG/UART` port connected using a Micro-USB data cable,
run the bridge in a second terminal (`pyserial` is included in `requirements.txt`):

```bash
.venv/bin/python tools/zybo_bridge.py /dev/cu.usbserial-XXXXXXXX
```

The board can boot standalone from `fpga/build/BOOT.BIN`; build and physical
wiring instructions are in [fpga/README.md](fpga/README.md).

To get a double-clickable app:

```bash
tools/build_app.sh
```

which writes `dist/WaveLens.app`: a small native launcher (`tools/launcher.c`) that runs the project with its own `.venv`. It has to be native so macOS attributes the camera permission to WaveLens.

For the presentation sequence, timing notes, and offline fallback, see [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md).

## Tools

- `tools/render_demo.py out.wav` renders the whole band offline, one instrument entering per phrase. Useful for tuning the music without a camera.
- `tools/check_pitch.py` measures the pitch of every sample and compares it with the note in the file name.
- `tools/write_instruments_txt.py` regenerates `INSTRUMENTS.txt` from `wavelens/config.py`.
- `tools/exs_extract.py` unpacks a Logic "consolidated" EXS instrument (such as the Concert Grand Piano) into per-note WAVs the sampler can use.
- `tools/eval_prompts.py` replays the saved photos through the detector with any prompts, threshold, size or model.
- `tools/make_bari_sax.py` builds the baritone sax notes into `cache/bari_sax/`.
- `tools/make_kings_cross.py` builds the King's Cross string ensemble (five sections layered) into `cache/kings_cross/`.
- `tests/` checks the reverb against a per-sample reference and the sample player for exactness: `.venv/bin/python tests/test_reverb.py`.

## Project layout

```
main.py                app, states (preview / show / summary), drawing
wavelens/config.py     tempo, chords, instrument table, sample paths
wavelens/vision.py     camera + YOLO-World thread
wavelens/music.py      composer: patterns per instrument
wavelens/motifs.py     random capture seeds and deterministic offline fallbacks
wavelens/arrangement.py immutable next-cycle score and fingerprint
wavelens/score_view.py compact note strips and drum grids
wavelens/summary.py   collection screen layout, hitboxes, and worker status queue
wavelens/synth.py      audio engine, voices, sequencer
wavelens/sampler.py    sample loading and key maps
wavelens/fx.py         hall reverb
wavelens/ui.py         drawing primitives (duotone, outlines, text, cards)
wavelens/remote.py     UDP/JSON remote-control port
wavelens/shelf.py      saved instruments (thumbnails + motifs + selection + stage spots), kept in cache/shelf/
wavelens/stage.py      the stage: the band placed on a loudness x complexity plane
wavelens/fpga_protocol.py  Zybo UART command/event codec
fpga/                  RTL, simulations, Zynq firmware, Vivado/Vitis builds
styles/                example chord loops for the remote "style" command
tools/zybo_bridge.py   UART-to-WaveLens bridge for the FPGA conductor
tools/                 demo renderer, checks, packaging
```

## Notes

All code was written during the hackathon. Sounds come from Apple's Logic Pro / GarageBand factory library on the local machine and are never copied into this repository.
