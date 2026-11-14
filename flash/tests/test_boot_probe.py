# SPDX-License-Identifier: GPL-2.0-or-later
import sys,struct,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'v100display'))
import boot_probe as b
from unicorn import *
from unicorn.mips_const import *

class ProbeTests(unittest.TestCase):
    def emulate(self,jedec=False,length=512):
        u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        for base,size in [(0,0x2000000),(0x10258000,0x1000),(0x10290000,0x1000),(0x14060000,0x10000),(0x1fc00000,0x8000)]:u.mem_map(base,size)
        u.mem_write(0x800000,b.build(0,length,jedec=jedec,stream=not jedec))
        regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7]
        for i,r in enumerate(regs):u.reg_write(r,0x12340000+i)
        u.reg_write(UC_MIPS_REG_SP,0xA0401000);u.reg_write(UC_MIPS_REG_RA,0xB4061700)
        output=[];cmds=[];reads=[]
        payload=bytes((i%251 for i in range(length)))
        def on_code(uc,addr,size,_):
            if addr in (b.ROM_INIT,b.ROM_EXIT,0xBFC070AC,b.ROM_READ):
                if addr==b.ROM_READ:
                    reads.append((uc.reg_read(UC_MIPS_REG_A0),uc.reg_read(UC_MIPS_REG_A1)))
                    uc.mem_write(uc.reg_read(UC_MIPS_REG_A2)&0x1fffffff,payload)
                uc.reg_write(UC_MIPS_REG_V0,0)
                uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(UC_MIPS_REG_RA))
        def on_read(uc,access,addr,size,value,_):
            if addr==0x10258008:uc.mem_write(addr,struct.pack('<I',4))
            if addr==0x1025800c:uc.mem_write(addr,bytes.fromhex('ef4018ff'))
        def on_write(uc,access,addr,size,value,_):
            if addr==0x10258010:cmds.append(value)
            if addr==0x10290088:output.append(struct.pack('<I',value))
        u.hook_add(UC_HOOK_CODE,on_code)
        u.hook_add(UC_HOOK_MEM_READ,on_read)
        u.hook_add(UC_HOOK_MEM_WRITE,on_write)
        u.emu_start(0x80800000,0xB4061700,count=1000000)
        for i,r in enumerate(regs):self.assertEqual(u.reg_read(r),0x12340000+i)
        self.assertEqual(u.reg_read(UC_MIPS_REG_SP),0xA0401000)
        self.assertEqual(u.mem_read(b.SAVE&0x1fffffff,44)[40:],bytes(4))
        if jedec:
            self.assertEqual(cmds,[0x9f]+[0]*16)
            self.assertEqual(u.mem_read(b.BUFFER&0x1fffffff,3),bytes.fromhex('ef4018'))
        else:
            self.assertEqual(reads,[(0,length)])
            self.assertEqual(b''.join(output),payload)
    def test_rdid_only_uses_read_id_and_restores_registers(self):self.emulate(jedec=True)
    def test_one_packet_spi_read(self):self.emulate(length=512)
    def test_multiple_packets_spi_read(self):self.emulate(length=1536)

if __name__=='__main__':unittest.main()
