# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a checksum-neutral single-sector direct-ADFU boot patch offline."""
import hashlib,json,struct
from pathlib import Path
from analyze_direct_boot import analyze, BACKUP

def prepare(original):
    analyze(original)
    result=bytearray(original)
    struct.pack_into('<II',result,0xc404,0x3c023000,0x34420001)
    # 0x3014 is beyond an always-taken branch (delay slot is 0x3010).
    # Preserve the module's existing 32-bit additive checksum.
    delta=sum(struct.unpack('<2I',original[0xc404:0xc40c]))-0x3c023000-0x34420001
    old=struct.unpack_from('<I',original,0xc414)[0]
    struct.pack_into('<I',result,0xc414,(old+delta)&0xffffffff)
    sum32=lambda b:sum(struct.unpack('<%dI'%(len(b)//4),b))&0xffffffff
    assert sum32(result[0x9400:0x18c00])==sum32(original[0x9400:0x18c00])
    assert sum32(result)==sum32(original)
    assert result[:0xc000]==original[:0xc000] and result[0xd000:]==original[0xd000:]
    # Reject incoming direct branches/jumps or data pointers to the compensation word.
    module=original[0x9400:0x18c00]
    incoming=[]
    for off in range(0,len(module),4):
        w=struct.unpack_from('<I',module,off)[0]; op=w>>26; pc=0xc3080000+off
        target=None
        if op in (2,3):target=(pc&0xf0000000)|((w&0x3ffffff)<<2)
        elif op in (1,4,5,6,7,20,21,22,23):
            imm=w&0xffff;imm=imm-65536 if imm&32768 else imm
            target=pc+4+imm*4
        if target==0xc3083014 or w==0xc3083014:incoming.append(hex(pc))
    assert not incoming,incoming
    return bytes(result)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args()
    result=prepare(BACKUP.read_bytes())
    with a.output.open('xb') as f:f.write(result)
    manifest={'status':'offline candidate; hardware write not performed','sha256':hashlib.sha256(result).hexdigest(),
              'sector':'0xc000','sector_size':4096,'modified_words':['0xc404','0xc408','0xc414'],
              'module_checksum':'unchanged','directory':'unchanged','boot_records':'unchanged',
              'trailer_0x27fc':'unchanged; global additive sum preserved'}
    a.output.with_suffix('.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest,indent=2))
