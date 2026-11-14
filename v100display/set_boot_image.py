#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Set ANY picture as the frame's boot/loading picture (shown from plug-in until the Windows desktop appears).

    python set_boot_image.py picture.jpg [--fit contain|cover|stretch] [--background 000000]
    python set_boot_image.py --restore              # back to the original Pixel Portal artwork

Converts the picture to 1024x600, dithered RGB444 (exactly what the panel decoder shows) and writes assets/loading.png, loading.rgb565 and loading.c444,
the three files the watcher/sender use.  The originals are backed up once in assets/default/.  Takes effect at the next plug-in.
"""
import argparse, shutil, sys
from pathlib import Path
import cv2
import numpy as np
import c444

ASSETS = Path(__file__).resolve().parent / "assets"
DEFAULT = ASSETS / "default"
FILES = ("loading.png", "loading.rgb565", "loading.c444", "loading-panel-preview.png")


def fit(img, mode, bg):
    h, w = img.shape[:2]
    if mode == "stretch":
        return cv2.resize(img, (1024, 600), interpolation=cv2.INTER_AREA)
    s = (max if mode == "cover" else min)(1024 / w, 600 / h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    canvas = np.full((600, 1024, 3), bg, dtype=np.uint8)
    x0, y0 = (1024 - nw) // 2, (600 - nh) // 2
    sx, sy = max(0, -x0), max(0, -y0)
    canvas[max(0, y0):max(0, y0) + min(600, nh), max(0, x0):max(0, x0) + min(1024, nw)] = r[sy:sy + min(600, nh), sx:sx + min(1024, nw)]
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("picture", nargs="?")
    ap.add_argument("--fit", choices=("contain", "cover", "stretch"), default="contain")
    ap.add_argument("--background", default="000000")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    if not DEFAULT.exists():
        DEFAULT.mkdir()
        for f in FILES:
            if (ASSETS / f).exists():
                shutil.copy2(ASSETS / f, DEFAULT / f)
        print("backed up the original artwork to", DEFAULT)
    if a.restore:
        for f in FILES:
            if (DEFAULT / f).exists():
                shutil.copy2(DEFAULT / f, ASSETS / f)
        print("restored the original boot picture")
        return
    if not a.picture:
        ap.error("give a picture (or --restore)")
    data = np.fromfile(a.picture, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit("cannot read %s as an image" % a.picture)
    bg = tuple(int(a.background[i:i + 2], 16) for i in (4, 2, 0))          # BGR
    rgb = cv2.cvtColor(fit(img, a.fit, bg), cv2.COLOR_BGR2RGB)
    packed = c444.encode(rgb, dither=True)
    preview = c444.decode_ref(packed, 1024 * 600).reshape(600, 1024)
    (ASSETS / "loading.c444").write_bytes(packed)
    (ASSETS / "loading.rgb565").write_bytes(preview.astype("<u2").tobytes())
    cv2.imwrite(str(ASSETS / "loading.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    r5, g6, b5 = (preview >> 11) & 31, (preview >> 5) & 63, preview & 31
    prev = np.stack([(r5 << 3 | r5 >> 2), (g6 << 2 | g6 >> 4), (b5 << 3 | b5 >> 2)], axis=-1).astype(np.uint8)
    cv2.imwrite(str(ASSETS / "loading-panel-preview.png"), cv2.cvtColor(prev, cv2.COLOR_RGB2BGR))
    print("boot picture set from %s (%s); it appears at the next plug-in" % (a.picture, a.fit))


if __name__ == "__main__":
    main()
