# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot picture from the frame's SPI flash (see tools/v100-boot/pic_flash.py), run inside the WSL ROM-upload session right after the stage-1
stub is ready.  If a valid V1PIC JPEG is stored, it is converted (by Windows Python, which has OpenCV) into assets/loading.{png,rgb565,c444}, the files
show_loading.py and frame_sender.py already use.  With no stored picture, assets that an earlier sync replaced are restored.  Never raises."""
import subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'assets'
MARK = ASSETS / '.from_flash'


def _win(path):
    p = str(path)
    return p[5].upper() + ':' + p[6:].replace('/', '\\') if p.startswith('/mnt/') and len(p) > 6 and p[6] == '/' else p


def _run_set_boot_image(win_python, *args):
    r = subprocess.run([win_python, '-W', 'ignore', _win(HERE / 'set_boot_image.py'), *args], capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


def sync(dev, win_python, log=print):
    t = time.monotonic()
    try:
        sys.path.insert(0, str(HERE.parent / 'flash'))
        import xq_load as x
        import pic_flash
        dev.write(1, bytes(512), timeout=4000)
        x.cmd(dev)
        x.cmd(dev)
        pic = pic_flash.read_picture(dev)
        if pic:
            jpg = ASSETS / 'flash_picture.jpg'
            jpg.write_bytes(pic)
            code, out = _run_set_boot_image(win_python, _win(jpg), '--fit', 'stretch')
            if code:
                log('flash picture could not be converted:', out[-200:])
                return False
            MARK.write_text('flash')
            log('FLASH_PICTURE: %d byte JPEG read from the frame flash and applied in %.2f s' % (len(pic), time.monotonic() - t))
            return True
        if MARK.exists():
            code, out = _run_set_boot_image(win_python, '--restore')
            MARK.unlink()
            log('no picture in flash: built-in artwork restored (%s)' % out[-80:])
        else:
            log('no picture stored in flash: using the built-in artwork')
        return False
    except Exception as ex:                                    # the boot sequence must never fail because of this
        log('flash picture unavailable:', ex)
        return False
