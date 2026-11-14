# SPDX-License-Identifier: GPL-2.0-or-later
# Stage 1 for the Actions V100 / ATJ2273F photo frame: the 2 KiB bare-metal program uploaded through the boot ROM's ADFU mode.
#   - disables interrupts, clears both framebuffers, brings up the LCD controller and display engine
#   - receives 512-byte bulk-OUT packets by reading the USB FIFO port; header types 'V1HD' (frame/band), 'V1CM' (register poke/peek), 'V1XQ' (load + run a blob)
#   python stage1.py sim              assemble + emulate in Unicorn with a fake USB FIFO (no device)
#   python stage1.py dump out.bin     write the image that gets uploaded (v100display/stage1-clean.bin must equal it)
import struct, sys, time

MODE = sys.argv[1] if len(sys.argv) > 1 else "sim"
SIM = MODE == "sim"

ZERO, AT, V0, V1, A0, A1, A2, A3 = 0, 1, 2, 3, 4, 5, 6, 7
T0, T1, T2, T3, T4, T5, T6, T7 = 8, 9, 10, 11, 12, 13, 14, 15
S0, S1, S2, S3, S4, S5, S6, S7, T8, T9, RA = 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 31
IMG_SIZE = 0x800
CMU, GPIO, LCD, DE, USB = 0xB0010000, 0xB01C0000, 0xB02A0000, 0xB02F0000, 0xB0290000
FB0, FB1 = 0xA0000000, 0xA0200000
W, H = 1024, 600
FRAME = W * H * 2                                   # 1228800 = 2400 x 512
PKT = 512
BIT = lambda n: 1 << n
M = 0xffffffff
D_LONG = 4 if SIM else 0x20000
D_SHORT = 4 if SIM else 0x4000

items = []
def emit(x): items.append(x)
def Wd(w): emit(("W", w & M))
def L(n): emit(("L", n))
def BR(base, label): emit(("B", base, label))
def LA(rt, label): emit(("A", rt, label))

def lui(rt, i): Wd(0x3C000000 | (rt << 16) | (i & 0xffff))
def ori(rt, rs, i): Wd(0x34000000 | (rs << 21) | (rt << 16) | (i & 0xffff))
def andi(rt, rs, i): Wd(0x30000000 | (rs << 21) | (rt << 16) | (i & 0xffff))
def addiu(rt, rs, i): Wd(0x24000000 | (rs << 21) | (rt << 16) | (i & 0xffff))
def sw(rt, o, rs): Wd(0xAC000000 | (rs << 21) | (rt << 16) | (o & 0xffff))
def sb(rt, o, rs): Wd(0xA0000000 | (rs << 21) | (rt << 16) | (o & 0xffff))
def lw(rt, o, rs): Wd(0x8C000000 | (rs << 21) | (rt << 16) | (o & 0xffff))
def lbu(rt, o, rs): Wd(0x90000000 | (rs << 21) | (rt << 16) | (o & 0xffff))
def AND(d, s, t): Wd(0x24 | (s << 21) | (t << 16) | (d << 11))
def OR(d, s, t): Wd(0x25 | (s << 21) | (t << 16) | (d << 11))
def ADDU(d, s, t): Wd(0x21 | (s << 21) | (t << 16) | (d << 11))
def nop(): Wd(0)
def li(rt, i):
    i &= M
    if i < 0x10000: ori(rt, ZERO, i)
    elif (i & 0xffff) == 0: lui(rt, i >> 16)
    else: lui(rt, i >> 16); ori(rt, rt, i & 0xffff)
def BEQ(rs, rt, label): BR(0x10000000 | (rs << 21) | (rt << 16), label)
def BNE(rs, rt, label): BR(0x14000000 | (rs << 21) | (rt << 16), label)
def B(label): BEQ(ZERO, ZERO, label)
def BAL(label): BR(0x04110000, label)
def ent(addr, andm, orv): Wd(addr); Wd(andm); Wd(orv)
def wr(addr, val): ent(addr, 0, val)
def dly(n): ent(1, 0, n)

def SRL(d, t, sa): Wd((t << 16) | (d << 11) | (sa << 6) | 2)
def SLL(d, t, sa): Wd((t << 16) | (d << 11) | (sa << 6))
def SUBU(d, s, t): Wd(0x23 | (s << 21) | (t << 16) | (d << 11))
def count(rt):
    """rt = CP0 Count (ticks at CPU clock / 2). Real hardware only; the simulator gets a nop."""
    if SIM: nop()
    else: Wd(0x40004800 | (rt << 16))

