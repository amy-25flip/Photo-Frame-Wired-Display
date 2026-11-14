# SPDX-License-Identifier: GPL-2.0-or-later
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'v100display'))
import struct,unittest
from pathlib import Path
from prepare_boot_patch import prepare,BACKUP
from unicorn import *
from unicorn.mips_const import *

@unittest.skipUnless(BACKUP.exists(), 'needs YOUR own flash backup: set V100_FLASH_BACKUP=/path/to/flash-backup.bin (never commit it)')
class BootPatchTest(unittest.TestCase):
    def test_actual_patched_return_path(self):
        # Run the exact patched module instructions through both stock epilogues.
        original=BACKUP.read_bytes();patched=prepare(original)
        u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        u.mem_map(0x03080000,0x20000);u.mem_map(0x100000,0x10000)
        u.mem_write(0x03080000,patched[0x9400:0x18c00])
        sp=0xa0100000;outer=sp+168;end=0x83080e60
        u.reg_write(UC_MIPS_REG_SP,sp)
        u.mem_write((sp&0x1fffffff)+164,struct.pack('<I',0x83084590))
        u.mem_write((outer&0x1fffffff)+64,struct.pack('<I',end))
        visited=[]
        def hook(uc,addr,size,_):
            visited.append(addr)
            if addr==0x8308bf14:uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(UC_MIPS_REG_RA))
        u.hook_add(UC_HOOK_CODE,hook)
        u.emu_start(0x83083004,end,count=500)
        self.assertEqual(u.reg_read(UC_MIPS_REG_V0),0x30000001)
        self.assertEqual(u.reg_read(UC_MIPS_REG_SP),outer+72)
        self.assertIn(0x83082e68,visited)
        self.assertIn(0x830845bc,visited)
        self.assertNotIn(0x83083014,visited)
        self.assertNotIn(0x8308302c,visited)

if __name__=='__main__':unittest.main()
