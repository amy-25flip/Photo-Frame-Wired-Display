# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only analysis. Produces a patch proposal, never a flashable image."""
import hashlib
import json
import struct
import os
from pathlib import Path

# YOUR OWN full 8 MiB flash backup (read with boot_probe.py --dump). Never commit or share it: it is proprietary vendor firmware.
BACKUP = Path(os.environ.get('V100_FLASH_BACKUP', 'flash-backup.bin'))
EXPECTED = 'c71b554e7f6e7631ccb7bc85d685a7f0dfdb0a04a93e416bb1586e7ebb9b1cf0'

def analyze(data):
    assert len(data) == 0x800000
    assert hashlib.sha256(data).hexdigest() == EXPECTED
    word = lambda off: struct.unpack_from('<I', data, off)[0]
    def sum32(start, end):
        return sum(struct.unpack('<%dI' % ((end-start)//4), data[start:end])) & 0xffffffff
    assert word(0x1f4) == 0x42746341
    assert word(0x1f8) == 0x55aa6d72
    assert (sum32(0, 0x1fc)+0x1234)&0xffffffff == word(0x1fc)
    assert struct.unpack_from('<H', data, 0x23fc)[0] == 0x55aa
    assert sum(struct.unpack('<%dH' % ((0x23fe-0x200)//2), data[0x200:0x23fe]))&0xffff == struct.unpack_from('<H', data, 0x23fe)[0]
    modules = []
    for off in range(0x2400, 0x27e0, 32):
        name = data[off:off+12].split(b'\0')[0]
        if not name or any(c<32 or c>126 for c in name):
            break
        start, length, checksum = struct.unpack_from('<III', data, off+20)
        start *= 512
        assert sum32(start, start+length) == checksum, name
        modules.append({'name':name.decode('ascii'), 'offset':hex(start), 'length':length})
    assert sum32(0x2400,0x27f4) == word(0x27f4)
    original = data[0xc404:0xc40c]
    assert original == bytes.fromhex('cf0ac20c2120c002')
    replacement = struct.pack('<II',0x3c023000,0x34420001)
    return {
        'status':'PROPOSAL ONLY; NOT READY TO FLASH',
        'backup_sha256':EXPECTED,
        'verified':['ROM boot-record checksum','SRAM second-stage checksum', 'all listed module checksums','boot directory checksum'],
        'modules':modules,
        'proposal':{'flash_offset':'0xc404','original_hex':original.hex(),'replacement_hex':replacement.hex(),
                    'meaning':'Replace RunModeTest call and delay slot with v0=0x30000001; existing branch returns before LCD setup.'},
        'unresolved':['global trailer at flash 0x27fc','verified flash writer and power-loss recovery','physical confirmation that this earlier path leaves panel blank'],
        'no_flash_image_generated':True,
    }

if __name__ == '__main__':
    print(json.dumps(analyze(BACKUP.read_bytes()),indent=2))
