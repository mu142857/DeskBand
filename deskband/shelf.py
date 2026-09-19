"""The shelf: instruments saved from earlier photos.

Shooting a photo files a thumbnail of the object it found (config.ONE_PER_PHOTO;
every object when that is off); from then on the
instrument can be switched on and off from the shelf without the object being
in front of the camera, so a band is built one photo at a time. The shelf
starts empty and fills in the order things were first shot (one place per
instrument; shooting the same kind of object again replaces its picture but
keeps its place). Kept on disk, so it survives a restart."""

import json
import os
import time

import cv2

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
    def __init__(self, name, shown, conf, thumb, saved_at=None):
        self.name, self.shown, self.conf, self.thumb = name, shown, conf, thumb
        self.saved_at = saved_at or time.time()
        self.selected = False
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
        for name, meta in index.items():
            thumb = cv2.imread(self._image(name))
            if name in self.names and thumb is not None:
                thumb = cv2.resize(thumb, (THUMB, THUMB))
                self.entries[name] = Entry(name, meta.get("shown", name), meta.get("conf", 0.0),
                                           thumb, meta.get("saved_at"))

    def _write_index(self):
        os.makedirs(self.folder, exist_ok=True)
        index = {n: dict(shown=e.shown, conf=round(e.conf, 3), saved_at=e.saved_at)
                 for n, e in self.entries.items()}
        with open(self._index(), "w") as f:
            json.dump(index, f, indent=1)

    # ---------------------------------------------------------- changes
    def add(self, name, shown, conf, frame, box):
        """File (or re-file) an object; the newest photo wins. Returns the entry."""
        if name not in self.names:
            return None
        old = self.entries.get(name)
        entry = Entry(name, shown, conf, crop_square(frame, box), old.saved_at if old else None)
        entry.selected = old.selected if old else False
        self.entries[name] = entry
        try:                                   # a full disk must not stop the show
            os.makedirs(self.folder, exist_ok=True)
            cv2.imwrite(self._image(name), entry.thumb, [cv2.IMWRITE_JPEG_QUALITY, 92])
            self._write_index()
        except OSError as e:
            print("shelf not saved:", repr(e), flush=True)
        return entry

    def remove(self, name):
        if self.entries.pop(name, None) is None:
            return
        try:
            os.remove(self._image(name))
            self._write_index()
        except OSError:
            pass

    def select(self, name, on=None):
        """on=None toggles. Only a saved instrument can be selected."""
        entry = self.entries.get(name)
        if entry is not None:
            entry.selected = (not entry.selected) if on is None else bool(on)

    def clear_selection(self):
        for entry in self.entries.values():
            entry.selected = False

    def selected(self):
        return {n for n, e in self.entries.items() if e.selected}
