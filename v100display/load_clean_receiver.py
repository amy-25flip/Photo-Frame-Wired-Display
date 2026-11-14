# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep ROM upload and stream ownership in separate libusb sessions.
Usage (run by the watcher inside WSL): load_clean_receiver.py [--win-python /mnt/.../python.exe]
With --win-python, a boot picture stored in the frame's flash (flash/pic_flash.py) is applied before the loading picture is shown."""
import sys
from fast_bootstrap import load
from show_loading import show
dev=load()
if '--win-python' in sys.argv:
    try:
        import flash_boot_picture;flash_boot_picture.sync(dev,sys.argv[sys.argv.index('--win-python')+1])
    except Exception as ex:print('flash picture step skipped:',ex,flush=True)
show(dev)
print('stub loaded and running',flush=True)
