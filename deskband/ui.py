"""Rendering: desaturated duotone base, colour kept inside detected objects,
1px rounded outlines, SF Pro labels, a frosted band card, colour-filtered shelf
thumbnails and a shutter button.
Pure functions over numpy frames; no OpenCV GUI calls here."""

import math

import cv2
import numpy as np
from PIL import Image, ImageFont, ImageDraw

from . import config as C

SF_FONT = "/System/Library/Fonts/SFNS.ttf"
WHITE = np.array((255, 255, 255), np.float32)
TONE_DARK = np.array((30, 27, 26), np.float32)      # BGR, warm near-black
TONE_LIGHT = np.array((236, 234, 230), np.float32)

# ------------------------------------------------------------- text ----

_fonts = {}
_text_cache = {}


def _font(size, weight):
    key = (size, weight)
    if key not in _fonts:
        try:
            f = ImageFont.truetype(SF_FONT, size)
            try:
                f.set_variation_by_name(weight)
            except Exception:
                pass
        except OSError:
            f = ImageFont.load_default(size)
        _fonts[key] = f
    return _fonts[key]


def text_mask(s, size, weight="Regular"):
    """-> (alpha float32 HxW, left bearing, top bearing). Cached per string."""
    key = (s, size, weight)
    m = _text_cache.get(key)
    if m is None:
        f = _font(size, weight)
        l, t, r, b = f.getbbox(s)
        w, h = max(r - l, 1), max(b - t, 1)
        im = Image.new("L", (w + 2, h + 2), 0)
        ImageDraw.Draw(im).text((1 - l, 1 - t), s, font=f, fill=255)
        m = (np.asarray(im).astype(np.float32) / 255.0, l - 1, t - 1)
        if len(_text_cache) > 400:
            _text_cache.clear()
        _text_cache[key] = m
    return m


def wrap(s, size, width, weight="Regular"):
    """Greedy word wrap to `width` px -> list of lines."""
    f = _font(size, weight)
    lines, line = [], ""
    for word in s.split():
        trial = f"{line} {word}" if line else word
        if line and f.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def text(img, s, x, y, size, alpha=1.0, weight="Regular", color=WHITE, align="left"):
    """Draw s with its top-left at (x, y). Returns the advance width."""
    if not s:
        return 0
    a, l, t = text_mask(s, size, weight)
    h, w = a.shape
    width = w + l
    if align == "right":
        x -= width
    elif align == "center":
        x -= width / 2
    x0, y0 = int(round(x)) + l, int(round(y)) + t
    H, W = img.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xb > xa and yb > ya:
        aa = a[ya - y0:yb - y0, xa - x0:xb - x0, None] * alpha
        roi = img[ya:yb, xa:xb]
        roi[:] = (color * aa + roi * (1 - aa)).astype(np.uint8)
    return width


# ----------------------------------------------------------- shapes ----

def _blend(img, mask, color, alpha, x0, y0):
    """Alpha-blend `color` where `mask` (float 0..1) says, placed at x0,y0."""
    h, w = mask.shape
    H, W = img.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xb <= xa or yb <= ya:
        return
    a = mask[ya - y0:yb - y0, xa - x0:xb - x0, None] * alpha
    roi = img[ya:yb, xa:xb]
    roi[:] = (color * a + roi * (1 - a)).astype(np.uint8)


