"""Global tunables: tempo, harmony, instrument table, sample locations."""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache")



def _device_rate(default=44100):
    """Run the engine at the output device's own sample rate so nothing has to
    convert in real time (PortAudio's 44.1k -> 48k path crackles on Bluetooth)."""
    try:
        import sounddevice as sd
        return int(sd.query_devices(kind="output")["default_samplerate"])
    except Exception:
        return default


SAMPLE_RATE = _device_rate()
BLOCK_SIZE = 1024         # ~21 ms; this is not a latency-critical instrument

# --- clock: 16th-note grid, 8th-note feel (the quantising idea is Mikutap's)
BPM = 120
STEPS_PER_BEAT = 4        # internal grid is 16ths; most parts play on 8ths
STEPS_PER_BAR = 16
BARS_PER_CHORD = 1
STEPS_PER_PHRASE = STEPS_PER_BAR * BARS_PER_CHORD   # one chord = one bar

# Rhythm skeleton: 3-3-2 in 8ths (the one-bar form of Mikutap's 3-3-3-3-2-2).
ACCENTS = [0, 6, 12]

# Chord loop, one bar each: (name, root pitch class, close voicing as MIDI notes,
# C3 = 60). The voicings move by step and keep common tones, which is where the
# blurred, hovering quality comes from. The bass always plays the root.
CHORDS = [
    ("Fmaj7",    5, [53, 57, 60, 64]),   # F A C E
    ("G6",       7, [55, 59, 62, 64]),   # G B D E
    ("Em7",      4, [52, 55, 59, 62]),   # E G B D
    ("Am(add9)", 9, [52, 57, 59, 60]),   # E A B C
]
PENTATONIC = [0, 2, 4, 7, 9]     # C D E G A: fits every chord above

# Math mode (key m): the melodic parts stop restating patterns and are computed
# instead: Euclidean rhythms, a 1/f contour made of irrational rotations and a
# chaotic logistic map (music.Sequence). Never repeats, still only pentatonic
# notes, and chord tones on the accents. Takes effect on the next bar line.
MATH_MODE = False
LOGISTIC_R = 3.97                # the logistic map is chaotic for r above ~3.57

# --- detected object -> part
#   voice:   which sampler / synth renders it (see synth.py)
#   lo/hi:   MIDI register (Logic convention, C3 = 60)
#   level:   channel gain, send: reverb send
#   detect:  text prompts that count as this object (any of them)
#   tint:    colour filter laid over its shelf thumbnail (ui.tint)
INSTRUMENTS = {
    "cup":        dict(label="Concert Grand, soft", voice="piano", lo=67, hi=88, level=0.28, send=0.55,
                       detect=["cup", "mug"], tint="#E8A25E"),
    "pen":        dict(label="Classical Guitar", voice="guitar",  lo=48, hi=67, level=0.41, send=0.25,
                       detect=["pen", "pencil", "marker"], tint="#E57F6B"),
    "bottle":     dict(label="Double Bass",      voice="bass",    lo=36, hi=47, level=0.34, send=0.05,
                       detect=["bottle", "water bottle"], tint="#5B8FD6"),
    "book":       dict(label="Trap Heat Drums",  voice="drums",   lo=0,  hi=0,  level=0.22, send=0.10,
                       detect=["book", "notebook"], tint="#D9739B"),
    "glasses":    dict(label="King's Cross Strings", voice="strings", lo=52, hi=76, level=0.14, send=0.50,
                       detect=["glasses", "eyeglasses", "sunglasses"], tint="#9A82D6"),
    "cell phone": dict(label="Glockenspiel",     voice="bells",   lo=84, hi=96, level=0.24, send=0.40,
                       detect=["cell phone"], tint="#4FBFA8"),
    "laptop":     dict(label="Soft Keys",        voice="keys",    lo=64, hi=88, level=0.30, send=0.55,
                       detect=["laptop", "tablet", "ipad"], tint="#A3C26A"),
    # Sung "ooh" samples made once by ElevenLabs (deskband/vocals.py); silent until they exist.
    # Not an object: an open mouth in the photo (deskband/face.py), so no text prompts.
    "mouth":      dict(label="Voices",           voice="vocal",   lo=57, hi=74, level=0.16, send=0.60,
                       detect=[], tint="#D8BE5A"),
}
# The Zybo sequencer has seven tracks, in this order (tools/zybo_bridge.py). A part
# not listed here follows the board's clock in FPGA mode but is not gated by it.
FPGA_TRACKS = ("cup", "pen", "bottle", "book", "glasses", "cell phone", "laptop")
# Text prompts given to YOLO-World, and which part each one belongs to.
ALIASES = {alias: name for name, spec in INSTRUMENTS.items() for alias in spec["detect"]}
DETECT_CLASSES = list(ALIASES)
# On-screen name when it differs from the prompt that fired.
SHOW_AS = {"ipad": "tablet", "eyeglasses": "glasses", "water bottle": "bottle"}
# Backing layer under the objects. All off: an empty desk is silent and the
# band is only what was photographed. Flip these on to bring the bed back.
BACKING = dict(level=1.0, send=0.15, vinyl=False, sub=False, perc=False)

