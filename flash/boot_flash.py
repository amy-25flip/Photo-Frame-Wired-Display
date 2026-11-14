# SPDX-License-Identifier: GPL-2.0-or-later
"""Exact-device single-sector SPI writer. Default is read-only status.

Only --apply/--restore may erase, and only sector 0xC000. Both require the
known original backup, matching JEDEC, and matching current sector contents.
"""
import argparse,hashlib,json,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'v100display'))
from mipsasm import *
import xq_load as x
import boot_probe as p
from prepare_boot_patch import prepare,BACKUP

DATA=0xA1001000
SECTOR=0xC000

def build(mode='status'):
    assert mode in ('status','wel-test','apply','program-identical')
    a=Asm(0x80800000)
    a.li(T0,p.SAVE)
    regs=[S0,S1,S2,S3,S4,S5,S6,S7,RA,SP]
    for i,r in enumerate(regs):a.sw(r,i*4,T0)
    for off in range(40,64,4):a.sw(ZERO,off,T0)
    a.li(SP,0xA0F00000)
    def rom(addr):a.li(T9,addr);a.jalr(T9);a.nop()
    def call(name):a.bal(name);a.nop()
    def end():a.li(T0,0x400d0);a.sw(T0,0,S0)
    def begin(op):
        a.lw(T0,8,S0);a.ori(T0,T0,0x30);a.sw(T0,8,S0)
        a.li(T0,0x400c0);a.sw(T0,0,S0)
        a.li(A0,op);call('byte')
    def one(op):begin(op);end()
    def status(op=5):a.li(A0,op);call('status')
    def wren():
        one(6);status();a.andi(T0,V0,3);a.li(T1,2)
        a.bne(T0,T1,'failed');a.nop()
    rom(p.ROM_INIT);a.li(S0,p.SPI);a.li(S1,p.SAVE)
    status();a.sw(V0,44,S1)
    status(0x35);a.sw(V0,48,S1)
    if mode!='status':
        # Refuse protected/busy chips; do not alter protection or status registers.
        a.lw(T0,44,S1);a.andi(T0,T0,0xfd);a.bne(T0,ZERO,'failed');a.nop()
        a.lw(T0,48,S1);a.andi(T0,T0,0x41);a.bne(T0,ZERO,'failed');a.nop()
        wren()
        if mode=='wel-test':
            one(4);status();a.sw(V0,52,S1)
            a.andi(T0,V0,3);a.bne(T0,ZERO,'failed');a.nop()
        else:
            a.li(S2,SECTOR);a.li(S3,DATA);a.li(S4,4096)
            if mode=='apply':
                begin(0x20);call('address');end();call('ready')
                a.li(T0,1);a.sw(T0,56,S1)
            # Program all sixteen 256-byte pages, without crossing a page boundary.
            a.label('page');wren();begin(2);call('address');a.li(S5,256)
            a.label('data');a.lbu(A0,0,S3);call('byte')
            a.addiu(S3,S3,1);a.addiu(S5,S5,-1);a.bne(S5,ZERO,'data');a.nop()
            end();call('ready')
            a.addiu(S2,S2,256);a.addiu(S4,S4,-256);a.sw(S4,60,S1)
            a.bne(S4,ZERO,'page');a.nop()
            one(4)
    a.b('cleanup');a.nop()
    a.label('failed');a.li(T0,p.SAVE);a.li(T1,0xBAD00001);a.sw(T1,40,T0)
    a.label('cleanup');a.li(S0,p.SPI);end()
    rom(p.ROM_EXIT)
    a.li(T0,p.SAVE)
    for i,r in enumerate(regs):a.lw(r,i*4,T0)
    a.jr(RA);a.nop()
    # Byte transfer uses the ROM's exact bounded TX-completion routine.
    a.label('byte');a.addiu(SP,SP,-16);a.sw(RA,0,SP)
    a.sw(A0,16,S0);rom(0xBFC070AC)
    a.bne(V0,ZERO,'failed');a.nop()
    a.lw(RA,0,SP);a.addiu(SP,SP,16);a.jr(RA);a.nop()
    a.label('address');a.addiu(SP,SP,-16);a.sw(RA,0,SP)
    for shift in (16,8,0):
        a.srl(A0,S2,shift);a.andi(A0,A0,255);call('byte')
    a.lw(RA,0,SP);a.addiu(SP,SP,16);a.jr(RA);a.nop()
    # Read 64 status bytes using the already-proven ROM receive phase.
    a.label('status');a.addiu(SP,SP,-16);a.sw(RA,0,SP)
    a.lw(T0,8,S0);a.ori(T0,T0,0x30);a.sw(T0,8,S0)
    a.li(T0,0x400c0);a.sw(T0,0,S0);call('byte')
    a.li(T0,0x040402c0);a.sw(T0,0,S0)
    a.lw(T0,8,S0);a.ori(T0,T0,0x30);a.sw(T0,8,S0)
    a.li(T1,16)
    a.label('clocks');a.sw(ZERO,16,S0);a.addiu(T1,T1,-1)
    a.bne(T1,ZERO,'clocks');a.nop()
    a.li(T2,16);a.move(S6,ZERO)
    a.label('rxword');a.li(T3,4096)
    a.label('rxpoll');a.addiu(T3,T3,-1);a.beq(T3,ZERO,'failed');a.nop()
    a.lw(T0,8,S0);a.andi(T0,T0,0x40);a.bne(T0,ZERO,'rxpoll');a.nop()
    a.lw(T0,12,S0);a.or_(S6,S6,T0);a.addiu(T2,T2,-1)
    a.bne(T2,ZERO,'rxword');a.nop()
    end();a.andi(V0,S6,255)
    a.lw(RA,0,SP);a.addiu(SP,SP,16);a.jr(RA);a.nop()
    a.label('ready');a.addiu(SP,SP,-16);a.sw(RA,0,SP);a.li(S7,100000)
    a.label('busy');status();a.andi(T0,V0,1);a.beq(T0,ZERO,'ready_done');a.nop()
    a.addiu(S7,S7,-1);a.bne(S7,ZERO,'busy');a.nop()
    a.b('failed');a.nop()
    a.label('ready_done');a.andi(T0,V0,2);a.bne(T0,ZERO,'failed');a.nop()
    a.lw(RA,0,SP);a.addiu(SP,SP,16);a.jr(RA);a.nop()
    return a.assemble()