def rounded_mask(w, h, r):
    m = np.zeros((h, w), np.uint8)
    r = int(max(1, min(r, w // 2, h // 2)))
    cv2.rectangle(m, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(m, (0, r), (w - 1, h - r - 1), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m


def outline(img, x0, y0, x1, y1, r, alpha, thickness=1, color=WHITE):
    """1px rounded rectangle outline, anti-aliased, alpha blended."""
    w, h = x1 - x0, y1 - y0
    if w < 4 or h < 4:
        return
    pad = thickness + 2
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    r = int(max(2, min(r, w // 2, h // 2)))
    ax0, ay0, ax1, ay1 = pad, pad, pad + w - 1, pad + h - 1
    cv2.line(m, (ax0 + r, ay0), (ax1 - r, ay0), 255, thickness, cv2.LINE_AA)
    cv2.line(m, (ax0 + r, ay1), (ax1 - r, ay1), 255, thickness, cv2.LINE_AA)
    cv2.line(m, (ax0, ay0 + r), (ax0, ay1 - r), 255, thickness, cv2.LINE_AA)
    cv2.line(m, (ax1, ay0 + r), (ax1, ay1 - r), 255, thickness, cv2.LINE_AA)
    for cx, cy, a0 in ((ax0 + r, ay0 + r, 180), (ax1 - r, ay0 + r, 270),
                       (ax0 + r, ay1 - r, 90), (ax1 - r, ay1 - r, 0)):
        cv2.ellipse(m, (cx, cy), (r, r), 0, a0, a0 + 90, 255, thickness, cv2.LINE_AA)
    # blend only the ring: four strips instead of the whole (mostly empty) box
    m = m.astype(np.float32) / 255.0
    band = r + pad + 1
    Hm, Wm = m.shape
    ox, oy = x0 - pad, y0 - pad
    _blend(img, m[:band], color, alpha, ox, oy)
    _blend(img, m[Hm - band:], color, alpha, ox, oy + Hm - band)
    _blend(img, m[band:Hm - band, :band], color, alpha, ox, oy + band)
    _blend(img, m[band:Hm - band, Wm - band:], color, alpha, ox + Wm - band, oy + band)


def frosted(img, x0, y0, x1, y1, r=14, darken=0.45, blur=21):
    """Frosted-glass card: blur the region, darken it, keep rounded corners."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = img[y0:y1, x0:x1]
    # blur at quarter resolution: same look, a fraction of the cost
    small = cv2.resize(roi, ((x1 - x0) // 4 + 1, (y1 - y0) // 4 + 1), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), blur / 4)
    soft = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    soft = (soft.astype(np.float32) * (1 - darken) + TONE_DARK * darken * 0.6).astype(np.uint8)
    m = rounded_mask(x1 - x0, y1 - y0, r).astype(np.float32)[:, :, None] / 255.0
    roi[:] = (soft * m + roi * (1 - m)).astype(np.uint8)
    outline(img, x0, y0, x1, y1, r, 0.18)


def circle(img, cx, cy, radius, alpha, thickness=2, color=WHITE):
    pad = int(radius) + max(thickness, 1) + 2
    layer = np.zeros((2 * pad + 1, 2 * pad + 1), np.uint8)
    cv2.circle(layer, (pad, pad), int(radius), 255, thickness, cv2.LINE_AA)
    _blend(img, layer.astype(np.float32) / 255.0, color, alpha, int(cx) - pad, int(cy) - pad)


def polygon(img, points, alpha, color=WHITE):
    """Filled, anti-aliased polygon."""
    pts = np.array(points, np.int32)
    x0, y0 = pts.min(axis=0) - 2
    x1, y1 = pts.max(axis=0) + 3
    layer = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(layer, [pts - (x0, y0)], 255, cv2.LINE_AA)
    _blend(img, layer.astype(np.float32) / 255.0, color, alpha, int(x0), int(y0))


# ------------------------------------------------------------ base ----

def _duotone_lut():
    t = (np.arange(256, dtype=np.float32) / 255.0)[:, None]
    t = t ** 1.05
    return np.clip(TONE_DARK * (1 - t) + TONE_LIGHT * t, 0, 255).astype(np.uint8)


LUT = _duotone_lut()


def hex_bgr(s):
    """'#RRGGBB' -> BGR float32."""
    s = s.lstrip("#")
    return np.array((int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16)), np.float32)


def tint(bgr, color, strength=0.78):
    """Colour filter over a picture: its brightness re-lit in one hue (a deep shade
    of `color` in the shadows, a pale one in the highlights), laid over the
    original at `strength`, so every thumbnail reads as its instrument's colour.
    -> float32 BGR."""
    c = hex_bgr(color)
    luma = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)[:, :, None] / 255.0
    filt = c * 0.20 * (1 - luma) + (c + (255 - c) * 0.35) * luma
    return bgr.astype(np.float32) * (1 - strength) + filt * strength


def picture(img, src, mask, x0, y0, alpha=1.0):
    """Alpha-blend a small picture (float32 BGR) through `mask` (float 0..1) at x0,y0."""
    h, w = mask.shape
    H, W = img.shape[:2]
    xa, ya, xb, yb = max(x0, 0), max(y0, 0), min(x0 + w, W), min(y0 + h, H)
    if xb <= xa or yb <= ya:
        return
    a = mask[ya - y0:yb - y0, xa - x0:xb - x0, None] * alpha
    roi = img[ya:yb, xa:xb]
    roi[:] = (src[ya - y0:yb - y0, xa - x0:xb - x0] * a + roi * (1 - a)).astype(np.uint8)


class Base:
    """Duotone + vignette for a fixed frame size (LUTs built once)."""

    def __init__(self, W, H):
        self.W, self.H = W, H
        self.lut = LUT
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx / W - 0.5) * 2) ** 2 + ((yy / H - 0.5) * 2) ** 2)
        vig = np.clip(1 - 0.28 * np.clip(d - 0.55, 0, 1.5), 0, 1)
        self.vignette = np.repeat((vig * 255).astype(np.uint8)[:, :, None], 3, axis=2)

    def render(self, frame, dim=0.0):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        out = cv2.LUT(cv2.merge([gray, gray, gray]), self.lut.reshape(1, 256, 3))
        return cv2.multiply(out, self.vignette, scale=(1 - dim) / 255.0)


def keep_colour(out, frame, x0, y0, x1, y1, r, alpha):
    """Restore the original colour inside a rounded box (the object 'lit up')."""
    w, h = x1 - x0, y1 - y0
    if w < 4 or h < 4:
        return
    m = cv2.GaussianBlur(rounded_mask(w, h, r), (0, 0), 1.0).astype(np.float32) / 255.0
    a = m[:, :, None] * alpha
    roi = out[y0:y1, x0:x1]
    src = frame[y0:y1, x0:x1].astype(np.float32)
    # slightly lifted, slightly desaturated colour reads as "lit" rather than raw webcam
    g = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)[:, :, None].astype(np.float32)
    src = src * 0.8 + g * 0.2
    roi[:] = np.clip(src * 1.05 * a + roi * (1 - a), 0, 255).astype(np.uint8)


def ease(cur, target, dt, tau):
    if cur is None:
        return target
    k = 1 - math.exp(-dt / max(tau, 1e-3))
    return cur + (target - cur) * k
