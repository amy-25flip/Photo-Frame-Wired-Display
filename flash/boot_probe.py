# SPDX-License-Identifier: GPL-2.0-or-later
"""RAM-only SPI identification/backup through the resident V100 stage-1 loader.

Only SPI opcodes emitted: 0x9F (RDID), and ROM's 0x03 (READ). No program,
erase, write-enable, status-write or flash writer exists in this module.
Stop frame_watcher.py before use; it must leave diag21 resident in the frame.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'v100display'))
from mipsasm import *
import xq_load as x

SAVE=0xA0400800
BUFFER=0xA1000000
SPI=0xB0258000
ROM_INIT=0xBFC06C2C
ROM_EXIT=0xBFC06DD8
ROM_READ=0xBFC06E8C

def build(offset=0,length=64,jedec=False,stream=False):
    a=Asm(0x80800000)
    a.li(T0,SAVE)
    for i,r in enumerate([S0,S1,S2,S3,S4,S5,S6,S7,RA,SP]):a.sw(r,4*i,T0)
    a.sw(ZERO,40,T0)
    a.li(SP,0xA0F00000)
    def call(addr):a.li(T9,addr);a.jalr(T9);a.nop()
    call(ROM_INIT)
    if jedec:
        a.li(S0,SPI);a.li(S1,BUFFER)
        a.lw(T0,8,S0);a.ori(T0,T0,0x30);a.sw(T0,8,S0)
        a.li(T0,0x400c0);a.sw(T0,0,S0)
        a.li(T0,0x9f);a.sw(T0,16,S0)
        call(0xBFC070AC)
        a.bne(V0,ZERO,'spi_failed');a.nop()
        a.li(T0,0x040402c0);a.sw(T0,0,S0)
        a.lw(T0,8,S0);a.ori(T0,T0,0x30);a.sw(T0,8,S0)
        a.li(T1,16)
        a.label('clock_read');a.sw(ZERO,16,S0);a.addiu(T1,T1,-1)
        a.bne(T1,ZERO,'clock_read');a.nop()
        a.li(T2,16)
        a.label('rd_word');a.li(T3,4096)
        a.label('poll');a.addiu(T3,T3,-1);a.beq(T3,ZERO,'spi_failed');a.nop()
        a.lw(T0,8,S0);a.andi(T0,T0,0x40);a.bne(T0,ZERO,'poll');a.nop()
        a.lw(T0,12,S0);a.sw(T0,0,S1);a.addiu(S1,S1,4);a.addiu(T2,T2,-1)
        a.bne(T2,ZERO,'rd_word');a.nop()
        a.b('spi_done');a.nop()
        a.label('spi_failed');a.li(V0,32)
        a.label('spi_done');a.li(T0,SAVE);a.sw(V0,40,T0)
        a.li(T0,0x400d0);a.sw(T0,0,S0)
    else:
        a.li(A0,offset);a.li(A1,length);a.li(A2,BUFFER)
        call(ROM_READ)
        a.li(T0,SAVE);a.sw(V0,40,T0)
    call(ROM_EXIT)
    if stream:
        a.li(S0,0xB0290000);a.li(S1,BUFFER);a.li(S2,length//512)
        a.label('packet')
        a.label('wait_in');a.lbu(T0,0x17,S0);a.andi(T0,T0,2)
        a.bne(T0,ZERO,'wait_in');a.nop()
        a.li(T2,128)
        a.label('copy');a.lw(T0,0,S1);a.sw(T0,0x88,S0)
        a.addiu(S1,S1,4);a.addiu(T2,T2,-1);a.bne(T2,ZERO,'copy');a.nop()
        a.sb(ZERO,0x14,S0);a.li(T0,2);a.sb(T0,0x15,S0);a.sb(ZERO,0x17,S0)
        a.addiu(S2,S2,-1);a.bne(S2,ZERO,'packet');a.nop()
        # Wait for the final data packet before stage 1 emits XQD1.
        a.label('last_in');a.lbu(T0,0x17,S0);a.andi(T0,T0,2)
        a.bne(T0,ZERO,'last_in');a.nop()
    a.li(T0,SAVE)
    for i,r in enumerate([S0,S1,S2,S3,S4,S5,S6,S7,RA,SP]):a.lw(r,4*i,T0)
    a.jr(RA);a.nop()
    return a.assemble()

def identify(dev):
    x.xq_load(dev,build(jedec=True),0x00800000)
    words=x.cmd(dev,peeks=[BUFFER,BUFFER+4,BUFFER+8,SAVE+40])
    if words[3]:raise RuntimeError('RDID SPI timeout: '+str(words))
    data=struct.pack('<III',*words[:3])
    return dict(raw=data.hex(),jedec=data[:3].hex())

def read_chunk(dev,offset,length):
    assert offset%512==0 and length%512==0 and 0<length<=1024*1024
    x.xq_load(dev,build(offset,length,stream=True),0x00800000,wait=False)
    output=bytearray()
    while len(output)<length:
        data=bytes(dev.read(0x82,min(65536,length-len(output)),timeout=20000))
        if not data:raise RuntimeError('Empty backup packet')
        output.extend(data)
    tag,_=x.rd(dev,5000)
    if tag!=b'XQD1':raise RuntimeError('Missing end-of-read ack: '+repr(tag))
    status=x.cmd(dev,peeks=[SAVE+40])[0]
    if status:raise RuntimeError('ROM SPI read failed: '+hex(status))
    return bytes(output)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--jedec',action='store_true')
    ap.add_argument('--dump',type=Path)
    ap.add_argument('--size',type=lambda x:int(x,0),default=0)
    ap.add_argument('--expect-id',help='Exact JEDEC ID, required for a complete backup')
    ap.add_argument('--probe-read',type=Path,metavar='BACKUP',help='Read the first 512 B and compare them with the same bytes of your own flash backup file')
    args=ap.parse_args()
    if args.dump and (not args.expect_id or args.size<512 or args.size>16*1024*1024 or args.size%512):
        ap.error('Provide --expect-id and verified capacity in --size (max 16 MiB for 24-bit SPI READ)')
    dev=x.open_frame();x.cmd(dev)
    ident=identify(dev);print(json.dumps(ident),flush=True)
    if args.expect_id and ident['jedec'].lower()!=args.expect_id.lower():raise RuntimeError('Unexpected flash identity')
    if args.probe_read:
        data=read_chunk(dev,0,512)
        known=args.probe_read.read_bytes()[:512]
        print('first sector exact match:',data==known,flush=True)
        if data!=known:raise RuntimeError('Readback differs from your backup file')
    if args.dump:
        args.dump.parent.mkdir(parents=True,exist_ok=True)
        with args.dump.open('xb') as f:
            for offset in range(0,args.size,1024*1024):
                chunk=read_chunk(dev,offset,min(1024*1024,args.size-offset))
                f.write(chunk);f.flush()
                print('read',offset+len(chunk),'/',args.size,flush=True)
        sha=hashlib.sha256(args.dump.read_bytes()).hexdigest()
        print('SHA256',sha,flush=True)
        args.dump.with_suffix(args.dump.suffix+'.json').write_text(json.dumps(dict(**ident,size=args.size,sha256=sha),indent=2),encoding='utf-8')

if __name__=='__main__':main()
