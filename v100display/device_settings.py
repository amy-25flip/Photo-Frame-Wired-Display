# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional device settings applied at every plug-in, right after the stage-1 stub is up (before the loading picture).

settings.json (next to this file; see settings.example.json):
  brightness  1..100   backlight, percent of the stub's default PWM duty (63/64). Lower = less current: helps on bus-powered USB hubs, where supply sag
                       shows up as backlight flicker.
  cpu_mhz     240..360 CPU clock via the core PLL multiplier (CMU 0xB0010100 low byte, 6 MHz steps, stock 60 = 360 MHz). Lower = cooler. Measured on a direct USB
                       port with the 12-bit decoder: 360 MHz = 33.3 fps, 336 = 31.9, 324 = 31.0, 312 = 30.0, 300 = 29.4 (the mirror caps at 30 fps).
Every value is verified by readback; the clock is only touched when the PLL is at its stock value and is never raised above stock.
"""
import json
from pathlib import Path

PWM_BACKLIGHT = 0xB01C004C        # GPIO PWM3_CTL: bits[5:0] duty (0..63), bit 8 polarity (stub default 0x13F)
PLL_CORE = 0xB0010100             # CMU core PLL: low byte = multiplier
STOCK_MULT = 60


def load_settings(directory=None):
    p = Path(directory or Path(__file__).resolve().parent) / "settings.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def brightness_duty(percent):
    """percent (clamped 5..100) -> PWM duty 1..63."""
    pct = max(5, min(100, int(percent)))
    return max(1, min(63, round(pct * 63 / 100)))


def pll_multiplier(mhz):
    """MHz (clamped 240..360) -> PLL multiplier 40..60."""
    return max(40, min(60, round(int(mhz) / 6)))


def apply_brightness(dev, settings, xq, log=print):
    if "brightness" not in settings:
        return
    try:
        pct = int(settings["brightness"])
    except (TypeError, ValueError):
        return
    duty = brightness_duty(pct)
    dev.write(1, bytes(512), timeout=4000)
    xq.cmd(dev, pokes=[(PWM_BACKLIGHT, 0x100 | duty)])
    log("BACKLIGHT: %d%% (PWM duty %d/64)" % (max(5, min(100, pct)), duty))


def apply_clock(dev, settings, xq, log=print):
    if "cpu_mhz" not in settings:
        return
    try:
        n = pll_multiplier(settings["cpu_mhz"])
    except (TypeError, ValueError):
        return
    dev.write(1, bytes(512), timeout=4000)
    old = xq.cmd(dev, peeks=[PLL_CORE, 0, 0, 0])[0]
    if (old & 0xFF) != STOCK_MULT:
        log("CPU CLOCK: PLL multiplier is %d (not the stock %d): left alone" % (old & 0xFF, STOCK_MULT))
        return
    if n == STOCK_MULT:
        return
    xq.cmd(dev, pokes=[(PLL_CORE, (old & ~0xFF) | n)])
    now = xq.cmd(dev, peeks=[PLL_CORE, 0, 0, 0])[0]
    if (now & 0xFF) != n:
        xq.cmd(dev, pokes=[(PLL_CORE, old)])
        log("CPU CLOCK: readback mismatch (0x%X), stock clock restored" % now)
        return
    log("CPU CLOCK: %d MHz (PLL multiplier %d)" % (n * 6, n))
