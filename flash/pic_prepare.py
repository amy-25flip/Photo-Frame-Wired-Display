# SPDX-License-Identifier: GPL-2.0-or-later
"""Picture -> 1024x600 JPEG payload (<= max_bytes). Needs OpenCV (Windows frame-venv has it; the WSL venv does not).
    python pic_prepare.py in.png out.jpg [--fit contain|cover|stretch] [--max 479216] [--quality N]"""
import argparse, sys
import cv2, numpy as np


def make_jpeg(picture, fit='contain', max_bytes=479216, quality=None):
    img = cv2.imdecode(np.fromfile(picture, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None: raise SystemExit('cannot read %s as an image' % picture)
    h, w = img.shape[:2]
    if fit == 'stretch':
        out = cv2.resize(img, (1024, 600), interpolation=cv2.INTER_AREA)
    else:
        s = (max if fit == 'cover' else min)(1024 / w, 600 / h)
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        out = np.zeros((600, 1024, 3), np.uint8)
        x0, y0 = (1024 - nw) // 2, (600 - nh) // 2
        sx, sy = max(0, -x0), max(0, -y0)
        out[max(0, y0):max(0, y0) + min(600, nh), max(0, x0):max(0, x0) + min(1024, nw)] = r[sy:sy + min(600, nh), sx:sx + min(1024, nw)]
    for q in ([quality] if quality else [95, 92, 90, 85, 80, 75, 70, 60, 50]):
        ok, enc = cv2.imencode('.jpg', out, [cv2.IMWRITE_JPEG_QUALITY, q, cv2.IMWRITE_JPEG_OPTIMIZE, 1])
        if ok and len(enc) <= max_bytes:
            return bytes(enc), q
    raise SystemExit('picture does not fit in %d bytes even at quality 50' % max_bytes)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('picture'); ap.add_argument('out')
    ap.add_argument('--fit', default='contain'); ap.add_argument('--max', type=int, default=479216); ap.add_argument('--quality', type=int)
    a = ap.parse_args()
    data, q = make_jpeg(a.picture, a.fit, a.max, a.quality)
    open(a.out, 'wb').write(data)
    print('quality %d, %d bytes' % (q, len(data)))
