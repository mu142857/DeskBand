"""Stable musical identity for a saved instrument slot."""

import hashlib


MOTIF_VERSION = 1


def default_seed(name, version=MOTIF_VERSION):
    """The same slot has the same motif across Python processes and machines."""
    key = f"deskband:motif:{version}:{name}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