# --- sample libraries (Logic Pro / GarageBand factory content, internal disk)
LIB_LOGIC = "/Library/Application Support/Logic/EXS Factory Samples"
LIB_GB = "/Library/Application Support/GarageBand/Instrument Library/Sampler/Sampler Files"
LIB_LOOPS = "/Library/Audio/Apple Loops/Apple"
# The libraries above may live on an external disk. tools/copy_samples.py copies
# just the files used here into samples/<kind>/ (kept in git), which wins when present.
LOCAL_SAMPLES = os.path.join(ROOT, "samples")


def sample_dir(kind, library_dir):
    local = os.path.join(LOCAL_SAMPLES, kind)
    return local if os.path.isdir(local) else library_dir

# pitch: how the MIDI note is read from the file name.
#   "prefix3"  -> leading 3-digit MIDI number     (060_C3KM56_M.wav)
#   "logic"    -> note name, C3 = 60              (50A-1GA1-E1.aif)
#   "sci"      -> note name, C4 = 60              (GLS2_Pla_mf_C6.wav)
#   "cbs"      -> "Cbs pizz f  0 e" style, octave then note, C3 = 60
SAMPLE_SETS = {
    "piano": dict(dir=f"{LIB_LOGIC}/01 Acoustic Pianos/Yamaha Grand Piano",
                  glob="*_M.wav", exclude="_ped_", pitch="prefix3", max_seconds=5.0),
    "guitar": dict(dir=f"{LIB_GB}/Classical Acoustic Guitar",
                   glob="50A-1GA2-*.aif", pitch="logic", max_seconds=4.0),
    "bass": dict(dir=f"{LIB_LOGIC}/06 Pop Strings/Double Bass (Pizzicato)",
                 glob="Cbs pizz f*.aif", pitch="cbs", max_seconds=3.0),
    "strings": dict(dir=f"{LIB_LOGIC}/06 Pop Strings/EXS Strings 2",
                    glob="*-left.aif", pair=("-left", "-right"), pitch="strng", max_seconds=6.0),
    "bells": dict(dir=f"{LIB_GB}/Glockenspiel/Glockenspiel_Pla_mf1",
                  glob="*.wav", pitch="sci", max_seconds=4.0),
}
# Optional: Concert Grand Piano unpacked by tools/exs_extract.py into cache/.
# When cache/concert_grand/keymap.json exists it replaces the Yamaha set.
# The soft velocity layer (cache/concert_grand_soft) is preferred: played
# quietly and low-passed it gives the felt, far-away piano.
CONCERT_GRAND = [os.path.join(CACHE_DIR, "concert_grand_soft"), os.path.join(CACHE_DIR, "concert_grand")]
PIANO_LOWPASS_HZ = 3000          # 0 = off
# King's Cross (Studio Strings "String Ensemble") unpacked by tools/make_kings_cross.py;
# replaces the EXS Strings 2 set when present.
KINGS_CROSS = os.path.join(CACHE_DIR, "kings_cross")
# Voices (open mouth): sung takes generated once by ElevenLabs' sound-effects model,
# pitch-detected, tuned to the nearest semitone and kept here as <midi>.wav +
# keymap.json. Delete the folder to make new ones. Needs ELEVENLABS_API_KEY.
VOCAL_DIR = os.path.join(CACHE_DIR, "vocal")
VOCAL_PROMPTS = [                # one take each; whatever pitch it lands on becomes a key zone
    "a solo female alto voice singing one long sustained 'ooh' on a single low steady note, "
    "no vibrato, dry close-mic studio recording, no reverb, no music, no other sounds",
    "a solo female voice singing one long sustained 'ooh' on a single steady note, "
    "no vibrato, dry close-mic studio recording, no reverb, no music, no other sounds",
    "a solo soprano voice singing one long sustained 'aah' on a single high steady note, "
    "no vibrato, dry close-mic studio recording, no reverb, no music, no other sounds",
]
VOCAL_SECONDS = 4.0

