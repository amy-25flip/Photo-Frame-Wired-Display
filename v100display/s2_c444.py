#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stage-2 blob for the V100 stub: receives c444-packed frames by DMA from the USB FIFO and decodes them (cached code + LUT) into the back buffer.

Layout in DRAM (physical): code 0x00800000 (padded to 4 KB) | LUT 0x00801000 (8 KB) | staging slots 0x00900000 / 0x00900200 | save area 0xA0400300 (kseg1).
Protocol (after loading with xq_load): host sends, per frame, a header packet [word0 'V1C4', words 1-3 magic, word 27 = number of data packets]
followed by that many 512-byte data packets (see c444.py).  The blob DMAs every packet (mode 0x00120052 from the FIFO port, started after the packet
arrived), decodes the PREVIOUS packet while the DMA of the current one runs, flips DE_PLANE0_BA after the last packet and acks 'C4F1' + frame counter.
'V1ST' header = stop: the blob restores S0-S7 and returns to the stub.  Anything else is discarded until a header shows up (self-resync).

    python3 s2_c444.py sim      # simulate with a fake FIFO/DMA in Unicorn and compare against c444.decode_ref
"""
import struct, sys
import numpy as np
from mipsasm import *
import c444

SIM = len(sys.argv) > 1 and sys.argv[1] == "sim"
CODE_PHYS, LUT_OFF = 0x00800000, 0x1000
TABLE_K0 = 0x80000000 | (CODE_PHYS + LUT_OFF)
SLOT_A = 0x80900000
SAVE = 0xA0400300
USB, DMA3, DE_BA = 0xB0290000, 0xB0220190, 0xB02F0050
MAGIC = (0x44483156, 0x5F4D5246, 0xA55AC33C, 0x3CC35AA5)
HDR_C4, HDR_ST = 0x34433156, 0x54533156          # 'V1C4' / 'V1S T' -> 'V1ST'
HDR_ST = 0x54533156
ACK_C4 = 0x31463443                               # 'C4F1'


def build():
    a = Asm(0x80000000 | CODE_PHYS)
    # ---- entry: save S0-S7, RA ----
    a.li(T0, SAVE)
    for i, r in enumerate((S0, S1, S2, S3, S4, S5, S6, S7)):
        a.sw(r, 4 * i, T0)
    a.sw(RA, 32, T0)
    a.li(S0, USB); a.li(S1, DMA3); a.li(S2, TABLE_K0)
    a.li(T0, 0x00120052); a.sw(T0, 0, S1)            # DMA MODE: plain-memory source, fixed address, SDRAM dst incrementing
    a.li(T0, 0x10290084); a.sw(T0, 4, S1)            # SRC = FIFO read port
    # Explicit readiness replaces the host's fixed sleep before the first frame.
    a.label('ready_in');a.lbu(T0,0x17,S0);a.andi(T0,T0,2)
    a.bne(T0,ZERO,'ready_in');a.nop()
    a.li(T0,0x44523443);a.sw(T0,0x88,S0)            # C4RD
    for _ in range(7):a.sw(ZERO,0x88,S0)
    a.li(T0,32);a.sb(T0,0x14,S0);a.sb(ZERO,0x15,S0);a.sb(T0,0x17,S0)
    # ---- HUNT: take one packet into slot A and look for a header ----
    a.label("hunt")
    a.li(A1, SLOT_A)
    a.bal("dma_start"); a.nop()
    a.bal("dma_wait"); a.nop()
    a.lw(T0, 0, A1); a.lw(T1, 4, A1); a.lw(T2, 8, A1); a.lw(T3, 12, A1)
    a.li(T4, MAGIC[1]); a.bne(T1, T4, "hunt"); a.nop()
    a.li(T4, MAGIC[2]); a.bne(T2, T4, "hunt"); a.nop()
    a.li(T4, MAGIC[3]); a.bne(T3, T4, "hunt"); a.nop()
    a.li(T4, HDR_ST); a.beq(T0, T4, "exit"); a.nop()
    a.li(T4, HDR_C4); a.bne(T0, T4, "hunt"); a.nop()
    a.lw(A2, 108, A1)                                # word 27: number of data packets
    a.beq(A2, ZERO, "hunt"); a.nop()
    a.move(S3, S5)                                   # output pointer = back buffer (kseg1)
    a.li(A3, 0)                                      # nothing to decode yet
    # ---- DATA pipeline: DMA packet k while decoding packet k-1 ----
    a.label("dloop")
    a.bal("dma_start"); a.nop()
    a.beq(A3, ZERO, "nodec"); a.nop()
    a.move(V0, A3); a.bal("decode"); a.nop()
    a.label("nodec")
    a.bal("dma_wait"); a.nop()
    a.move(A3, A1)
    a.xori(A1, A1, 0x200)
    a.addiu(A2, A2, -1)
    a.bne(A2, ZERO, "dloop"); a.nop()
    a.move(V0, A3); a.bal("decode"); a.nop()         # last packet
    a.li(T0, DE_BA); a.sw(S5, 0, T0)                 # flip: DE_PLANE0_BA = back buffer
    a.move(T0, S4); a.move(S4, S5); a.move(S5, T0)
    a.addiu(S6, S6, 1)
    # ack 'C4F1' + frame counter (only if the IN endpoint is idle)
    a.lbu(T0, 0x17, S0); a.andi(T0, T0, 2); a.bne(T0, ZERO, "noack"); a.nop()
    a.li(T0, ACK_C4); a.sw(T0, 0x88, S0); a.sw(S6, 0x88, S0)
    for _ in range(6):
        a.sw(ZERO, 0x88, S0)
    a.addiu(T1, ZERO, 32); a.sb(T1, 0x14, S0); a.sb(ZERO, 0x15, S0); a.sb(T1, 0x17, S0)
    a.label("noack")
    a.b("hunt"); a.nop()
    # ---- exit: write back S4/S5/S6, restore, return ----
    a.label("exit")
    a.li(T0, SAVE)
    a.sw(S4, 16, T0); a.sw(S5, 20, T0); a.sw(S6, 24, T0)
    for i, r in enumerate((S0, S1, S2, S3, S4, S5, S6, S7)):
        a.lw(r, 4 * i, T0)
    a.lw(RA, 32, T0)
    a.jr(RA); a.nop()

    # ---- dma_start(A1 = slot kseg0 address): arm OUT, wait for the packet, start the 512-byte DMA ----
    a.label("dma_start")
    a.addiu(T0, ZERO, 1); a.sb(T0, 0x0b, S0)
    a.nop(); a.nop(); a.nop(); a.nop()
    a.label("ds_w")
    a.lbu(T0, 0x0b, S0); a.andi(T0, T0, 2); a.bne(T0, ZERO, "ds_w"); a.nop()
    a.li(T1, 0x1FFFFFFF); a.and_(T1, A1, T1); a.sw(T1, 8, S1)
    a.addiu(T0, ZERO, c444.GROUPS_PER_PKT * 12); a.sw(T0, 12, S1)   # 504 bytes: the 8 padding bytes are not read
    a.addiu(T0, ZERO, 1); a.sw(T0, 0x14, S1)
    a.jr(RA); a.nop()
    # ---- dma_wait(A1): wait for the DMA, invalidate the slot's D-cache lines ----
    a.label("dma_wait")
    a.label("dw_w")
    a.lw(T0, 0x14, S1); a.andi(T0, T0, 1); a.bne(T0, ZERO, "dw_w"); a.nop()
    a.move(T1, A1); a.addiu(T0, ZERO, 16)
    a.label("dw_i")
    if SIM: a.nop()
    else: a.cache(0x11, T1, 0)                       # Hit_Invalidate_D
    a.addiu(T0, T0, -1); a.bne(T0, ZERO, "dw_i"); a.addiu(T1, T1, 32)
    a.jr(RA); a.nop()
    # ---- decode(V0 = slot kseg0 address): 42 groups of 8 pixels -> S3 (kseg1 output pointer) ----
    a.label("decode")
    a.addiu(V1, ZERO, c444.GROUPS_PER_PKT)
    a.label("dg")
    a.lw(T0, 0, V0); a.lw(T1, 4, V0); a.lw(T2, 8, V0)
    a.sll(T3, T0, 1); a.andi(T3, T3, 0x1FFE); a.addu(T3, T3, S2); a.lhu(T3, 0, T3)            # p0
    a.srl(T4, T0, 11); a.andi(T4, T4, 0x1FFE); a.addu(T4, T4, S2); a.lhu(T4, 0, T4)           # p1
    a.srl(T5, T0, 23); a.sll(T6, T1, 9); a.or_(T5, T5, T6); a.andi(T5, T5, 0x1FFE); a.addu(T5, T5, S2); a.lhu(T5, 0, T5)   # p2
    a.srl(T6, T1, 3); a.andi(T6, T6, 0x1FFE); a.addu(T6, T6, S2); a.lhu(T6, 0, T6)            # p3
    a.srl(T7, T1, 15); a.andi(T7, T7, 0x1FFE); a.addu(T7, T7, S2); a.lhu(T7, 0, T7)           # p4
    a.srl(T8, T1, 27); a.sll(T9, T2, 5); a.or_(T8, T8, T9); a.andi(T8, T8, 0x1FFE); a.addu(T8, T8, S2); a.lhu(T8, 0, T8)   # p5
    a.srl(T9, T2, 7); a.andi(T9, T9, 0x1FFE); a.addu(T9, T9, S2); a.lhu(T9, 0, T9)            # p6
    a.srl(A0, T2, 19); a.andi(A0, A0, 0x1FFE); a.addu(A0, A0, S2); a.lhu(A0, 0, A0)           # p7
    a.sll(T4, T4, 16); a.or_(T3, T3, T4); a.sw(T3, 0, S3)
    a.sll(T6, T6, 16); a.or_(T5, T5, T6); a.sw(T5, 4, S3)
    a.sll(T8, T8, 16); a.or_(T7, T7, T8); a.sw(T7, 8, S3)
    a.sll(A0, A0, 16); a.or_(T9, T9, A0); a.sw(T9, 12, S3)
    a.addiu(V0, V0, 12); a.addiu(V1, V1, -1)
    a.bne(V1, ZERO, "dg"); a.addiu(S3, S3, 16)
    a.jr(RA); a.nop()
    code = a.assemble()
    assert len(code) <= LUT_OFF, "code too big: %d" % len(code)
    return code.ljust(LUT_OFF, b"\0") + c444.make_lut().tobytes(), a.labels


def blob():
    return build()[0]


if __name__ == "__main__":
    b, labels = build()
    print("blob %d bytes (code %d)" % (len(b), max(labels.values()) - 0x80800000))
    if SIM:
        from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
        from unicorn.mips_const import *
        fix = lambda x: x & 0x1fffffff
        uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        uc.mem_map(0, 0x1000000)
        uc.mem_map(fix(0xB0000000), 0x400000)
        uc.mem_map(fix(0xB4060000), 0x10000)
        uc.mem_write(CODE_PHYS, b)
        rng = np.random.default_rng(3)
        NDATA = 5
        payload = rng.integers(0, 256, size=(NDATA, 512), dtype=np.uint8)
        def hdrpk(w0, n=0):
            w = [w0, MAGIC[1], MAGIC[2], MAGIC[3]] + [0] * 23 + [n]
            return struct.pack("<%dI" % len(w), *w) + bytes(512 - 4 * len(w))
        stream = bytes(512) + bytes(512) + hdrpk(HDR_C4, NDATA) + payload.tobytes() + hdrpk(HDR_C4, 2) + payload[:2].tobytes() + hdrpk(HDR_ST)
        st = {"pos": 0, "acks": [], "ba": []}
        DST_REG, CNT_REG, CMD_REG = fix(DMA3) + 8, fix(DMA3) + 12, fix(DMA3) + 0x14
        def on_write(u, access, addr, size, value, ud):
            if addr == CMD_REG and value == 1:
                dst = struct.unpack("<I", bytes(u.mem_read(DST_REG, 4)))[0]
                chunk = stream[st["pos"]:st["pos"] + 512].ljust(512, b"\xEE")
                st["pos"] += 512
                u.mem_write(dst, chunk)
            if addr == fix(USB) + 0x88: st["acks"].append(value & 0xFFFFFFFF)
            if addr == fix(DE_BA): st["ba"].append(value & 0xFFFFFFFF)
        def on_read(u, access, addr, size, value, ud):
            if addr == CMD_REG: u.mem_write(CMD_REG, struct.pack("<I", 0))
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=fix(DMA3) + 0x14, end=fix(DMA3) + 0x14)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=fix(USB) + 0x88, end=fix(USB) + 0x88)
        uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=fix(DE_BA), end=fix(DE_BA))
        uc.hook_add(UC_HOOK_MEM_READ, on_read, begin=CMD_REG, end=CMD_REG)
        for r, v in ((UC_MIPS_REG_S0, USB), (UC_MIPS_REG_S3, 0x89), (UC_MIPS_REG_S4, 0xA0000000), (UC_MIPS_REG_S5, 0xA0200000),
                     (UC_MIPS_REG_S6, 7), (UC_MIPS_REG_S7, 0xB02F0050), (UC_MIPS_REG_RA, 0xB4061700)):
            uc.reg_write(r, v)
        uc.mem_write(fix(0xB4061700), struct.pack("<2I", 0, 0))
        uc.emu_start(0x80800000, 0xB4061700, count=200000000)
        print("returned to the stub address; stream bytes consumed:", st["pos"], "of", len(stream))
        print("S4/S5/S6 on return (want S4=FB0 S5=FB1 after two flips, S6=9):",
              hex(uc.reg_read(UC_MIPS_REG_S4)), hex(uc.reg_read(UC_MIPS_REG_S5)), uc.reg_read(UC_MIPS_REG_S6),
              "| S0/S3/S7 preserved:", hex(uc.reg_read(UC_MIPS_REG_S0)), hex(uc.reg_read(UC_MIPS_REG_S3)), hex(uc.reg_read(UC_MIPS_REG_S7)))
        print("BA writes:", [hex(x) for x in st["ba"]], "| acks (first words):", [hex(x) for x in st["acks"][:2]], "...")
        want = c444.decode_ref(payload.tobytes())
        # frame 1 -> back buffer FB1 (S5 at entry), frame 2 (2 packets) -> FB0
        got1 = np.frombuffer(bytes(uc.mem_read(fix(0xA0200000), NDATA * 336 * 2)), dtype="<u2")
        print("frame 1 decoded == reference:", np.array_equal(got1, want))
        want2 = c444.decode_ref(payload[:2].tobytes())
        got2 = np.frombuffer(bytes(uc.mem_read(fix(0xA0000000), 2 * 336 * 2)), dtype="<u2")
        print("frame 2 decoded == reference:", np.array_equal(got2, want2))
