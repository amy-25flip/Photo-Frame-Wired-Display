#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Host side of the 'V1XQ' stage-2 loader (stub = stage1.py, resident, frame in ADFU mode, WSL).

    xq_load.py hello          # load + run the tiny test blob (fills the front buffer red, times itself), check it returned
    from xq_load import open_frame, xq_load

xq_load(dev, blob, dest_phys, run=True): sends 'V1XQ' header + the blob as 512-byte packets; the stub copies them to DRAM, invalidates both
caches, then (run=True) calls the blob (kseg0, jalr) and acks 'XQD1' when it returns.  A blob must preserve S0..S7 and return with jr ra.
"""
import struct, sys, time
import usb.core

MAGIC = (0x44483156, 0x5F4D5246, 0xA55AC33C, 0x3CC35AA5)
XQ0, CMD0 = 0x51583156, 0x4D433156
PKT = 512


def open_frame():
    dev = usb.core.find(idVendor=0x10D6, idProduct=0x10D6)
    assert dev is not None, "frame not found"
    try:
        dev.set_configuration()
    except usb.core.USBError:
        pass
    dev.write(1, bytes(PKT), timeout=4000)          # first packet after a fresh load is lost
    return dev


def pkt(word0, band=(0, 0), noflip=0, pokes=(), peeks=(), extra=()):
    w = [word0, MAGIC[1], MAGIC[2], MAGIC[3], 0x89]
    p = list(pokes)[:8]
    for a, v in p:
        w += [a, v]
    w += [0, 0] * (8 - len(p))
    q = list(peeks)[:4]
    w += q + [0] * (4 - len(q))
    w += [0, band[0], band[1], noflip, 0] + list(extra)
    return struct.pack("<%dI" % len(w), *w) + bytes(PKT - 4 * len(w))


def rd(dev, t=3000):
    raw = bytes(dev.read(0x82, 512, timeout=t))
    return raw[:4], struct.unpack("<%dI" % (len(raw) // 4), raw)


def cmd(dev, pokes=(), peeks=()):
    for _ in range(5):
        dev.write(1, pkt(CMD0, pokes=pokes, peeks=peeks), timeout=4000)
        try:
            while True:
                tag, w = rd(dev, 1500)
                if tag == b"CMD1":
                    return list(w[4:8])
        except usb.core.USBTimeoutError:
            continue
    raise RuntimeError("no command ack")


def xq_load(dev, blob, dest_phys, run=True, timeout_ms=20000, wait=True):
    npk = (len(blob) + PKT - 1) // PKT
    data = blob + bytes(npk * PKT - len(blob))
    dev.write(1, pkt(XQ0, band=(dest_phys, npk), noflip=1 if run else 0) + data, timeout=10000)
    t0 = time.time()
    if not wait:
        return 0.0
    while True:
        tag, w = rd(dev, timeout_ms)
        if tag == b"XQD1":
            return time.time() - t0


def build_hello():
    from mipsasm import Asm, T0, T1, T2, T3, S4, RA
    a = Asm(0x80800000)
    a.li(T0, 0xF800F800)                 # red
    a.move(T1, S4)                       # front buffer (stage-1 keeps it in S4, kseg1)
    a.li(T2, 1228800 // 32)
    a.label("fill")
    for i in range(8):
        a.sw(T0, 4 * i, T1)
    a.addiu(T2, T2, -1)
    a.bne(T2, 0, "fill")
    a.addiu(T1, T1, 32)
    a.li(T2, 3_000_000)                  # timing loop: 3M iterations x 5 instr
    a.label("spin")
    a.addu(T3, T0, T1)
    a.addu(T3, T3, T0)
    a.addiu(T2, T2, -1)
    a.bne(T2, 0, "spin")
    a.nop()
    a.jr(RA)
    a.nop()
    return a.assemble()


if __name__ == "__main__":
    dev = open_frame()
    if sys.argv[1:] == ["hello"]:
        blob = build_hello()
        print("hello blob: %d bytes" % len(blob))
        cmd(dev)                                     # make sure the command path is alive
        dt = xq_load(dev, blob, 0x00800000)
        print("blob returned after %.3f s (3M x 5 instr: ~0.04 s if running from the I-cache, ~0.9 s uncached)" % dt)
        fb = cmd(dev, peeks=[0xA0000000, 0xA0200000, 0xA0000000 + 614400 * 2 - 4, 0xA0200000 + 614400 * 2 - 4])
        print("FB words:", ["0x%08X" % v for v in fb], "-> one of the two buffers should be 0xF800F800 at both ends")
        print("stub still alive:", cmd(dev, peeks=[0xB0010010])[0] == 0x542)
