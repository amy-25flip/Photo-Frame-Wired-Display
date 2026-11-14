# SPDX-License-Identifier: GPL-2.0-or-later
"""Boot picture stored in the frame's SPI flash (blank region 0x72B000..0x79FFFF, 117 sectors = 479,232 bytes).

Layout at PIC_START: 16-byte header [b'V1PIC\\0\\0\\1' | u32 payload length | u32 crc32(payload)] followed by a JPEG (any size <= ~479 KB).
Write path = exactly the verified primitives of boot_flash.py (ROM SPI init/exit, ROM TX routine 0xBFC070AC, status polling, write enable per op),
extended to loop over sectors.  Safety:
  * the blob itself refuses any address outside [PIC_START, PIC_END) (checked before every erase/program) and any protected / busy chip
  * the host refuses to write unless the JEDEC id is c84017 and the region is currently blank (all 0xFF) or already holds a V1PIC image
  * full readback verification after writing; nothing outside the region is ever touched, the boot sectors are not involved
  * `clear` erases the region again (the flash is then exactly as before)
Needs the resident stage-1 stub (diag21/22), watcher stopped (exclusive USB ownership), same as boot_flash.py.

    python3 pic_flash.py status
    python3 pic_flash.py write picture.jpg [--fit contain|cover|stretch]     # any picture; converted to a 1024x600 JPEG
    python3 pic_flash.py clear
    python3 pic_flash.py read out.jpg
"""
import argparse, struct, sys, zlib
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'v100display'))
from mipsasm import *
import xq_load as x
import boot_probe as p

PIC_START, PIC_END = 0x72B000, 0x7A0000
SECTOR = 4096
DATA = 0xA1001000                          # DRAM staging area for the data to program (kseg1)
MAGIC = b'V1PIC\0\0\1'
HEADER = 16
MAX_PAYLOAD = PIC_END - PIC_START - HEADER


