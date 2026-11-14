# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the two on-device programs in the Unicorn MIPS emulator (needs the `unicorn` package):
stage 1 (display bring-up, USB packet receiver, 'V1XQ' loader) and stage 2 (DMA + 12-bit decoder, bit-exact against c444.decode_ref)."""
import subprocess, sys, unittest
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "v100display"
try:
    import unicorn  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False


def run(script):
    r = subprocess.run([sys.executable, str(PKG / script), "sim"], capture_output=True, text=True, timeout=600, cwd=str(PKG))
    return r.returncode, r.stdout + r.stderr


@unittest.skipUnless(HAVE, "unicorn not installed")
class SimTests(unittest.TestCase):
    def test_stage1(self):
        rc, out = run("stage1.py")
        self.assertEqual(rc, 0, out[-600:])
        self.assertIn("XQ loader: blob ran", out)
        self.assertIn("dirty-DDR startup: both framebuffers cleared before LCD setup: True", out)
        for line in out.splitlines():
            if line.startswith(("frame 1 landed", "frame 2", "second band", "rows just outside", "bytes past FB1", "XQ loader", "exactly one flip")):
                self.assertNotIn("False", line, line)

    def test_committed_stage1_binary_is_reproducible(self):
        """stage1-clean.bin (what gets uploaded to the frame) must be exactly what stage1.py generates."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "stage1.bin")
            r = subprocess.run([sys.executable, str(PKG / "stage1.py"), "dump", out], capture_output=True, text=True, timeout=120, cwd=str(PKG))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(open(out, "rb").read(), (PKG / "stage1-clean.bin").read_bytes())

    def test_stage2_decoder(self):
        rc, out = run("s2_c444.py")
        self.assertEqual(rc, 0, out[-600:])
        self.assertIn("frame 1 decoded == reference: True", out)
        self.assertIn("frame 2 decoded == reference: True", out)


if __name__ == "__main__":
    unittest.main()
