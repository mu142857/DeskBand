"""Global tunables: tempo, harmony, instrument table, sample locations."""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "cache")

SAMPLE_RATE = 44100
BLOCK_SIZE = 512          # ~11.6 ms at 44.1 kHz

# --- clock (after Mikutap: 60000/280 ms grid = 8th notes at 140 BPM)
BPM = 140
STEPS_PER_BEAT = 4        # internal grid is 16ths; most parts play on 8ths
STEPS_PER_BAR = 16
BARS_PER_CHORD = 2
STEPS_PER_PHRASE = STEPS_PER_BAR * BARS_PER_CHORD   # one chord = one phrase

# Mikutap's backing pattern "3443443443443434" per 16 eighths: accents every
# 3-3-3-3-2-2 eighths. Expressed here as 16th steps inside a phrase.
ACCENTS = [0, 6, 12, 18, 24, 28]

# Chord loop (pitch classes, 0 = C). Key of C major.
CHORDS = [
    ("Fmaj7", [5, 9, 0, 4]),
    ("Em7",   [4, 7, 11, 2]),
    ("Dm7",   [2, 5, 9, 0]),
    ("Cmaj7", [0, 4, 7, 11]),
]
PENTATONIC = [0, 2, 4, 7, 9]     # C D E G A: fits every chord above

# --- detected object -> part
#   voice:   which sampler / synth renders it (see synth.py)
#   lo/hi:   MIDI register (Logic convention, C3 = 60)
#   level:   channel gain, send: reverb send
INSTRUMENTS = {
    "cup":        dict(label="Grand Piano",      voice="piano",   lo=60, hi=84, level=0.90, send=0.30),
    "pen":        dict(label="Classical Guitar", voice="guitar",  lo=48, hi=67, level=0.80, send=0.25),
    "bottle":     dict(label="Double Bass",      voice="bass",    lo=28, hi=43, level=1.00, send=0.05),
    "book":       dict(label="Trap Heat Drums",  voice="drums",   lo=0,  hi=0,  level=0.85, send=0.10),
    "lamp":       dict(label="Strings",          voice="strings", lo=55, hi=76, level=0.55, send=0.45),
    "cell phone": dict(label="Glockenspiel",     voice="bells",   lo=84, hi=96, level=0.55, send=0.40),
    "laptop":     dict(label="Synth Arp",        voice="arp",     lo=60, hi=79, level=0.45, send=0.25),
}
DETECT_CLASSES = list(INSTRUMENTS.keys())
BACKING = dict(level=1.0, send=0.15)

# --- sample libraries (Logic Pro / GarageBand factory content, internal disk)
LIB_LOGIC = "/Library/Application Support/Logic/EXS Factory Samples"
LIB_GB = "/Library/Application Support/GarageBand/Instrument Library/Sampler/Sampler Files"
LIB_LOOPS = "/Library/Audio/Apple Loops/Apple"

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
CONCERT_GRAND = os.path.join(CACHE_DIR, "concert_grand")

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
REVERB = dict(room=0.86, damp=0.45, predelay_ms=18.0, wet=0.9)

# --- vision
CAMERA_INDEX = 0
DETECT_CONF = 0.35
DETECT_IMGSZ = 640
PRESENCE_HOLD = 1.0
