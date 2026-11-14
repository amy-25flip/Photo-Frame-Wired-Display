# SPDX-License-Identifier: GPL-2.0-or-later
"""12-bit (RGB444) packed frame format for the V100 stage-2 decoder.

Pixel code = (R4 << 8) | (G4 << 4) | B4.  Eight pixels = 96 bits = 12 bytes (little endian bit stream, pixel k at bits [12k, 12k+12)).
A 512-byte USB packet carries 42 such groups (336 pixels, 504 bytes) + 8 bytes padding; a 1024x600 frame = 614400 px = 1829 packets
(the last one zero padded).  The stub decodes with a 4096-entry RGB565 lookup table (LUT, 8 KB) that the host uploads with the code.
"""
import numpy as np

W, H = 1024, 600
GROUPS_PER_PKT = 42
PX_PER_PKT = GROUPS_PER_PKT * 8
PKT = 512
NPKT = -(-(W * H) // PX_PER_PKT)             # 1829


def make_lut():
    c = np.arange(4096, dtype=np.uint32)
    r4, g4, b4 = (c >> 8) & 15, (c >> 4) & 15, c & 15
    r5 = (r4 << 1) | (r4 >> 3)
    g6 = (g4 << 2) | (g4 >> 2)
    b5 = (b4 << 1) | (b4 >> 3)
    return ((r5 << 11) | (g6 << 5) | b5).astype("<u2")


_BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32) + 0.5) / 16.0
_THR = None


def _thr(h, w):
    global _THR
    if _THR is None or _THR.shape != (h, w, 1):
        _THR = np.tile(_BAYER4, (-(-h // 4), -(-w // 4)))[:h, :w, None]
    return _THR


def quantize(rgb, dither=True):
    """rgb: (H, W, 3) uint8 in R,G,B order -> (H*W,) uint16 codes."""
    h, w, _ = rgb.shape
    s = rgb.astype(np.float32) * (1.0 / 17.0)
    if dither:
        s = s + _thr(h, w)
    else:
        s = s + 0.5
    q = np.clip(s, 0, 15).astype(np.uint16)              # floor
    return ((q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]).reshape(-1)


def pack(codes):
    """codes: (n,) uint16 -> bytes of NPKT 512-byte packets."""
    total = NPKT * PX_PER_PKT
    c = np.zeros(total, dtype=np.uint32)
    c[:len(codes)] = codes
    c = c.reshape(-1, 8)
    w0 = c[:, 0] | (c[:, 1] << 12) | ((c[:, 2] & 0xFF) << 24)
    w1 = (c[:, 2] >> 8) | (c[:, 3] << 4) | (c[:, 4] << 16) | ((c[:, 5] & 0xF) << 28)
    w2 = (c[:, 5] >> 4) | (c[:, 6] << 8) | (c[:, 7] << 20)
    g = np.ascontiguousarray(np.stack([w0, w1, w2], axis=1).astype("<u4").reshape(NPKT, GROUPS_PER_PKT * 3))
    out = np.zeros((NPKT, PKT), dtype=np.uint8)
    out[:, :GROUPS_PER_PKT * 12] = g.view(np.uint8)
    return out.tobytes()


def encode(rgb, dither=True):
    return pack(quantize(rgb, dither))


def decode_ref(packed, npix=None):
    """Reference decoder (what the stub must produce): bytes -> (n,) uint16 RGB565."""
    lut = make_lut()
    a = np.frombuffer(packed, dtype=np.uint8).reshape(-1, PKT)[:, :GROUPS_PER_PKT * 12].reshape(-1, 12)
    w = a.copy().view("<u4").reshape(-1, 3).astype(np.uint32)
    w0, w1, w2 = w[:, 0], w[:, 1], w[:, 2]
    codes = np.stack([w0 & 0xFFF, (w0 >> 12) & 0xFFF, (w0 >> 24) | ((w1 & 0xF) << 8), (w1 >> 4) & 0xFFF,
                      (w1 >> 16) & 0xFFF, (w1 >> 28) | ((w2 & 0xFF) << 4), (w2 >> 8) & 0xFFF, w2 >> 20], axis=1).reshape(-1)
    px = lut[codes]
    return px if npix is None else px[:npix]
