"""Random capture seeds and deterministic fallbacks for unsaved parts."""

import hashlib
import secrets


MOTIF_VERSION = 1


def default_seed(name, version=MOTIF_VERSION):
    """Deterministic fallback for an unsaved part or an offline score."""
    key = f"deskband:motif:{version}:{name}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")


def new_seed(previous=None):
    """Give each capture a fresh seed, including a re-shot of the same class."""
    seed = secrets.randbits(64)
    while seed == previous:
        seed = secrets.randbits(64)
    return seed