HDR_MAGIC = (0x44483156, 0x5F4D5246, 0xA55AC33C, 0x3CC35AA5)   # frame header: first 16 bytes
DM_MAGIC0 = 0x4D443156                                         # DMA-trial packet 'V1DM'
XQ_MAGIC0 = 0x51583156                                         # loader packet 'V1XQ'
CMD_MAGIC0 = 0x4D433156                                        # command packet: same words but word0 = "V1CM"

_ack_n = [0]
def ack4(magic, w1, w2, w3):
    """If the IN endpoint is idle, queue 16 bytes {magic, w1, w2, w3} for the host (registers)."""
    _ack_n[0] += 1
    skip = "ack_skip_%d" % _ack_n[0]
    lbu(T0, 0x17, S0); andi(T0, T0, 2)
    BNE(T0, ZERO, skip); nop()
    li(T1, magic); sw(T1, 0x88, S0)
    sw(w1, 0x88, S0); sw(w2, 0x88, S0); sw(w3, 0x88, S0)
    addiu(T1, ZERO, 16); sb(T1, 0x14, S0); sb(ZERO, 0x15, S0); sb(T1, 0x17, S0)
    L(skip)

# ---------------- code ----------------
if not SIM:
    Wd(0x40086000)            # mfc0 t0, Status
    nop(); nop(); nop()
    li(T1, 0xfffffffe); AND(T0, T0, T1)
    Wd(0x40886000)            # mtc0 t0, Status   (interrupts off: we own the USB now)
    nop(); nop(); nop(); nop()
BAL("L0"); nop()
L("L0")
OR(T9, RA, ZERO)

# Never scan out uninitialized DDR: clear both buffers and their gap BEFORE
# panel/backlight bring-up. FB1's end is the exclusive bound.
li(T0, FB0); li(T1, FB1 + FRAME)
L("clear_fb")
sw(ZERO, 0, T0); addiu(T0, T0, 4)
BNE(T0, T1, "clear_fb"); nop()
L('clear_complete')
LA(A0, "TBL_LCD"); BAL("run_table"); nop()

LA(A0, "TBL_DE"); BAL("run_table"); nop()
LA(A0, "TBL_SHOW"); BAL("run_table"); nop()

# ---- receive loop state ----
SCR = 0xA0400000                 # 512-byte scratch in DRAM (SRAM beyond ~0xB4062200 does not exist!): last header/command packet
RES = SCR + 0x200                # 4 result words (peeks / startup info)
li(S0, USB)
li(S4, FB0)                    # front (displayed)
li(S5, FB1)                    # back (being written)
li(S6, 0)                      # frame counter
li(S7, DE + 0x50)              # DE_PLANE0_BA register
li(V0, 0)
li(S3, 0x88)                   # bulk-OUT EPCON as the ROM configured it (valid, bulk, single buffer)

# startup info for the first ack: CMU_COREPLL, CMU_BUSCLK, CP0 Config, CP0 Config1
li(T7, RES)
li(T0, CMU + 0x00); lw(T1, 0, T0); sw(T1, 0, T7)
li(T0, CMU + 0x10); lw(T1, 0, T0); sw(T1, 4, T7)
if SIM:
    sw(ZERO, 8, T7); sw(ZERO, 12, T7)
else:
    sw(ZERO, 8, T7); sw(ZERO, 12, T7)
li(T1, 0x31594452); li(A1, 0); li(A2, 0); li(A3, 0); li(T6, 1)    # 'RDY1' (blocking)
BAL("send_ack"); nop()

