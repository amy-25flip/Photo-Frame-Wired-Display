# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep ROM upload and stream ownership in separate libusb sessions.
Usage (run by the watcher inside WSL): load_clean_receiver.py [--win-python /mnt/.../python.exe]
Order: upload stage 1 -> optional settings (settings.json: cpu_mhz, brightness) -> optional flash picture (--win-python) -> loading picture."""
import sys
from fast_bootstrap import load
from show_loading import show

dev=load()
try:
    import device_settings, xq_load
    cfg=device_settings.load_settings()
    device_settings.apply_clock(dev,cfg,xq_load)
    device_settings.apply_brightness(dev,cfg,xq_load)
except Exception as ex:print('device settings step skipped:',ex,flush=True)
if '--win-python' in sys.argv:
    try:
        import flash_boot_picture;flash_boot_picture.sync(dev,sys.argv[sys.argv.index('--win-python')+1])
    except Exception as ex:print('flash picture step skipped:',ex,flush=True)
show(dev)
print('stub loaded and running',flush=True)
