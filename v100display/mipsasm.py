# SPDX-License-Identifier: GPL-2.0-or-later
"""Tiny MIPS32 (little endian) assembler for the V100 stage-2 blobs (code that is uploaded into DRAM and run by the resident stub).
Instance based, labels + branch fixups, absolute base address known at assembly time.  Only the instructions the blobs need."""
import struct

ZERO, AT, V0, V1, A0, A1, A2, A3 = 0, 1, 2, 3, 4, 5, 6, 7
T0, T1, T2, T3, T4, T5, T6, T7 = 8, 9, 10, 11, 12, 13, 14, 15
S0, S1, S2, S3, S4, S5, S6, S7, T8, T9 = 16, 17, 18, 19, 20, 21, 22, 23, 24, 25
GP, SP, FP, RA = 28, 29, 30, 31
M = 0xFFFFFFFF


class Asm:
    def __init__(self, base):
        self.base = base
        self.items = []          # ("W", word) | ("L", name) | ("B", opbits, label) | ("D", bytes) data blob (word aligned)
        self.pc = 0

    # -- plumbing
    def w(self, x):
        self.items.append(("W", x & M)); self.pc += 4

    def label(self, n):
        self.items.append(("L", n))

    def data(self, b):
        assert len(b) % 4 == 0
        self.items.append(("D", b)); self.pc += len(b)

    def _r(self, op, rs=0, rt=0, imm=0):
        self.w((op << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF))

    def _spec(self, rs, rt, rd, sa, fn):
        self.w((rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | fn)

    # -- ALU
    def lui(self, rt, i): self._r(0x0F, 0, rt, i)
    def ori(self, rt, rs, i): self._r(0x0D, rs, rt, i)
    def andi(self, rt, rs, i): self._r(0x0C, rs, rt, i)
    def xori(self, rt, rs, i): self._r(0x0E, rs, rt, i)
    def addiu(self, rt, rs, i): self._r(0x09, rs, rt, i)
    def sltiu(self, rt, rs, i): self._r(0x0B, rs, rt, i)
    def addu(self, d, s, t): self._spec(s, t, d, 0, 0x21)
    def subu(self, d, s, t): self._spec(s, t, d, 0, 0x23)
    def and_(self, d, s, t): self._spec(s, t, d, 0, 0x24)
    def or_(self, d, s, t): self._spec(s, t, d, 0, 0x25)
    def xor(self, d, s, t): self._spec(s, t, d, 0, 0x26)
    def sltu(self, d, s, t): self._spec(s, t, d, 0, 0x2B)
    def sll(self, d, t, sa): self._spec(0, t, d, sa, 0x00)
    def srl(self, d, t, sa): self._spec(0, t, d, sa, 0x02)
    def move(self, d, s): self.or_(d, s, ZERO)
    def nop(self): self.w(0)

    def li(self, rt, i):
        i &= M
        if i < 0x10000: self.ori(rt, ZERO, i)
        elif i & 0xFFFF == 0: self.lui(rt, i >> 16)
        else:
            self.lui(rt, i >> 16); self.ori(rt, rt, i & 0xFFFF)

    # -- memory
    def lw(self, rt, o, rs): self._r(0x23, rs, rt, o)
    def lhu(self, rt, o, rs): self._r(0x25, rs, rt, o)
    def lbu(self, rt, o, rs): self._r(0x24, rs, rt, o)
    def sw(self, rt, o, rs): self._r(0x2B, rs, rt, o)
    def sh(self, rt, o, rs): self._r(0x29, rs, rt, o)
    def sb(self, rt, o, rs): self._r(0x28, rs, rt, o)

    # -- branches (delay slot is the caller's next instruction!)
    def _br(self, opbits, label):
        self.items.append(("B", opbits, label)); self.pc += 4

    def beq(self, rs, rt, label): self._br(0x10000000 | (rs << 21) | (rt << 16), label)
    def bne(self, rs, rt, label): self._br(0x14000000 | (rs << 21) | (rt << 16), label)
    def b(self, label): self.beq(ZERO, ZERO, label)
    def bal(self, label): self._br(0x04110000, label)
    def jr(self, rs): self.w((rs << 21) | 0x08)
    def jalr(self, rs, rd=RA): self.w((rs << 21) | (rd << 11) | 0x09)

    # -- system
    def cache(self, op, base, off=0): self.w(0xBC000000 | (base << 21) | (op << 16) | (off & 0xFFFF))
    def sync(self): self.w(0x0F)
    def mtc0(self, rt, rd, sel=0): self.w(0x40800000 | (rt << 16) | (rd << 11) | sel)
    def mfc0(self, rt, rd, sel=0): self.w(0x40000000 | (rt << 16) | (rd << 11) | sel)

    # -- finish
    def assemble(self):
        labels, pc = {}, 0
        for it in self.items:
            if it[0] == "L": labels[it[1]] = pc
            elif it[0] == "D": pc += len(it[1])
            else: pc += 4
        out, pc = bytearray(), 0
        for it in self.items:
            k = it[0]
            if k == "L": continue
            if k == "D":
                out += it[1]; pc += len(it[1]); continue
            if k == "W": wv = it[1]
            else:
                off = (labels[it[2]] - (pc + 4)) >> 2
                assert -0x8000 <= off < 0x8000, "branch out of range to " + it[2]
                wv = it[1] | (off & 0xFFFF)
            out += struct.pack("<I", wv); pc += 4
        self.labels = {k: v + self.base for k, v in labels.items()}
        return bytes(out)