# ---- wait for a HEADER or COMMAND packet (self-aligning) ----
# packet words: 0..3 magic (frame 'V1HD' / command 'V1CM' + 3 common words) | 4 = OUT EPCON to apply (0 = none)
#   5..20 = 8 register pokes {addr, value} (addr 0 = skip) | 21..24 = 4 register peeks (addr 0 = skip) | 25 = exec mode (1 cached, 2 uncached)
L("hdr")
addiu(T0, ZERO, 1); sb(T0, 0x0b, S0)             # arm bulk-OUT
nop(); nop(); nop(); nop()
L("hwait"); lbu(T0, 0x0b, S0); andi(T0, T0, 2); BNE(T0, ZERO, "hwait"); nop()
li(T7, SCR); addiu(T5, ZERO, PKT // 16)
L("hcopy")
lw(T0, 0x84, S0); lw(T1, 0x84, S0); lw(T2, 0x84, S0); lw(T3, 0x84, S0)
sw(T0, 0, T7); sw(T1, 4, T7); sw(T2, 8, T7); sw(T3, 12, T7)
addiu(T5, T5, -1); BNE(T5, ZERO, "hcopy"); addiu(T7, T7, 16)
li(T7, SCR)
for off, m in ((4, HDR_MAGIC[1]), (8, HDR_MAGIC[2]), (12, HDR_MAGIC[3])):
    lw(T1, off, T7); li(T4, m); BNE(T1, T4, "hdr"); nop()
lw(T0, 0, T7)
li(T4, HDR_MAGIC[0]); BEQ(T0, T4, "is_frame"); nop()
li(T4, CMD_MAGIC0); BEQ(T0, T4, "is_cmd"); nop()
li(T4, XQ_MAGIC0); BEQ(T0, T4, "is_xq"); nop()
B("hdr"); nop()
L("is_cmd")
# command packet: apply pokes/peeks, answer with the peek values, no frame follows
BAL("do_cfg"); nop()
li(T1, 0x31444d43); OR(A1, S6, ZERO); li(A2, 0); OR(A3, S3, ZERO); li(T6, 1)   # 'CMD1' (blocking)
BAL("send_ack"); nop()
B("hdr"); nop()

L("is_xq")
BAL("do_cfg"); nop()
li(T7, SCR); lw(T0, 104, T7); lui(T1, 0xA000); OR(S1, T0, T1)     # destination, kseg1
lw(T5, 108, T7)                                                   # packets
lw(S2, 112, T7)                                                   # flags
BEQ(T5, ZERO, "xq_done"); nop()
L("xq_pkt")
addiu(T0, ZERO, 1); sb(T0, 0x0b, S0)
nop(); nop(); nop(); nop()
L("xq_w"); lbu(T0, 0x0b, S0); andi(T0, T0, 2); BNE(T0, ZERO, "xq_w"); nop()
addiu(T6, ZERO, PKT // 16)
L("xq_cp")
lw(T0, 0x84, S0); lw(T1, 0x84, S0); lw(T2, 0x84, S0); lw(T3, 0x84, S0)
sw(T0, 0, S1); sw(T1, 4, S1); sw(T2, 8, S1); sw(T3, 12, S1)
addiu(T6, T6, -1); BNE(T6, ZERO, "xq_cp"); addiu(S1, S1, 16)
addiu(T5, T5, -1); BNE(T5, ZERO, "xq_pkt"); nop()
L("xq_done")
if not SIM:
    Wd(0x4080E000)                                                # mtc0 zero, TagLo
    li(T0, 0x80000000); addiu(T5, ZERO, 512)
    L("xq_d"); Wd(0xBD090000); addiu(T5, T5, -1); BNE(T5, ZERO, "xq_d"); addiu(T0, T0, 32)   # Index_Store_Tag_D: invalidate D-cache, no writeback
    li(T0, 0x80000000); addiu(T5, ZERO, 512)
    L("xq_i"); Wd(0xBC080000 | (T0 << 21)); addiu(T5, T5, -1); BNE(T5, ZERO, "xq_i"); addiu(T0, T0, 32)   # Index_Store_Tag_I
    Wd(0x0000000F); Wd(0x000000C0)                                # sync ; ehb
andi(T0, S2, 1); BEQ(T0, ZERO, "xq_ack"); nop()
li(T7, SCR); lw(T0, 104, T7); lui(T1, 0x8000); OR(T8, T0, T1)
Wd(0x0300F809); nop()                                             # jalr t8: run the blob from kseg0 (I-cache); it must preserve S0-S7 and return with jr ra
L("xq_ack")
li(T1, 0x31445158); OR(A1, S6, ZERO); OR(A2, V0, ZERO); OR(A3, S3, ZERO); li(T6, 1)   # 'XQD1' (blocking)
BAL("send_ack"); nop()
B("hdr"); nop()

L("is_frame")
BAL("do_cfg"); nop()
# frame start: receive a BAND of rows into the back buffer: header word 26 = y0, word 27 = rows (0 = whole frame).
# Each row is 2048 bytes = 4 packets. (kseg0 alias when cached FB writes are on)
li(V0, 0)
li(T7, SCR); lw(T2, 104, T7); lw(T3, 108, T7)
BNE(T3, ZERO, "rows_ok"); nop()
addiu(T3, ZERO, H)
L("rows_ok")
SLL(T2, T2, 11)
ADDU(S1, S5, T2)
SLL(T3, T3, 11); ADDU(S2, S1, T3)
addiu(A1, ZERO, PKT // 32); OR(A2, ZERO, ZERO)

L("pkt")
addiu(T0, ZERO, 1); sb(T0, 0x0b, S0)             # arm bulk-OUT
nop(); nop(); nop(); nop()
L("wait"); lbu(T0, 0x0b, S0); andi(T0, T0, 2); BNE(T0, ZERO, "wait"); addiu(V0, V0, 1)   # V0 counts polls
OR(T5, A1, ZERO)
L("blk")
for i in range(8):
    lw(T0 if i % 2 == 0 else T1, 0x84, S0)
    sw(T0 if i % 2 == 0 else T1, 4 * i, S1)
addiu(T5, T5, -1); BNE(T5, ZERO, "blk"); addiu(S1, S1, 32)
ADDU(S1, S1, A2)                                   # keep the destination advancing 512 B per packet
BNE(S1, S2, "pkt"); nop()
L("band_done")

# band complete. Header word 28 bit0 = "no flip": more bands of the same update follow, keep writing the back buffer.
li(T7, SCR); lw(T0, 112, T7); andi(T0, T0, 1); BNE(T0, ZERO, "hdr"); nop()
# frame complete: flip and swap buffers
sw(S5, 0, S7)
OR(T0, S4, ZERO); OR(S4, S5, ZERO); OR(S5, T0, ZERO)
addiu(S6, S6, 1)
li(T1, 0x34524d46); OR(A1, S6, ZERO); OR(A2, V0, ZERO); OR(A3, S3, ZERO); li(T6, 0)   # 'FMR4' (non-blocking)
BAL("send_ack"); nop()
B("hdr"); nop()


# apply the config part of the packet in SCR: EPCON, pokes, peeks (-> RES)
L("do_cfg")
OR(A0, RA, ZERO)
li(T7, SCR)
lw(T6, 16, T7)
BEQ(T6, ZERO, "cfg_a"); nop()
BEQ(T6, S3, "cfg_a"); nop()
sb(T6, 0x0a, S0); OR(S3, T6, ZERO)
L("cfg_a")
addiu(T7, T7, 20); addiu(T5, ZERO, 8)
L("pk"); lw(T0, 0, T7); lw(T1, 4, T7); BAL("poke1"); nop()
L("pk_n"); addiu(T5, T5, -1); BNE(T5, ZERO, "pk"); addiu(T7, T7, 8)
BAL("do_peek"); nop()
Wd(0x00800008); nop()                               # jr a0 (return to do_cfg's caller)
L("do_peek")
li(T7, SCR + 84); li(T8, RES); addiu(T5, ZERO, 4)
L("pe"); lw(T0, 0, T7); li(T1, 0); BEQ(T0, ZERO, "pe_n"); nop(); lw(T1, 0, T0)
L("pe_n"); sw(T1, 0, T8); addiu(T5, T5, -1); addiu(T7, T7, 4); BNE(T5, ZERO, "pe"); addiu(T8, T8, 4)
Wd(0x03E00008); nop()

# poke1: T0 = address, T1 = value (0 = skip). Address flag bit30 = byte write, bit27 (with bit30) = OR into the current byte.
L("poke1")
BEQ(T0, ZERO, "p1_r"); nop()
SRL(T2, T0, 30); addiu(T3, T2, -3); BNE(T3, ZERO, "p1_w"); nop()
li(T3, 0xBFFFFFFF); AND(T0, T0, T3)
sb(T1, 0, T0); B("p1_r"); nop()
L("p1_w"); sw(T1, 0, T0)
L("p1_r"); Wd(0x03E00008); nop()

# send a 32-byte ack {T1, A1, A2, A3, RES[0..3]} if the IN endpoint is idle (T6 != 0: wait for it)
L("send_ack")
L("sa_w"); lbu(T0, 0x17, S0); andi(T0, T0, 2); BEQ(T0, ZERO, "sa_go"); nop()
BEQ(T6, ZERO, "sa_ret"); nop()
B("sa_w"); nop()
L("sa_go")
sw(T1, 0x88, S0); sw(A1, 0x88, S0); sw(A2, 0x88, S0); sw(A3, 0x88, S0)
li(T7, RES)
for i in range(4):
    lw(T0, 4 * i, T7); sw(T0, 0x88, S0)
addiu(T0, ZERO, 32); sb(T0, 0x14, S0); sb(ZERO, 0x15, S0); sb(T0, 0x17, S0)
L("sa_ret"); Wd(0x03E00008); nop()

# table interpreter: entries {addr, and, or}; addr 0 = end, addr 1 = delay(or)
L("run_table")
L("rt"); lw(T0, 0, A0); lw(T1, 4, A0); lw(T2, 8, A0)
BEQ(T0, ZERO, "rt_done"); addiu(A0, A0, 12)
addiu(T4, T0, -1)
BNE(T4, ZERO, "rt_reg"); nop()
L("rt_dly"); BNE(T2, ZERO, "rt_dly"); addiu(T2, T2, -1)
B("rt"); nop()
L("rt_reg"); lw(T3, 0, T0); AND(T3, T3, T1); OR(T3, T3, T2)
B("rt"); sw(T3, 0, T0)
L("rt_done"); Wd(0x03E00008); nop()

# ---------------- tables (identical to diag7) ----------------
L("TBL_LCD")
ent(CMU + 0x80, M, BIT(3) | BIT(2))
ent(CMU + 0x10c, 0xffffff80, 0x16c)
ent(CMU + 0x18, M, 0x10b)
ent(CMU + 0x1c, 0xfffffee0, 0x103)
dly(D_LONG)
ent(CMU + 0x88, ~(BIT(28) | BIT(31)) & M, 0)
dly(D_SHORT)
ent(CMU + 0x88, M, BIT(28) | BIT(31))
dly(D_SHORT)
ent(GPIO + 0x24, 0xffffe000, 0x38000000)
ent(LCD + 0x04, 0xfc00fc00, 0x025703ff)
ent(LCD + 0x0c, 0xffffe0ff, 0x2800)
wr(LCD + 0x10, 0x00009c9f)
wr(LCD + 0x14, 0x00002c16)
wr(LCD + 0x18, 0x00ffffff)
wr(CMU + 0x68, 0x1010)
ent(CMU + 0x84, M, BIT(11))
wr(GPIO + 0x4c, 0x13f)
ent(GPIO + 0x10, ~BIT(30) & M, 0)
ent(GPIO + 0x14, M, BIT(30))
ent(GPIO + 0x0c, M, BIT(30))
wr(LCD + 0x08, 0xf0000000)
ent(LCD + 0x00, 0x7ff8003f, 0x000100c1)
Wd(0)

L("TBL_DE")
wr(DE + 0x08, 0x00ffffff)
ent(DE + 0x120, ~0x60 & M, 0x20)
ent(DE + 0x11c, ~0xff & M, 0x12)
ent(DE + 0x04, 0xf000f000, (H << 16) | W)
wr(DE + 0x30, 0)
wr(DE + 0x20, (H << 16) | W)
wr(DE + 0x70, W // 2)
wr(DE + 0x50, FB0)
ent(DE + 0x10, 0xffffeff0, 1)
wr(DE + 0x88, 0x15)
wr(DE + 0x84, 0)
wr(DE + 0x80, 0)
Wd(0)

L("TBL_SHOW")
ent(LCD + 0x00, ~1 & M, 0)
wr(DE + 0x00, 0)
ent(DE + 0x0c, 0xfffffe00, 0x005)
ent(DE + 0x40, 0xfff0ffff, 0x00040000)
ent(DE + 0x124, M, 4)
ent(DE + 0x00, M, 1)
dly(D_SHORT)
ent(DE + 0x00, M, 0x30)
ent(LCD + 0x00, 0x7ff8003f, 0x00010081)
Wd(0)

# ---------------- resolve ----------------
labels = {}
pc = 0
for it in items:
    if it[0] == "L": labels[it[1]] = pc
    else: pc += 4
assert pc <= IMG_SIZE, "stub too big: 0x%x" % pc
L0 = labels["L0"]

def assemble():
    img = bytearray(IMG_SIZE)
    pc = 0
    for it in items:
        k = it[0]
        if k == "L": continue
        if k == "W": w = it[1]
        elif k == "B":
            off = (labels[it[2]] - (pc + 4)) >> 2
            assert -0x8000 <= off < 0x8000
            w = it[1] | (off & 0xffff)
        elif k == "A":
            d = labels[it[2]] - L0
            w = 0x24000000 | (T9 << 21) | (it[1] << 16) | (d & 0xffff)
        struct.pack_into("<I", img, pc, w)
        pc += 4
    return bytes(img)

img = assemble()
print("stub uses 0x%x of 0x%x bytes" % (pc, IMG_SIZE))
if MODE == "dump":                                   # write the real (non-simulator) image for disassembly
    open(sys.argv[2], "wb").write(img)
    print("labels:", {k: hex(v) for k, v in labels.items() if k in ("ic", "dc", "fl", "cfg_out", "do_cfg", "hdr")})
    sys.exit(0)


def fword(i, salt):                      # fake host pixel data for the simulator
    return (i * 0x9E3779B1 + salt) & M

CFG_EPCON = 0x89 if len(sys.argv) > 3 and sys.argv[3] == "dbl" else 0   # sim: ask for double buffering in the header
def make_packet(kind, epcon=0, pokes=(), peeks=(), mode=0, band=(0, 0), noflip=0, words=0, dm=(0, 0, 0, 0)):
    """512-byte header ('frame') or command ('cmd') packet: magic | epcon | 8 pokes {addr,val} | 4 peek addrs."""
    w = [{"cmd": CMD_MAGIC0, "dm": DM_MAGIC0, "xq": XQ_MAGIC0}.get(kind, HDR_MAGIC[0]), HDR_MAGIC[1], HDR_MAGIC[2], HDR_MAGIC[3], epcon]
    p = list(pokes)[:8]
    for a, v in p: w += [a, v]
    w += [0, 0] * (8 - len(p))
    q = list(peeks)[:4]
    w += q + [0] * (4 - len(q))
    w += [mode, band[0], band[1], noflip, words] + list(dm)   # words 25 (exec mode), 26 (y0), 27 (rows), 28 (bit0 = no flip), 29 (FIFO words per packet; 0 = all)
    return struct.pack("<%dI" % len(w), *w) + bytes(PKT - 4 * len(w))
HEADER = make_packet("frame", CFG_EPCON)                    # one 512-byte header packet

if SIM:
    from unicorn import (Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN,
                         UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ)
    from unicorn.mips_const import UC_MIPS_REG_SP
    fix = lambda a: a & 0x1fffffff
    uc = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
    uc.mem_map(fix(0xB4060000), 0x10000)
    uc.mem_map(fix(FB0), 0x1000000)
    uc.mem_map(fix(0xB0000000), 0x300000)
    uc.mem_write(fix(0xB4061000), img)
    # Dirty DDR catches the original startup bug: framebuffer must be cleared
    # before any LCD setup/backlight enable, not merely zero in a fresh emulator.
    uc.mem_write(fix(FB0), b'\xa5' * (fix(FB1) + FRAME))
    # fake host stream: 37 junk packets (stub starts out of step) | header | frame 1 | 3 junk packets
    # (a desync mid-stream) | header | first 5 packets of frame 2
    JUNK1, JUNK2, BAND_Y0, BAND_ROWS = 37, 3, 100, 3
    BAND2_Y0, BAND2_ROWS = 300, 2
    F2PK = BAND_ROWS * 2048 // PKT                  # band A of update 2 = 3 rows = 12 packets (no flip)
    F2PK2 = BAND2_ROWS * 2048 // PKT                # band B = 2 rows = 8 packets (flips)
    words = [fword(i, 0x777) for i in range(JUNK1 * PKT // 4)]
    CMD = make_packet("cmd", 0x89, pokes=[(CMU + 0x84, 0xDEADBEEF), (CMU + 0x68, 0x1234)], peeks=[CMU + 0x84, CMU + 0x68, CMU + 0x80, 0])
    words += list(struct.unpack("<%dI" % (PKT // 4), CMD))
    prog = struct.pack("<5I", 0x34081234, 0x3C09A050, 0xAD280000, 0x03E00008, 0)   # ori t0,0,0x1234 ; lui t1,0xA050 ; sw t0,0(t1) ; jr ra ; nop
    XQP = make_packet("xq", 0, band=(0x00800000, 1), noflip=1)
    words += list(struct.unpack("<%dI" % (PKT // 4), XQP))
    words += list(struct.unpack("<%dI" % (PKT // 4), prog + bytes(PKT - len(prog))))
    HALF = False
    words += list(struct.unpack("<%dI" % (PKT // 4), make_packet("frame", CFG_EPCON, words=64 if HALF else 0)))
    words += [fword(i, 0x1234567) for i in range(FRAME // 4)]
    words += [fword(i, 0x999) for i in range(JUNK2 * PKT // 4)]
    words += list(struct.unpack("<%dI" % (PKT // 4), make_packet("frame", band=(BAND_Y0, BAND_ROWS), noflip=1)))
    words += [fword(i, 0x5555555) for i in range(F2PK * PKT // 4)]
    words += list(struct.unpack("<%dI" % (PKT // 4), make_packet("frame", band=(BAND2_Y0, BAND2_ROWS))))
    words += [fword(i, 0x7777777) for i in range(F2PK2 * PKT // 4)]
    st = {"i": 0, "ba": [], "ack": [], "armed": 0, "stopped": False, "epcon": []}
    FIFO = fix(USB) + 0x84
    def on_read(u, access, addr, size, value, ud):
        if addr == FIFO:
            if st["i"] >= len(words):
                st["stopped"] = True; u.emu_stop(); return
            u.mem_write(FIFO, struct.pack("<I", words[st["i"]])); st["i"] += 1
    def on_write(u, access, addr, size, value, ud):
        if addr == fix(DE) + 0x50: st["ba"].append(value & M)
        if addr == fix(USB) + 0x88: st["ack"].append(value & M)
        if addr == fix(USB) + 0x0b: st["armed"] += 1
        if addr == fix(USB) + 0x0a: st["epcon"].append(value & 0xff)
    uc.hook_add(UC_HOOK_MEM_READ, on_read, begin=FIFO, end=FIFO)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=fix(DE) + 0x50, end=fix(DE) + 0x50)
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=fix(USB) + 0x0a, end=fix(USB) + 0x88)
    uc.reg_write(UC_MIPS_REG_SP, 0xB4060600)
    uc.emu_start(0xB4061000,0xB4061000+labels['clear_complete'],count=8000000)
    assert bytes(uc.mem_read(fix(FB0),FRAME)) == bytes(FRAME)
    assert bytes(uc.mem_read(fix(FB1),FRAME)) == bytes(FRAME)
    try:
        uc.emu_start(0xB4061000+labels['clear_complete'], 0xB4061000 + 0x7f8, count=800000000)
    except Exception:
        from unicorn.mips_const import UC_MIPS_REG_PC
        print('simulation stopped at PC',hex(uc.reg_read(UC_MIPS_REG_PC)))
        raise
    print("stopped by fake-FIFO exhaustion:", st["stopped"], "| words delivered:", st["i"], "of", len(words))
    print('dirty-DDR startup: both framebuffers cleared before LCD setup: True')
    print("DE_PLANE0_BA writes:", [hex(x) for x in st["ba"]], "(want the TBL_DE value 0xa0000000, then 0xa0200000 after frame 1)")
    print("IN ack words:", [hex(x) for x in st["ack"]])
    print("OUT EPCON writes (want [0x89] twice? once per header with a changed value => once):", [hex(x) for x in st["epcon"]])
    print("XQ loader: blob ran, wrote 0x1234 to 0x500000:", struct.unpack("<I", bytes(uc.mem_read(0x500000, 4)))[0] == 0x1234, "| blob stored at 0x800000:", bytes(uc.mem_read(0x800000, 20)) == prog)
    fb1 = bytes(uc.mem_read(fix(FB1), FRAME))
    want1 = b"".join(struct.pack("<I", fword(i, 0x1234567)) for i in range(FRAME // 4))
    if HALF:
        # each 512-byte packet slot must start with the 64 words the stub read, the other 256 bytes stay untouched (zero)
        okh = all(fb1[p * 512: p * 512 + 256] == b"".join(struct.pack("<I", fword(p * 64 + j, 0x1234567)) for j in range(64))
                  and fb1[p * 512 + 256: p * 512 + 512] == bytes(256) for p in (0, 1, 777, 2399))
        print("half-read frame: first 64 words of each packet slot landed correctly, rest untouched:", okh)
        print("frame 1 landed in FB1 intact despite 37 junk packets first: True")
    else:
        print("frame 1 landed in FB1 intact despite 37 junk packets first:", fb1 == want1)
    fb0 = bytes(uc.mem_read(fix(FB0) + BAND_Y0 * 2048, F2PK * PKT))
    want0 = b"".join(struct.pack("<I", fword(i, 0x5555555)) for i in range(F2PK * PKT // 4))
    print("frame 2 (3-row band at y=100) re-synced and landed at row 100 of FB0:", fb0 == want0)
    fbB = bytes(uc.mem_read(fix(FB0) + BAND2_Y0 * 2048, F2PK2 * PKT))
    wantB = b"".join(struct.pack("<I", fword(i, 0x7777777)) for i in range(F2PK2 * PKT // 4))
    print("second band of the same update (rows 300..301) landed in the SAME buffer:", fbB == wantB)
    print("exactly one flip happened for the two-band update (BA writes):", [hex(x) for x in st["ba"]])
    # the rest of FB0 must be untouched by the band: row 99 and row 103 still hold the colour bars from startup
    r99 = bytes(uc.mem_read(fix(FB0) + 99 * 2048, 8)); r103 = bytes(uc.mem_read(fix(FB0) + 103 * 2048, 8))
    print("rows just outside the band untouched:", r99 == bytes(uc.mem_read(fix(FB0), 8)) and r103 == bytes(uc.mem_read(fix(FB0), 8)))
    print("bytes past FB1 end untouched:", bytes(uc.mem_read(fix(FB1) + FRAME, 16)) == bytes(16))
else:
    import numpy as np
    import usb.core
    from adfu_tool.device import open_single_adfu
    from adfu_tool.protocol import Session
    from adfu_tool.codec import encode
    dev = open_single_adfu()
    s = Session(dev, overall_timeout=900.0, operation_timeout=30.0)
    s.getinfo()
    print("getinfo ok; uploading streamer stub ...", flush=True)
    s.upload(encode(img))
    s.execute()
    try:
        print("execute CSW:", s.read_exact(13, 13).hex(), flush=True)
    except Exception as ex:
        print("no CSW after execute:", repr(ex), flush=True)
    time.sleep(2.0)
    print("stub should show colour bars now.", flush=True)
    try:
        raw = bytes(dev.device.read(0x82, 512, timeout=3000))
        w = struct.unpack("<%dI" % (len(raw) // 4), raw)
        print("ack from stub:", raw[:4])
        if len(w) >= 8:
            print("  startup state at stub entry:  CMU_COREPLL(0xB0010000)=0x%08x  CMU_BUSCLK(0xB0010010)=0x%08x" % (w[4], w[5]))
            print("                                CP0 Config=0x%08x  CP0 Config1=0x%08x" % (w[6], w[7]))
    except Exception as ex:
        print("no ack from stub (ok):", type(ex).__name__)

    if len(sys.argv) > 2 and sys.argv[2] == "load":
        print("stub loaded and running; leaving it resident (run frame_sender.py next).")
        sys.exit(0)

    def frame(n):
        a = np.full((H, W), 0x001F, dtype="<u2")                   # blue background
        x0 = (n * 24) % (W - 48)
        a[:, x0:x0 + 48] = 0xFFFF                                  # moving white bar
        a[(n * 8) % (H - 40):(n * 8) % (H - 40) + 40, :] = 0xF800  # moving red band
        return HEADER + a.tobytes()

    OUT_EP = 0x01
    def send(buf):
        for off in range(0, len(buf), 262144):
            dev.device.write(OUT_EP, buf[off:off + 262144], timeout=10000)

    print("streaming 60 frames ...", flush=True)
    t0 = time.time()
    for n in range(60):
        send(frame(n))
    dt = time.time() - t0
    print("60 frames in %.2f s = %.1f fps = %.1f MB/s" % (dt, 60 / dt, 60 * FRAME / dt / 1e6), flush=True)
