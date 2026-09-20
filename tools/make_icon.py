"""Build WaveLens.icns from the supplied app icon. Usage: make_icon.py out.icns"""

from io import BytesIO
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image


SOURCE = os.path.join(os.path.dirname(__file__), "..", "assets", "wavelens_icon.png")


def icon_image():
    """Make the dark corners outside the white rounded square transparent."""
    pixels = np.array(Image.open(SOURCE).convert("RGBA"))
    gray = cv2.cvtColor(pixels[:, :, :3], cv2.COLOR_RGB2GRAY)
    bright = (gray >= 245).astype(np.uint8)
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    shape = max(contours, key=cv2.contourArea)
    alpha = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(alpha, [shape], -1, 255, -1)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.8)
    pixels[alpha < 255, :3] = 255
    pixels[:, :, 3] = alpha
    return Image.fromarray(pixels, "RGBA")


def main(out):
    image = icon_image()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "WaveLens.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            image.resize((base, base), Image.Resampling.LANCZOS).save(
                os.path.join(iconset, f"icon_{base}x{base}.png"))
            image.resize((base * 2, base * 2), Image.Resampling.LANCZOS).save(
                os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
        try:
            subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out],
                           check=True, capture_output=True)
        except subprocess.CalledProcessError:
            # iconutil sometimes rejects a valid iconset in restricted builds.
            chunks = bytearray()
            for size, code in ((16, b"icp4"), (32, b"icp5"), (64, b"icp6"),
                               (128, b"ic07"), (256, b"ic08"),
                               (512, b"ic09"), (1024, b"ic10")):
                buffer = BytesIO()
                image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
                data = buffer.getvalue()
                chunks.extend(code + (len(data) + 8).to_bytes(4, "big") + data)
            with open(out, "wb") as result:
                result.write(b"icns" + (len(chunks) + 8).to_bytes(4, "big") + chunks)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "WaveLens.icns")
