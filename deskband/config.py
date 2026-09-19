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
BARS_PER_CHORD = 2
STEPS_PER_PHRASE = STEPS_PER_BAR * BARS_PER_CHORD   # one chord = one phrase

# Mikutap's backing pattern "3443443443443434" per 16 eighths: accents every
# 3-3-3-3-2-2 eighths. Expressed here as 16th steps inside a phrase.
ACCENTS = [0, 6, 12, 18, 24, 28]

# Chord loop (pitch classes, 0 = C). Key of C major.
# IV - V - iii - vi: the first pitch class of each chord is its root, and
# the bass, the guitar's low string and the strings' bottom voice all play it.
CHORDS = [
    ("Fmaj7", [5, 9, 0, 4]),
    ("G",     [7, 11, 2]),
    ("Em",    [4, 7, 11]),
    ("Am",    [9, 0, 4]),
]
PENTATONIC = [0, 2, 4, 7, 9]     # C D E G A: fits every chord above

# --- detected object -> part
#   voice:   which sampler / synth renders it (see synth.py)
#   lo/hi:   MIDI register (Logic convention, C3 = 60)
#   level:   channel gain, send: reverb send
INSTRUMENTS = {
    "cup":        dict(label="Grand Piano",      voice="piano",   lo=60, hi=84, level=0.37, send=0.30),
    "pen":        dict(label="Classical Guitar", voice="guitar",  lo=48, hi=67, level=0.41, send=0.25),
    "bottle":     dict(label="Double Bass",      voice="bass",    lo=36, hi=47, level=0.34, send=0.05),
    "book":       dict(label="Trap Heat Drums",  voice="drums",   lo=0,  hi=0,  level=0.22, send=0.10),
    "lamp":       dict(label="Strings",          voice="strings", lo=55, hi=76, level=0.15, send=0.45),
    "cell phone": dict(label="Glockenspiel",     voice="bells",   lo=84, hi=96, level=0.20, send=0.40),
    "laptop":     dict(label="Synth Arp",        voice="arp",     lo=60, hi=79, level=0.33, send=0.25),
}
DETECT_CLASSES = list(INSTRUMENTS.keys())
# Backing layer under the objects. All off: an empty desk is silent and the
# band is only what was photographed. Flip these on to bring the bed back.
BACKING = dict(level=1.0, send=0.15, vinyl=False, sub=False, perc=False)

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
REVERB = dict(room=0.84, damp=0.5, predelay_ms=18.0, wet=0.85)

# --- master bus. Part levels above are set so each instrument peaks around
# 0.2-0.45 on its own; MAKEUP lifts sparse bands, the limiter rides the gain
# down (no waveshaping) if the sum still goes over CEILING.
MAKEUP = {0: 1.5, 1: 1.5, 2: 1.3, 3: 1.15}     # active parts -> gain, else 1.0
CEILING = 0.89
LIMITER_RELEASE_S = 0.5

# --- vision
CAMERA_INDEX = 0
DETECT_CONF = 0.35
DETECT_IMGSZ = 640
PRESENCE_HOLD = 1.0
