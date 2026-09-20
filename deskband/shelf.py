"""The shelf: instruments saved from earlier photos.

Shooting a photo files a thumbnail of the single object selected; from then on the
instrument can be switched on and off from the shelf without the object being
in front of the camera, so a band is built one photo at a time. The shelf
starts empty and fills in the order things were first shot (one place per
instrument; shooting the same kind of object again replaces its picture but
keeps its place). Kept on disk, so it survives a restart, along with where
each instrument was put on the stage (Entry.pos)."""

import json
import os
import tempfile
import time

import cv2

from .motifs import MOTIF_VERSION, new_seed

THUMB = 144          # stored thumbnail side, px (drawn at half that)


def crop_square(frame, box, margin=1.15):
    """Square crop around a detection box, shifted rather than shrunk at the edges."""
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = box
    side = int(min(max(x1 - x0, y1 - y0) * margin, W, H))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    left = min(max(cx - side // 2, 0), W - side)
    top = min(max(cy - side // 2, 0), H - side)
    crop = frame[top:top + side, left:left + side]
    return cv2.resize(crop, (THUMB, THUMB), interpolation=cv2.INTER_AREA)


class Entry:
    def __init__(self, name, shown, conf, thumb, saved_at=None, *, instrument=None,
                 motif_version=MOTIF_VERSION, motif_seed=None, selected=False, pos=None,
                 description=None):
        self.name, self.shown, self.conf, self.thumb = name, shown, conf, thumb
        self.saved_at = time.time() if saved_at is None else saved_at
        self.pos = tuple(pos) if pos else None
        self.instrument = instrument or name
        self.motif_version = motif_version
        self.motif_seed = new_seed() if motif_seed is None else motif_seed
        self.selected = selected
        self.description = description or None   # Gemini on the photo that first filed it
        self.tile = None             # drawing cache, owned by the UI


class Shelf:
    def __init__(self, folder, names):
        self.folder = folder
        self.names = list(names)     # what can be saved: the instruments
        self.entries = {}            # name -> Entry
        self.load()

    def order(self):
        """Saved instruments, first shot first: the shelf from the top down."""
        return sorted(self.entries, key=lambda n: self.entries[n].saved_at)

    # ------------------------------------------------------------- disk
    def _index(self):
        return os.path.join(self.folder, "shelf.json")

    def _image(self, name):
        return os.path.join(self.folder, name.replace(" ", "_") + ".jpg")

    def load(self):
        try:
            with open(self._index()) as f:
                index = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(index, dict):
            return
        migrated = False
        for name, meta in index.items():
            if name not in self.names or not isinstance(meta, dict):
                continue
            thumb = cv2.imread(self._image(name))
            if thumb is not None:
                thumb = cv2.resize(thumb, (THUMB, THUMB))
                version = meta.get("motif_version", MOTIF_VERSION)
                if not isinstance(version, int) or version < 1:
                    version = MOTIF_VERSION
                seed = meta.get("motif_seed")
                if not isinstance(seed, int) or seed < 0:
                    seed = new_seed()
                description = meta.get("description")
                if not isinstance(description, str) or not description.strip():
                    description = None
                migrated |= any(k not in meta for k in ("instrument", "motif_version", "motif_seed",
                                                        "selected", "description"))
                migrated |= (meta.get("instrument") != name or
                             meta.get("motif_version") != version or meta.get("motif_seed") != seed)
                self.entries[name] = Entry(name, meta.get("shown", name), meta.get("conf", 0.0),
                                           thumb, meta.get("saved_at"), instrument=name,
                                           motif_version=version, motif_seed=seed,
                                           selected=bool(meta.get("selected", False)), pos=meta.get("pos"),
                                           description=description)
        if migrated:
            self._save_index()

    def _write_index(self):
        os.makedirs(self.folder, exist_ok=True)
        index = {n: dict(shown=e.shown, conf=round(e.conf, 3), saved_at=e.saved_at,
                         instrument=e.instrument, motif_version=e.motif_version,
                         motif_seed=e.motif_seed, selected=e.selected,
                         description=e.description,
                         pos=[round(v, 4) for v in e.pos] if e.pos else None)
                 for n, e in self.entries.items()}
        fd, pending = tempfile.mkstemp(prefix=".shelf-", suffix=".json", dir=self.folder)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(index, f, indent=1)
            os.replace(pending, self._index())
        finally:
            if os.path.exists(pending):
                os.remove(pending)

    def _save_index(self):
        try:
            self._write_index()
        except OSError as e:                # a full disk must not stop the show
            print("shelf not saved:", repr(e), flush=True)

    # ---------------------------------------------------------- changes
    def add(self, name, shown, conf, frame, box):
        """File (or re-file) an object; the newest photo wins. Returns the entry."""
        if name not in self.names:
            return None
        old = self.entries.get(name)
        entry = Entry(name, shown, conf, crop_square(frame, box), old.saved_at if old else None,
                      instrument=old.instrument if old else name,
                      motif_version=old.motif_version if old else MOTIF_VERSION,
                      motif_seed=new_seed(old.motif_seed if old else None),
                      selected=old.selected if old else False,
                      pos=old.pos if old else None,
                      description=old.description if old else None)
        self.entries[name] = entry
        try:                                   # a full disk must not stop the show
            os.makedirs(self.folder, exist_ok=True)
            cv2.imwrite(self._image(name), entry.thumb, [cv2.IMWRITE_JPEG_QUALITY, 92])
            self._save_index()
        except OSError as e:
            print("shelf not saved:", repr(e), flush=True)
        return entry

    def describe(self, name, text):
        """File what Gemini said about the photo. The first description stays:
        re-shooting an object keeps the words from when it was first collected."""
        entry = self.entries.get(name)
        text = " ".join(str(text).split())
        if entry is None or entry.description or not text:
            return False
        entry.description = text
        self._save_index()
        return True

    def remove(self, name):
        if self.entries.pop(name, None) is None:
            return
        try:
            os.remove(self._image(name))
        except OSError:
            pass
        self._save_index()

    def place(self, name, pos, save=True):
        """Put a saved instrument at (complexity, loudness) on the stage, both
        0..1. save=False while it is being dragged; the drop writes it down."""
        entry = self.entries.get(name)
        if entry is None:
            return
        entry.pos = tuple(min(max(float(v), 0.0), 1.0) for v in pos)
        if save:
            try:
                self._write_index()
            except OSError as e:
                print("shelf not saved:", repr(e), flush=True)

    def select(self, name, on=None):
        """on=None toggles. Only a saved instrument can be selected."""
        entry = self.entries.get(name)
        if entry is not None:
            selected = (not entry.selected) if on is None else bool(on)
            if selected != entry.selected:
                entry.selected = selected
                self._save_index()

    def clear_selection(self):
        changed = False
        for entry in self.entries.values():
            changed |= entry.selected
            entry.selected = False
        if changed:
            self._save_index()

    def selected(self):
        return {n for n, e in self.entries.items() if e.selected}
