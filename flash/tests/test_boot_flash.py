# SPDX-License-Identifier: GPL-2.0-or-later
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'v100display'))
import struct,unittest
from unicorn import *
from unicorn.mips_const import *
import boot_flash as f

class FlashTests(unittest.TestCase):
    def run_model(self,mode,protected=False,fail_tx=False):
        u=Uc(UC_ARCH_MIPS,UC_MODE_MIPS32|UC_MODE_LITTLE_ENDIAN)
        for addr,size in [(0,0x2000000),(0x10258000,0x1000),(0x14060000,0x10000),(0x1fc00000,0x8000)]:u.mem_map(addr,size)
        u.mem_write(0x800000,f.build(mode))
        payload=bytes((i*37+13)&255 for i in range(4096));u.mem_write(f.DATA&0x1fffffff,payload)
        flash=bytearray(b'\x55'*0x1000)
        wel=False;cmd=[];read_mode=False;commands=[];erase=[];program=[]
        regs=[UC_MIPS_REG_S0,UC_MIPS_REG_S1,UC_MIPS_REG_S2,UC_MIPS_REG_S3,UC_MIPS_REG_S4,UC_MIPS_REG_S5,UC_MIPS_REG_S6,UC_MIPS_REG_S7]
        for i,r in enumerate(regs):u.reg_write(r,0xface0000+i)
        u.reg_write(UC_MIPS_REG_SP,0xa0401000);u.reg_write(UC_MIPS_REG_RA,0xb4061700)
        def finish():
            nonlocal wel
            if not cmd:return
            op=cmd[0];commands.append(bytes(cmd))
            if op==6:wel=True
            elif op==4:wel=False
            elif op in (2,0x20):
                self.assertTrue(wel);addr=int.from_bytes(bytes(cmd[1:4]),'big')
                self.assertGreaterEqual(addr,f.SECTOR);self.assertLess(addr,f.SECTOR+4096)
                if op==0x20:
                    self.assertEqual(len(cmd),4);erase.append(addr);flash[:]=b'\xff'*4096
                else:
                    data=bytes(cmd[4:]);self.assertEqual(len(data),256);self.assertEqual(addr%256,0)
                    for i,v in enumerate(data):flash[addr-f.SECTOR+i]&=v
                    program.append(addr)
                wel=False
        def write(uc,access,addr,size,value,_):
            nonlocal cmd,read_mode
            if addr==0x10258000:
                if value==0x400c0:cmd=[];read_mode=False
                elif value==0x040402c0:read_mode=True
                elif value==0x400d0:finish();cmd=[];read_mode=False
            elif addr==0x10258010 and not read_mode:cmd.append(value&255)
        def read(uc,access,addr,size,value,_):
            if addr==0x10258008:uc.mem_write(addr,struct.pack('<I',4))
            elif addr==0x1025800c:
                status=(0x04 if protected else 0)|(2 if wel else 0) if cmd[0]==5 else 0
                uc.mem_write(addr,bytes([status])*4)
        def code(uc,addr,size,_):
            if addr in (f.p.ROM_INIT,f.p.ROM_EXIT,0xbfc070ac):
                uc.reg_write(UC_MIPS_REG_V0,32 if fail_tx and addr==0xbfc070ac else 0)
                uc.reg_write(UC_MIPS_REG_PC,uc.reg_read(UC_MIPS_REG_RA))
        u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_MEM_READ,read);u.hook_add(UC_HOOK_CODE,code)
        u.emu_start(0x80800000,0xb4061700,count=3000000)
        for i,r in enumerate(regs):self.assertEqual(u.reg_read(r),0xface0000+i)
        self.assertEqual(u.reg_read(UC_MIPS_REG_SP),0xa0401000)
        error=struct.unpack('<I',u.mem_read((f.p.SAVE&0x1fffffff)+40,4))[0]
        return flash,payload,commands,erase,program,error
    def test_exact_sector_erase_and_pages(self):
        flash,payload,cmd,erase,program,error=self.run_model('apply')
        self.assertEqual(error,0);self.assertEqual(flash,payload)
        self.assertEqual(erase,[0xc000]);self.assertEqual(program,list(range(0xc000,0xd000,256)))
        self.assertTrue(all(c[0] in (2,4,5,6,0x20,0x35) for c in cmd))
    def test_protection_rejects_before_write_enable(self):
        _,_,cmd,erase,program,error=self.run_model('apply',protected=True)
        self.assertNotEqual(error,0);self.assertFalse(erase or program)
        self.assertNotIn(6,[c[0] for c in cmd])
    def test_tx_timeout_aborts_without_erasing(self):
        _,_,_,erase,program,error=self.run_model('apply',fail_tx=True)
        self.assertNotEqual(error,0);self.assertFalse(erase or program)
    def test_status_is_read_only(self):
        _,_,cmd,erase,program,error=self.run_model('status')
        self.assertEqual(error,0);self.assertEqual([c[0] for c in cmd],[5,0x35])
        self.assertFalse(erase or program)
    def test_enable_disable_without_data_writes(self):
        _,_,cmd,erase,program,error=self.run_model('wel-test')
        self.assertEqual(error,0);self.assertFalse(erase or program)
        self.assertEqual([c[0] for c in cmd],[5,0x35,6,5,4,5])

if __name__=='__main__':unittest.main()