def build_writer(start, length):
    """Stage-2 blob: erase + program [start, start+length) from DRAM DATA. start/length are baked in and bounds-checked inside the blob."""
    assert start % SECTOR == 0 and length % SECTOR == 0 and length > 0
    assert PIC_START <= start and start + length <= PIC_END, 'outside the picture region'
    a = Asm(0x80800000)
    a.li(T0, p.SAVE)
    regs = [S0, S1, S2, S3, S4, S5, S6, S7, RA, SP]
    for i, r in enumerate(regs): a.sw(r, i * 4, T0)
    for off in range(40, 64, 4): a.sw(ZERO, off, T0)
    a.li(SP, 0xA0F00000)

    def rom(addr): a.li(T9, addr); a.jalr(T9); a.nop()
    def call(name): a.bal(name); a.nop()
    def end(): a.li(T0, 0x400d0); a.sw(T0, 0, S0)
    def begin(op):
        a.lw(T0, 8, S0); a.ori(T0, T0, 0x30); a.sw(T0, 8, S0)
        a.li(T0, 0x400c0); a.sw(T0, 0, S0)
        a.li(A0, op); call('byte')
    def one(op): begin(op); end()
    def status(op=5): a.li(A0, op); call('status')
    def wren():
        one(6); status(); a.andi(T0, V0, 3); a.li(T1, 2)
        a.bne(T0, T1, 'failed'); a.nop()

    rom(p.ROM_INIT); a.li(S0, p.SPI); a.li(S1, p.SAVE)
    status(); a.sw(V0, 44, S1)
    status(0x35); a.sw(V0, 48, S1)
    # refuse protected / busy chips (same checks as boot_flash.py); never alters protection or status registers
    a.lw(T0, 44, S1); a.andi(T0, T0, 0xfd); a.bne(T0, ZERO, 'failed'); a.nop()
    a.lw(T0, 48, S1); a.andi(T0, T0, 0x41); a.bne(T0, ZERO, 'failed'); a.nop()
    a.li(S2, start); a.li(S3, DATA); a.li(S4, length)
    a.label('page')
    # bounds check before every erase/program: PIC_START <= S2 < PIC_END
    a.li(T0, PIC_START); a.sltu(T1, S2, T0); a.bne(T1, ZERO, 'failed'); a.nop()
    a.li(T0, PIC_END); a.sltu(T1, S2, T0); a.beq(T1, ZERO, 'failed'); a.nop()
    a.andi(T0, S2, 0xFFF); a.bne(T0, ZERO, 'prog'); a.nop()
    wren(); begin(0x20); call('address'); end(); call('ready')          # erase the 4 KB sector that starts here
    a.li(T0, 1); a.sw(T0, 56, S1)
    a.label('prog')
    wren(); begin(2); call('address'); a.li(S5, 256)
    a.label('data'); a.lbu(A0, 0, S3); call('byte')
    a.addiu(S3, S3, 1); a.addiu(S5, S5, -1); a.bne(S5, ZERO, 'data'); a.nop()
    end(); call('ready')
    a.addiu(S2, S2, 256); a.addiu(S4, S4, -256); a.sw(S4, 60, S1)
    a.bne(S4, ZERO, 'page'); a.nop()
    one(4)
    a.b('cleanup'); a.nop()
    a.label('failed'); a.li(T0, p.SAVE); a.li(T1, 0xBAD00001); a.sw(T1, 40, T0)
    a.label('cleanup'); a.li(S0, p.SPI); end()
    rom(p.ROM_EXIT)
    a.li(T0, p.SAVE)
    for i, r in enumerate(regs): a.lw(r, i * 4, T0)
    a.jr(RA); a.nop()
    # --- subroutines, identical to boot_flash.py ---
    a.label('byte'); a.addiu(SP, SP, -16); a.sw(RA, 0, SP)
    a.sw(A0, 16, S0); rom(0xBFC070AC)
    a.bne(V0, ZERO, 'failed'); a.nop()
    a.lw(RA, 0, SP); a.addiu(SP, SP, 16); a.jr(RA); a.nop()
    a.label('address'); a.addiu(SP, SP, -16); a.sw(RA, 0, SP)
    for shift in (16, 8, 0):
        a.srl(A0, S2, shift); a.andi(A0, A0, 255); call('byte')
    a.lw(RA, 0, SP); a.addiu(SP, SP, 16); a.jr(RA); a.nop()
    a.label('status'); a.addiu(SP, SP, -16); a.sw(RA, 0, SP)
    a.lw(T0, 8, S0); a.ori(T0, T0, 0x30); a.sw(T0, 8, S0)
    a.li(T0, 0x400c0); a.sw(T0, 0, S0); call('byte')
    a.li(T0, 0x040402c0); a.sw(T0, 0, S0)
    a.lw(T0, 8, S0); a.ori(T0, T0, 0x30); a.sw(T0, 8, S0)
    a.li(T1, 16)
    a.label('clocks'); a.sw(ZERO, 16, S0); a.addiu(T1, T1, -1)
    a.bne(T1, ZERO, 'clocks'); a.nop()
    a.li(T2, 16); a.move(S6, ZERO)
    a.label('rxword'); a.li(T3, 4096)
    a.label('rxpoll'); a.addiu(T3, T3, -1); a.beq(T3, ZERO, 'failed'); a.nop()
    a.lw(T0, 8, S0); a.andi(T0, T0, 0x40); a.bne(T0, ZERO, 'rxpoll'); a.nop()
    a.lw(T0, 12, S0); a.or_(S6, S6, T0); a.addiu(T2, T2, -1)
    a.bne(T2, ZERO, 'rxword'); a.nop()
    end(); a.andi(V0, S6, 255)
    a.lw(RA, 0, SP); a.addiu(SP, SP, 16); a.jr(RA); a.nop()
    a.label('ready'); a.addiu(SP, SP, -16); a.sw(RA, 0, SP); a.li(S7, 200000)
    a.label('busy'); status(); a.andi(T0, V0, 1); a.beq(T0, ZERO, 'ready_done'); a.nop()
    a.addiu(S7, S7, -1); a.bne(S7, ZERO, 'busy'); a.nop()
    a.b('failed'); a.nop()
    a.label('ready_done'); a.andi(T0, V0, 2); a.bne(T0, ZERO, 'failed'); a.nop()
    a.lw(RA, 0, SP); a.addiu(SP, SP, 16); a.jr(RA); a.nop()
    return a.assemble()


# ------------------------------------------------------------------------------------------------ host side
def _win_python():
    import os
    p = os.environ.get('V100_WIN_PYTHON')
    if not p or not os.path.exists(p):
        raise SystemExit('set V100_WIN_PYTHON to the WSL path of a Windows python.exe that has numpy and opencv-python, '
                         'e.g. export V100_WIN_PYTHON=/mnt/c/Users/<you>/AppData/Local/Programs/Python/Python312/python.exe')
    return p


def _win_path(path):
    import os
    path = os.path.abspath(path)
    if path.startswith('/mnt/') and len(path) > 6 and path[6] == '/':
        return path[5].upper() + ':' + path[6:].replace('/', '\\')
    return path


