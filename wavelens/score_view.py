"""Small score previews for shelf items on the future ending screen."""

import cv2
import numpy as np

from . import config as C


def score_strip(item, bars, width=256, height=56):
    """BGR image: a pitch strip for notes, a 16-step-per-bar grid for drums."""
    if bars < 1 or width < 32 or height < 16:
        raise ValueError("score strip needs positive bars and at least 32x16 pixels")
    image = np.full((height, width, 3), (30, 27, 26), np.uint8)
    grid = (69, 64, 60)
    light = np.array((236, 234, 230), np.float32)

    if item.kind == "rhythm":
        # Rows are bars; the columns are sixteenth-note positions. A kick,
        # snare or hat is a hit in the same grid cell, never a fictitious pitch.
        strength = {}
        for event in item.events:
            key = (event.step // C.STEPS_PER_BAR, event.step % C.STEPS_PER_BAR)
            strength[key] = max(strength.get(key, 0.0), event.velocity)
        for bar in range(bars):
            y0 = bar * height // bars
            y1 = (bar + 1) * height // bars - 1
            for beat in range(C.STEPS_PER_BAR):
                x0 = beat * width // C.STEPS_PER_BAR
                x1 = (beat + 1) * width // C.STEPS_PER_BAR - 1
                cv2.rectangle(image, (x0, y0), (x1, y1), grid, 1)
                velocity = strength.get((bar, beat), 0.0)
                if velocity:
                    value = tuple(int(v) for v in (light * (0.35 + 0.65 * velocity)))
                    cv2.rectangle(image, (x0 + 2, y0 + 2), (max(x0 + 2, x1 - 2), max(y0 + 2, y1 - 2)),
                                  value, -1)
        return image

    for bar in range(1, bars):
        x = bar * width // bars
        cv2.line(image, (x, 0), (x, height - 1), grid, 1)
    notes = [event.note for event in item.events if isinstance(event.note, int)]
    if not notes:
        return image
    lo, hi = min(notes), max(notes)
    span = max(hi - lo, 1)
    total_steps = bars * C.STEPS_PER_BAR
    for event in item.events:
        if not isinstance(event.note, int):
            continue
        x0 = round((event.step + event.delay_steps) * width / total_steps)
        x1 = round((event.step + event.delay_steps + event.duration_steps) * width / total_steps)
        y = round((hi - event.note) * (height - 5) / span) + 2
        value = tuple(int(v) for v in (light * (0.35 + 0.65 * event.velocity)))
        cv2.rectangle(image, (min(x0, width - 1), y),
                      (min(max(x0 + 2, x1), width - 1), min(y + 2, height - 1)), value, -1)
    return image