DRUM_DIR = f"{LIB_LOGIC}/03 Drums & Percussion/02 Electronic Drum Kits/Trap Heat"
DRUMS = {
    "kick": "Kick 1 - Trap Heat.aif",
    "snare": "Snare 1 - Trap Heat.aif",
    "clap": "Clap 1 - Trap Heat.aif",
    "hat": "Hi-Hat 1 - Trap Heat.aif",
    "hat_open": "Hi-Hat Open - Trap Heat.aif",
    "shaker": "Shaker 1 - Trap Heat.aif",
    "rim": "Rim 1 - Trap Heat.aif",
    "snap": "Snap - Trap Heat.aif",
    "perc": "Perc 1 - Trap Heat.aif",
}
VINYL_LOOP = f"{LIB_LOOPS}/Beat Tape/Noisy Vinyl FX 01.caf"   # AAC; decoded once into cache/
VINYL_LEVEL = 0.22

# --- reverb (Schroeder/Freeverb style hall)
REVERB = dict(room=0.92, damp=0.45, predelay_ms=25.0, wet=1.0)     # long, soft hall

# --- master bus. Part levels above are set so each instrument peaks around
# 0.2-0.45 on its own; MAKEUP lifts sparse bands, the limiter rides the gain
# down (no waveshaping) if the sum still goes over CEILING.
MAKEUP = {0: 1.5, 1: 1.5, 2: 1.3, 3: 1.15}     # active parts -> gain, else 1.0
CEILING = 0.89
LIMITER_RELEASE_S = 0.5

# --- the stage (tab): the band placed by hand on a plane (deskband/stage.py).
# Up is loudness: the part's own level in the middle, STAGE_DB at the bottom
# and top edges. Across is complexity: the middle band (STAGE_AS_WRITTEN) plays
# the part as written, left of it notes drop away from the weakest beats first,
# right of it passing notes and graces fill in (music.Pattern.arrange).
STAGE_DB = (-24.0, 9.0)
STAGE_AS_WRITTEN = (0.4, 0.6)

# --- remote control (deskband/remote.py): JSON over UDP for hardware and other programs
REMOTE_HOST = "0.0.0.0"        # "127.0.0.1" to accept commands from this Mac only
REMOTE_PORT = 9000
REMOTE_STATE_HZ = 20

# --- cloud APIs. Keys come from the environment only (never from this file);
# without one the feature is simply off and everything else runs as before.
GEMINI_KEY_ENV = "GEMINI_API_KEY"
GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_PROMPT = ("This photo was taken by DeskBand, an app that turns the things on a desk into "
                 "instruments. In one or two short sentences (30 words at most), describe the main "
                 "object being shown to the camera: what it is, its colour and material, and anything "
                 "distinctive about it. Plain text, no markdown.")
ELEVENLABS_KEY_ENV = "ELEVENLABS_API_KEY"
API_TIMEOUT_S = 30

# --- vision
CAMERA_INDEX = 0
MIRROR_CAMERA = False       # raw orientation for Continuity Camera; True for a selfie-style preview
DETECT_CONF = 0.25          # open-vocabulary scores run low; press d to see them
DETECT_SURE = 0.50          # at or above this a detection stands on its own
DETECT_FLOOR = 0.10         # photo only: how faint the second pass's agreement may be...
CONFIRM_CONF = 0.10         # ...for a weak detection (DETECT_CONF..DETECT_SURE) to be kept
CONFIRM_EDGE = 0.15         # stricter for boxes cut off by the frame edge
SLIVER_PX = 40              # boxes thinner than this along the frame edge are dropped
DETECT_MODEL = "yolov8l-worldv2.pt"            # the large model recognises far more reliably
DETECT_MODEL_FALLBACK = "yolov8s-worldv2.pt"   # used when the large weights are not present
DETECT_IMGSZ = 960          # live preview: ~115 ms per frame with the large model on an M2 Pro
SHOOT_IMGSZ = 1280          # one extra full-resolution pass on the frozen photo (~200 ms)
SHOTS_DIR = os.path.join(CACHE_DIR, "shots")   # every photo is kept here for tuning the detector
SHELF_DIR = os.path.join(CACHE_DIR, "shelf")   # saved instruments: one thumbnail per slot + shelf.json
FACE_MODEL = os.path.join(ROOT, "weights", "face_landmarker.task")   # MediaPipe; see README
MOUTH_JAW = 0.50            # jawOpen blendshape: talking reaches ~0.4, a toothy smile ~0.3; press d to see it
MOUTH_GAP = 0.20            # and the lip gap must be at least this fraction of the mouth's width
PRESENCE_HOLD = 1.0