def make_payload(picture, fit='contain', quality=None):
    """-> (JPEG bytes, quality). OpenCV is normally only in the Windows Python, so from WSL the conversion runs through it (V100_WIN_PYTHON)."""
    import subprocess, os
    try:
        import pic_prepare
        return pic_prepare.make_jpeg(picture, fit, MAX_PAYLOAD, quality)
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, '_prepared.jpg')
    cmd = [_win_python(), '-W', 'ignore', _win_path(os.path.join(here, 'pic_prepare.py')), _win_path(picture), _win_path(out),
           '--fit', fit, '--max', str(MAX_PAYLOAD)]
    if quality: cmd += ['--quality', str(quality)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode: raise SystemExit('picture conversion failed: ' + (r.stdout + r.stderr)[-300:])
    data = open(out, 'rb').read()
    os.remove(out)
    return data, int(r.stdout.split()[1].rstrip(','))


def pack(payload):
    return MAGIC + struct.pack('<II', len(payload), zlib.crc32(payload) & 0xffffffff) + payload


def read_region(dev, nbytes):
    out = bytearray()
    off = PIC_START
    while len(out) < nbytes:
        n = min(1024 * 1024, ((nbytes - len(out)) + 511) // 512 * 512)
        out += p.read_chunk(dev, off, n)
        off += n
    return bytes(out[:nbytes])


def read_picture(dev):
    """-> payload bytes (JPEG) if a valid V1PIC image is stored, else None."""
    head = p.read_chunk(dev, PIC_START, 512)
    if head[:8] != MAGIC: return None
    n, crc = struct.unpack('<II', head[8:16])
    if n == 0 or n > MAX_PAYLOAD: return None
    data = head[HEADER:] if n <= 512 - HEADER else head[HEADER:] + p.read_chunk(dev, PIC_START + 512, ((n - (512 - HEADER)) + 511) // 512 * 512)
    data = data[:n]
    return data if zlib.crc32(data) & 0xffffffff == crc else None


def check_identity(dev):
    ident = p.identify(dev)
    if ident['jedec'] != 'c84017': raise RuntimeError('wrong flash device %s' % ident)
    return ident


def write_region(dev, blob_bytes):
    padded = blob_bytes + b'\xff' * (-len(blob_bytes) % SECTOR)
    assert len(padded) <= PIC_END - PIC_START
    x.xq_load(dev, padded, DATA & 0x1fffffff, run=False)
    x.xq_load(dev, build_writer(PIC_START, len(padded)), 0x800000, timeout_ms=120000)
    res = x.cmd(dev, peeks=[p.SAVE + 40, p.SAVE + 44, p.SAVE + 48, p.SAVE + 60])
    if res[0]: raise RuntimeError('SPI operation failed %s; keep the frame connected' % list(map(hex, res)))
    after = read_region(dev, len(padded))
    if after != padded: raise RuntimeError('READBACK MISMATCH; keep the frame connected and tell me')
    return len(padded)


def region_state(dev):
    """'blank' | 'ours' | 'foreign' - never allow a write over foreign data."""
    cur = read_region(dev, PIC_END - PIC_START)
    if cur == b'\xff' * len(cur): return 'blank'
    if cur[:8] == MAGIC: return 'ours'
    return 'foreign'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['status', 'write', 'clear', 'read'])
    ap.add_argument('arg', nargs='?')
    ap.add_argument('--fit', default='contain', choices=['contain', 'cover', 'stretch'])
    ap.add_argument('--quality', type=int)
    a = ap.parse_args()
    dev = x.open_frame(); x.cmd(dev)
    print('flash:', check_identity(dev), flush=True)
    st = region_state(dev)
    print('picture region 0x%X..0x%X is %s' % (PIC_START, PIC_END, st), flush=True)
    if a.cmd == 'status':
        pic = read_picture(dev)
        print('stored picture: %s' % ('%d bytes JPEG, crc ok' % len(pic) if pic else 'none'))
    elif a.cmd == 'read':
        pic = read_picture(dev)
        if not pic: sys.exit('no valid picture stored')
        open(a.arg, 'wb').write(pic); print('wrote', a.arg, len(pic))
    elif a.cmd == 'clear':
        if st == 'foreign': sys.exit('region holds unknown data; refusing')
        print('erasing', write_region(dev, b'\xff' * SECTOR * ((PIC_END - PIC_START) // SECTOR)), 'bytes of the region')
    else:
        if st == 'foreign': sys.exit('region holds unknown data; refusing to write')
        if not a.arg: sys.exit('give a picture file')
        payload, q = make_payload(a.arg, a.fit, a.quality)
        n = write_region(dev, pack(payload))
        print('WROTE %d bytes (JPEG %d bytes, quality %d) and verified the readback byte for byte' % (n, len(payload), q))
        assert read_picture(dev) == payload


if __name__ == '__main__':
    main()
