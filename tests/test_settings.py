# SPDX-License-Identifier: GPL-2.0-or-later
"""device_settings: value mapping and the safety rules around the PLL/backlight pokes (mock frame, no hardware)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "v100display"))
import device_settings as ds


class FakeDev:
    def __init__(self): self.writes = []
    def write(self, ep, data, timeout=0): self.writes.append((ep, len(data)))


class FakeXq:
    """cmd(dev, pokes=, peeks=): records pokes; a peek of the PLL returns the current simulated register."""
    def __init__(self, pll, accept=True):
        self.pll, self.accept, self.pokes = pll, accept, []
    def cmd(self, dev, pokes=(), peeks=()):
        for a, v in pokes:
            self.pokes.append((a, v))
            if a == ds.PLL_CORE and self.accept:
                self.pll = v
        return [self.pll if peeks and peeks[0] == ds.PLL_CORE else 0, 0, 0, 0]


class SettingsTests(unittest.TestCase):
    def test_brightness_mapping(self):
        self.assertEqual(ds.brightness_duty(100), 63)
        self.assertEqual(ds.brightness_duty(75), 47)
        self.assertEqual(ds.brightness_duty(1), 3)          # clamped to 5 %
        self.assertEqual(ds.brightness_duty(500), 63)

    def test_clock_mapping_never_exceeds_stock(self):
        self.assertEqual(ds.pll_multiplier(324), 54)
        self.assertEqual(ds.pll_multiplier(1000), 60)
        self.assertEqual(ds.pll_multiplier(10), 40)

    def test_load_settings_missing_or_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ds.load_settings(d), {})
            (Path(d) / "settings.json").write_text("not json")
            self.assertEqual(ds.load_settings(d), {})
            (Path(d) / "settings.json").write_text('{"brightness": 80}')
            self.assertEqual(ds.load_settings(d), {"brightness": 80})

    def test_clock_applied_only_from_stock_and_preserves_other_bits(self):
        x = FakeXq(0x0D3C)
        ds.apply_clock(FakeDev(), {"cpu_mhz": 324}, x, log=lambda *a: None)
        self.assertEqual(x.pokes, [(ds.PLL_CORE, 0x0D36)])

    def test_clock_left_alone_when_pll_is_not_stock(self):
        x = FakeXq(0x0D30)
        ds.apply_clock(FakeDev(), {"cpu_mhz": 324}, x, log=lambda *a: None)
        self.assertEqual(x.pokes, [])

    def test_clock_readback_mismatch_restores_stock(self):
        x = FakeXq(0x0F3C, accept=False)
        ds.apply_clock(FakeDev(), {"cpu_mhz": 300}, x, log=lambda *a: None)
        self.assertEqual(x.pokes[-1], (ds.PLL_CORE, 0x0F3C))

    def test_no_keys_means_no_pokes(self):
        x = FakeXq(0x0F3C)
        ds.apply_clock(FakeDev(), {}, x); ds.apply_brightness(FakeDev(), {}, x)
        self.assertEqual(x.pokes, [])

    def test_brightness_poke(self):
        x = FakeXq(0x0F3C)
        ds.apply_brightness(FakeDev(), {"brightness": 75}, x, log=lambda *a: None)
        self.assertEqual(x.pokes, [(ds.PWM_BACKLIGHT, 0x100 | 47)])


if __name__ == "__main__":
    unittest.main()
