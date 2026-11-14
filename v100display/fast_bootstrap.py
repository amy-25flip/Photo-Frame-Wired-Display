# SPDX-License-Identifier: GPL-2.0-or-later
"""Load the clean-framebuffer RAM receiver and wait for its actual ready ack."""
from pathlib import Path
import time

def load():
    from adfu_tool.device import open_single_adfu
    from adfu_tool.protocol import Session, SUCCESS_CSW
    from adfu_tool.codec import encode
    t=time.monotonic()
    dev=open_single_adfu()
    session=Session(dev,overall_timeout=30,operation_timeout=5)
    session.getinfo()
    image=(Path(__file__).parent/'stage1-clean.bin').read_bytes()
    if len(image)!=2048:raise RuntimeError('Unexpected stage-1 size')
    session.upload(encode(image));session.execute()
    for _ in range(3):
        raw=bytes(dev.device.read(0x82,512,timeout=5000))
        if raw==SUCCESS_CSW:continue
        if len(raw)==32 and raw[:4]==b'RDY1':
            print('RAM_LOADER_READY: %.3fs (buffers cleared before panel enable)'%(time.monotonic()-t),flush=True)
            return dev.device
        raise RuntimeError('Unexpected loader response: '+repr(raw[:32]))
    raise RuntimeError('Missing RAM-loader ready ack')