def main():
    ap=argparse.ArgumentParser();g=ap.add_mutually_exclusive_group()
    g.add_argument('--wel-test',action='store_true');g.add_argument('--program-identical',action='store_true')
    g.add_argument('--apply',action='store_true');g.add_argument('--restore',action='store_true')
    args=ap.parse_args()
    original=BACKUP.read_bytes();patched=prepare(original)
    dev=x.open_frame();x.cmd(dev)
    identity=p.identify(dev);print('identity',identity,flush=True)
    if identity['jedec']!='c84017':raise RuntimeError('Wrong flash device')
    current=p.read_chunk(dev,SECTOR,4096)
    stock=original[SECTOR:SECTOR+4096];target=patched[SECTOR:SECTOR+4096]
    if current not in (stock,target):raise RuntimeError('Current boot sector differs from both verified versions')
    write=args.apply or args.restore or args.program_identical
    if args.restore:desired=stock
    elif args.program_identical:desired=current
    else:desired=target
    if write:
        if current==desired and not args.program_identical:
            print('Already matches requested image; no write');return
        x.xq_load(dev,desired,DATA&0x1fffffff,run=False)
    mode='apply' if args.apply or args.restore else 'program-identical' if args.program_identical else 'wel-test' if args.wel_test else 'status'
    print('mode',mode,'sector',hex(SECTOR),flush=True)
    x.xq_load(dev,build(mode),0x800000,timeout_ms=60000)
    result=x.cmd(dev,peeks=[p.SAVE+40,p.SAVE+44,p.SAVE+48,p.SAVE+52])
    progress=x.cmd(dev,peeks=[p.SAVE+56,p.SAVE+60])
    print('result',list(map(hex,result)),'progress',list(map(hex,progress)),flush=True)
    if result[0]:raise RuntimeError('SPI operation failed; keep connected for recovery')
    after=p.read_chunk(dev,SECTOR,4096)
    if after != (desired if write else current):raise RuntimeError('SECTOR READBACK FAILED; keep connected')
    print('SECTOR READBACK EXACT MATCH',hashlib.sha256(after).hexdigest(),flush=True)

if __name__=='__main__':main()
