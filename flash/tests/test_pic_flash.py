# SPDX-License-Identifier: GPL-2.0-or-later
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'v100display'))
import struct, unittest
from unicorn import *
from unicorn.mips_const import *
import pic_flash as f

REGION = f.PIC_END - f.PIC_START


class PicFlashTests(unittest.TestCase):
    def run_model(self, start, nsectors, protected=False, fail_tx=False):
        length = nsectors * 4096
        u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        for addr, size in [(0, 0x2000000), (0x10258000, 0x1000), (0x14060000, 0x10000), (0x1fc00000, 0x8000)]:
            u.mem_map(addr, size)
        u.mem_write(0x800000, f.build_writer(start, length))
        payload = bytes((i * 37 + 13) & 255 for i in range(length))
        u.mem_write(f.DATA & 0x1fffffff, payload)
        flash = {}                                   # absolute address -> value, initially "programmed" garbage 0x55 inside the region only
        for a in range(f.PIC_START, f.PIC_END): flash[a] = 0x55
        wel = False; cmd = []; read_mode = False; commands = []; erase = []; program = []
        regs = [UC_MIPS_REG_S0, UC_MIPS_REG_S1, UC_MIPS_REG_S2, UC_MIPS_REG_S3, UC_MIPS_REG_S4, UC_MIPS_REG_S5, UC_MIPS_REG_S6, UC_MIPS_REG_S7]
        for i, r in enumerate(regs): u.reg_write(r, 0xface0000 + i)
        u.reg_write(UC_MIPS_REG_SP, 0xa0401000); u.reg_write(UC_MIPS_REG_RA, 0xb4061700)

        def finish():
            nonlocal wel
            if not cmd: return
            op = cmd[0]; commands.append(bytes(cmd))
            if op == 6: wel = True
            elif op == 4: wel = False
            elif op in (2, 0x20):
                self.assertTrue(wel)
                addr = int.from_bytes(bytes(cmd[1:4]), 'big')
                self.assertGreaterEqual(addr, f.PIC_START); self.assertLess(addr, f.PIC_END)        # NEVER outside the region
                if op == 0x20:
                    self.assertEqual(len(cmd), 4); self.assertEqual(addr % 4096, 0)
                    erase.append(addr)
                    for a in range(addr, addr + 4096): flash[a] = 0xff
                else:
                    data = bytes(cmd[4:]); self.assertEqual(len(data), 256); self.assertEqual(addr % 256, 0)
                    for i, v in enumerate(data): flash[addr + i] &= v
                    program.append(addr)
                wel = False

        def write(uc, access, addr, size, value, _):
            nonlocal cmd, read_mode
            if addr == 0x10258000:
                if value == 0x400c0: cmd = []; read_mode = False
                elif value == 0x040402c0: read_mode = True
                elif value == 0x400d0: finish(); cmd = []; read_mode = False
            elif addr == 0x10258010 and not read_mode: cmd.append(value & 255)

        def read(uc, access, addr, size, value, _):
            if addr == 0x10258008: uc.mem_write(addr, struct.pack('<I', 4))
            elif addr == 0x1025800c:
                status = (0x04 if protected else 0) | (2 if wel else 0) if cmd[0] == 5 else 0
                uc.mem_write(addr, bytes([status]) * 4)

        def code(uc, addr, size, _):
            if addr in (f.p.ROM_INIT, f.p.ROM_EXIT, 0xbfc070ac):
                uc.reg_write(UC_MIPS_REG_V0, 32 if fail_tx and addr == 0xbfc070ac else 0)
                uc.reg_write(UC_MIPS_REG_PC, uc.reg_read(UC_MIPS_REG_RA))

        u.hook_add(UC_HOOK_MEM_WRITE, write); u.hook_add(UC_HOOK_MEM_READ, read); u.hook_add(UC_HOOK_CODE, code)
        u.emu_start(0x80800000, 0xb4061700, count=200000000)
        for i, r in enumerate(regs): self.assertEqual(u.reg_read(r), 0xface0000 + i)
        self.assertEqual(u.reg_read(UC_MIPS_REG_SP), 0xa0401000)
        error = struct.unpack('<I', u.mem_read((f.p.SAVE & 0x1fffffff) + 40, 4))[0]
        return flash, payload, commands, erase, program, error

    def test_three_sectors_erase_and_program(self):
        start = f.PIC_START
        flash, payload, cmd, erase, program, error = self.run_model(start, 3)
        self.assertEqual(error, 0)
        self.assertEqual(bytes(flash[a] for a in range(start, start + 3 * 4096)), payload)
        self.assertEqual(erase, [start, start + 4096, start + 8192])
        self.assertEqual(program, list(range(start, start + 3 * 4096, 256)))
        self.assertTrue(all(flash[a] == 0x55 for a in range(start + 3 * 4096, f.PIC_END)))          # rest of the region untouched
        self.assertTrue(all(c[0] in (2, 4, 5, 6, 0x20, 0x35) for c in cmd))

    def test_last_sectors_of_region(self):
        start = f.PIC_END - 2 * 4096
        flash, payload, cmd, erase, program, error = self.run_model(start, 2)
        self.assertEqual(error, 0)
        self.assertEqual(bytes(flash[a] for a in range(start, f.PIC_END)), payload)

    def test_out_of_region_cannot_be_built(self):
        with self.assertRaises(AssertionError): f.build_writer(f.PIC_START - 4096, 4096)
        with self.assertRaises(AssertionError): f.build_writer(f.PIC_END - 4096, 8192)
        with self.assertRaises(AssertionError): f.build_writer(0xC000, 4096)                        # the boot-patch sector

    def test_protected_chip_rejected_before_any_write(self):
        _, _, cmd, erase, program, error = self.run_model(f.PIC_START, 1, protected=True)
        self.assertNotEqual(error, 0); self.assertFalse(erase or program)
        self.assertNotIn(6, [c[0] for c in cmd])

    def test_tx_timeout_aborts_without_erasing(self):
        _, _, _, erase, program, error = self.run_model(f.PIC_START, 1, fail_tx=True)
        self.assertNotEqual(error, 0); self.assertFalse(erase or program)

    def test_header_pack(self):
        data = f.pack(b'abc')
        self.assertEqual(data[:8], f.MAGIC); self.assertEqual(struct.unpack('<I', data[8:12])[0], 3)


if __name__ == '__main__':
    unittest.main()
