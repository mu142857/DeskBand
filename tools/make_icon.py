"""Draw the app icon (dark rounded square, three lit objects on a desk line)
and build DeskBand.icns with iconutil. Usage: make_icon.py out.icns"""

import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter


def draw(size):
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(s * 0.22)
    d.rounded_rectangle((0, 0, s - 1, s - 1), r, fill=(30, 27, 26, 255))
    # desk line
    y = int(s * 0.66)
    d.line((int(s * 0.18), y, int(s * 0.82), y), fill=(236, 234, 230, 110), width=max(1, s // 64))
    # three objects: a tall one, a round one, a small one - each glowing
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    shapes = [
        ("rect", (0.22, 0.34, 0.40, 0.66)),
        ("ellipse", (0.46, 0.44, 0.64, 0.66)),
        ("rect", (0.70, 0.52, 0.78, 0.66)),
    ]
    for kind, (x0, y0, x1, y1) in shapes:
        box = (int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s))
        if kind == "rect":
            g.rounded_rectangle(box, max(2, s // 40), fill=(236, 234, 230, 255))
        else:
            g.ellipse(box, fill=(236, 234, 230, 255))
    halo = glow.filter(ImageFilter.GaussianBlur(s * 0.05))
    halo.putalpha(halo.getchannel("A").point(lambda a: int(a * 0.45)))
    im.alpha_composite(halo)
    im.alpha_composite(glow)
    return im


def main(out):
    tmp = tempfile.mkdtemp()
    iconset = os.path.join(tmp, "DeskBand.iconset")
    os.makedirs(iconset)
    for base in (16, 32, 128, 256, 512):
        draw(base).save(os.path.join(iconset, f"icon_{base}x{base}.png"))
        draw(base * 2).save(os.path.join(iconset, f"icon_{base}x{base}@2x.png"))
    try:
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out],
                       check=True, capture_output=True)
    except subprocess.CalledProcessError:
        # iconutil sometimes rejects a valid iconset in restricted build
        # environments. An ICNS container can also hold the same PNG images.
        chunks = bytearray()
        for size, code in ((16, b"icp4"), (32, b"icp5"), (64, b"icp6"),
                           (128, b"ic07"), (256, b"ic08"),
                           (512, b"ic09"), (1024, b"ic10")):
            png = draw(size)
            from io import BytesIO
            buffer = BytesIO()
            png.save(buffer, format="PNG")
            data = buffer.getvalue()
            chunks.extend(code + (len(data) + 8).to_bytes(4, "big") + data)
        with open(out, "wb") as result:
            result.write(b"icns" + (len(chunks) + 8).to_bytes(4, "big") + chunks)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "DeskBand.icns")
