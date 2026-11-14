# SPDX-License-Identifier: GPL-2.0-or-later
"""Show the complete loading image through stage 1 before decoder startup."""
from pathlib import Path
import time
import xq_load as x

def show(dev):
    t=time.monotonic()
    raw=(Path(__file__).parent/'assets'/'loading.rgb565').read_bytes()
    if len(raw)!=1024*600*2:raise RuntimeError('Incorrect raw loading frame size')
    dev.write(1,bytes(512),timeout=4000)
    x.cmd(dev,pokes=[(0xB02F0040,0x40000),(0xB02F0070,512)])
    header=x.pkt(x.MAGIC[0],band=(0,600))
    dev.write(1,header+raw,timeout=10000)
    tag,_=x.rd(dev,5000)
    if tag!=b'FMR4':raise RuntimeError('Raw loading picture not acknowledged: '+repr(tag))
    print('EARLY_LOADING_PICTURE: acknowledged in %.3fs'%(time.monotonic()-t),flush=True)

if __name__=='__main__':
    show(x.open_frame())
