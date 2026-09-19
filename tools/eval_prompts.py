"""Replay saved photos (cache/shots/*.jpg) through the detector and print what
each prompt finds. Use it to choose prompts, thresholds, input size and model
from real pictures instead of guessing.

  eval_prompts.py                          current config on every saved shot
  eval_prompts.py --prompts "headset,earbuds,airpods case" --conf 0.05
  eval_prompts.py --model yolov8l-worldv2.pt --imgsz 640 960 1280
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from deskband import config as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=C.DETECT_MODEL)
    ap.add_argument("--prompts", help="comma separated; default: the prompts in config.py")
    ap.add_argument("--imgsz", type=int, nargs="+", default=[C.DETECT_IMGSZ, C.SHOOT_IMGSZ])
    ap.add_argument("--conf", type=float, default=0.05, help="list everything above this")
    ap.add_argument("--images", default=os.path.join(C.SHOTS_DIR, "*.jpg"))
    a = ap.parse_args()

    from ultralytics import YOLO
    prompts = [p.strip() for p in a.prompts.split(",")] if a.prompts else C.DETECT_CLASSES
    model = YOLO(a.model)
    model.set_classes(prompts)
    files = sorted(glob.glob(a.images))
    if not files:
        sys.exit(f"no images match {a.images}: take some photos in the app first (space or s)")
    print(f"model {a.model}   prompts {prompts}")
    for f in files:
        frame = cv2.imread(f)
        print(f"\n{os.path.basename(f)}  {frame.shape[1]}x{frame.shape[0]}")
        for size in a.imgsz:
            r = model.predict(frame, device="mps", imgsz=size, conf=a.conf, verbose=False)[0]
            found = sorted(((float(c), model.names[int(k)], [int(v) for v in b.tolist()])
                            for k, c, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xyxy)), reverse=True)
            line = "   ".join(f"{n} {c:.2f}" + ("" if c >= C.DETECT_CONF else "*") for c, n, _ in found[:12])
            print(f"   imgsz {size:4d}: {line or '(nothing)'}")
    print(f"\n* = below the app's threshold ({C.DETECT_CONF})")


if __name__ == "__main__":
    main()
