# SPDX-License-Identifier: GPL-2.0-or-later
"""c444 12-bit codec: packing, reference decoder and the exact stream geometry the on-device decoder expects."""
import sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v100display"))
import c444


class CodecTests(unittest.TestCase):
    def test_geometry(self):
        self.assertEqual(c444.NPKT, 1829)
        self.assertEqual(c444.GROUPS_PER_PKT * 8, 336)

    def test_pack_unpack_roundtrip(self):
        rng = np.random.default_rng(1)
        rgb = rng.integers(0, 256, size=(c444.H, c444.W, 3), dtype=np.uint8)
        codes = c444.quantize(rgb)
        packed = c444.pack(codes)
        self.assertEqual(len(packed), c444.NPKT * c444.PKT)
        self.assertTrue(np.array_equal(c444.decode_ref(packed, c444.W * c444.H), c444.make_lut()[codes]))

    def test_white_and_black_are_exact(self):
        lut = c444.make_lut()
        self.assertEqual(int(lut[0x000]), 0x0000)
        self.assertEqual(int(lut[0xFFF]), 0xFFFF)

    def test_padding_bytes_are_zero(self):
        packed = c444.encode(np.full((c444.H, c444.W, 3), 255, dtype=np.uint8))
        pkt = np.frombuffer(packed, dtype=np.uint8).reshape(-1, c444.PKT)
        self.assertTrue(not pkt[:, 504:].any())


if __name__ == "__main__":
    unittest.main()
