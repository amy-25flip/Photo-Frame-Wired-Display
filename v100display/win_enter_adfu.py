#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""V100 normal USB storage -> RAM-loader mode, without a button or flash writes.

Proven on this frame: 12-byte CDB CB 21 00 00 00 00 00 00 02 00 00 00,
two-byte IN reply FF 00, then standard START STOP UNIT / eject (1B ... 02).
The length is BIG-ENDIAN at CDB[7:9], not CDB[7] and not CDB[10].
Only disks whose live PnP ancestry includes USB VID_10D6&PID_1101 qualify.
An IOCTL success or timeout is NOT evidence of transition: require ADFU arrival.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import re
import struct
import subprocess
import time

NORMAL = 'USB\\VID_10D6&PID_1101'
ADFU = 'USB\\VID_10D6&PID_10D6'
MODE_CDB = bytes.fromhex('cb 21 00 00 00 00 00 00 02 00 00 00')
EJECT_CDB = bytes.fromhex('1b 00 00 00 02 00')
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

class SCSI_PTD(c.Structure):
    _fields_ = [('Length', w.USHORT), ('ScsiStatus', w.BYTE),
                ('PathId', w.BYTE), ('TargetId', w.BYTE), ('Lun', w.BYTE),
                ('CdbLength', w.BYTE), ('SenseInfoLength', w.BYTE), ('DataIn', w.BYTE),
                ('DataTransferLength', w.ULONG), ('TimeOutValue', w.ULONG),
                ('DataBuffer', c.c_void_p), ('SenseInfoOffset', w.ULONG), ('Cdb', w.BYTE*16)]

def kernel():
    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    k.CreateFileW.restype = w.HANDLE
    k.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
    k.DeviceIoControl.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    return k

def open_path(path, access=0xc0000000):
    h = kernel().CreateFileW(path, access, 3, None, 3, 0, None)
    if h == c.c_void_p(-1).value:
        raise OSError(c.get_last_error(), 'Cannot open '+path)
    return h

def scsi(path, cdb, count=0, direction=1):
    if len(cdb)>16 or count>4096: raise ValueError('Invalid diagnostic command')
    k, h = kernel(), open_path(path)
    try:
        buf=c.create_string_buffer(c.sizeof(SCSI_PTD)+32)
        p=SCSI_PTD.from_buffer(buf)
        data=c.create_string_buffer(max(count,1))
        p.Length=c.sizeof(SCSI_PTD)
        p.CdbLength,p.SenseInfoLength,p.DataIn=len(cdb),32,direction
        p.DataTransferLength,p.TimeOutValue=count,5
        p.DataBuffer,p.SenseInfoOffset=c.addressof(data),c.sizeof(SCSI_PTD)
        for i,b in enumerate(cdb): p.Cdb[i]=b
        ret=w.DWORD()
        ok=k.DeviceIoControl(h,0x4d014,buf,len(buf),buf,len(buf),c.byref(ret),None)
        return dict(ok=bool(ok),error=c.get_last_error() if not ok else 0,
                    status=p.ScsiStatus,data=data.raw[:p.DataTransferLength].hex(),
                    sense=bytes(buf)[c.sizeof(SCSI_PTD):].hex())
    finally: k.CloseHandle(h)

def ancestry(instance):
    cfg=c.WinDLL('cfgmgr32')
    cfg.CM_Locate_DevNodeW.argtypes=[c.POINTER(w.ULONG),w.LPWSTR,w.ULONG]
    cfg.CM_Get_Parent.argtypes=[c.POINTER(w.ULONG),w.ULONG,w.ULONG]
    cfg.CM_Get_Device_IDW.argtypes=[w.ULONG,w.LPWSTR,w.ULONG,w.ULONG]
    node=w.ULONG()
    if cfg.CM_Locate_DevNodeW(c.byref(node),instance,0): return []
    result=[]
    for _ in range(12):
        name=c.create_unicode_buffer(1024)
        if cfg.CM_Get_Device_IDW(node,name,len(name),0): break
        result.append(name.value)
        parent=w.ULONG()
        if cfg.CM_Get_Parent(c.byref(parent),node,0): break
        node=parent
    return result

def matches_frame(chain):
    return any(x.upper().startswith(NORMAL+'\\') for x in chain)

def disk_number(path):
    try: h=open_path(path,0)
    except OSError: return None
    k=kernel()
    try:
        buf=c.create_string_buffer(12); n=w.DWORD()
        if k.DeviceIoControl(h,0x2d1080,None,0,buf,12,c.byref(n),None):
            return struct.unpack('<III',buf.raw)[1]
    finally: k.CloseHandle(h)
    return None

def frame_targets():
    script="Get-CimInstance Win32_DiskDrive | Where-Object Model -eq 'actions media-player USB Device' | Select-Object DeviceID,PNPDeviceID,Index | ConvertTo-Json -Compress"
    proc=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,timeout=30,creationflags=NOWIN)
    if proc.returncode: raise RuntimeError(proc.stderr.strip())
    if not proc.stdout.strip(): return []
    rows=json.loads(proc.stdout)
    if isinstance(rows,dict): rows=[rows]
    targets=[]
    for row in rows:
        chain=ancestry(row['PNPDeviceID'])
        if matches_frame(chain):
            row['Ancestors']=chain
            row['Volumes']=[]
            targets.append(row)
    mask=kernel().GetLogicalDrives()
    for i in range(26):
        if mask & (1<<i):
            path='\\\\.\\'+chr(65+i)+':'
            number=disk_number(path)
            for row in targets:
                if number==row['Index']: row['Volumes'].append(path)
    # First LUN is the control interface, even with no card in that slot.
    return sorted(targets,key=lambda r:(not r['PNPDeviceID'].endswith('&0'),r['Index']))

def adfu_present():
    # Config Manager interface is live and does not invoke slow PowerShell queries.
    cfg=c.WinDLL('cfgmgr32')
    size=w.ULONG()
    cfg.CM_Get_Device_ID_List_SizeW.argtypes=[c.POINTER(w.ULONG),w.LPCWSTR,w.ULONG]
    cfg.CM_Get_Device_ID_ListW.argtypes=[w.LPCWSTR,w.LPWSTR,w.ULONG,w.ULONG]
    if cfg.CM_Get_Device_ID_List_SizeW(c.byref(size),None,0x100): return False
    buf=c.create_unicode_buffer(size.value)
    if cfg.CM_Get_Device_ID_ListW(None,buf,size,0x100): return False
    return any(x.upper().startswith(ADFU+'\\') for x in buf[:].split('\0'))

def transition(say=print,wait=20):
    if adfu_present():
        say('ADFU already present'); return True
    targets=frame_targets()
    say('verified frame targets:',[(r['DeviceID'],r['Volumes']) for r in targets])
    if not targets: raise RuntimeError('No storage disk with verified V100 USB ancestry')
    for row in targets:
        for path in row['Volumes']+[row['DeviceID']]:
            try:
                identity=scsi(path,bytes.fromhex('cc 00 00 00 00 00 00 12')+bytes(8),18)
                if not identity['ok'] or identity['status'] or bytes.fromhex(identity['data'])[2:6]!=b'USBD':
                    say('identity rejected:',path,identity); continue
                reply=scsi(path,MODE_CDB,2)
                say('mode request:',path,reply)
                if not reply['ok'] or reply['status'] or reply['data']!='ff00': continue
                say('recovery request acknowledged; ejecting the same frame LUN')
                say('eject:',scsi(path,EJECT_CDB,0,2))
                deadline=time.monotonic()+wait
                while time.monotonic()<deadline:
                    if adfu_present():
                        say('ADFU arrival VERIFIED; no MENU press or flash write'); return True
                    time.sleep(.4)
                raise RuntimeError('Acknowledged request but no ADFU arrival; not retrying/ejecting other disks')
            except OSError as ex:
                say(path,str(ex))
    return False

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--list',action='store_true',help='List verified frame disks without sending commands')
    args=ap.parse_args()
    if args.list:
        print(json.dumps(frame_targets(),indent=2)); return 0
    log=Path(__file__).with_suffix('.log')
    def say(*a):
        line=time.strftime('%Y-%m-%d %H:%M:%S ')+' '.join(map(str,a))
        print(line,flush=True)
        with log.open('a',encoding='utf-8') as f: f.write(line+'\n')
    try: return 0 if transition(say) else 3
    except Exception as ex:
        say('FAILED:',ex); return 1

if __name__=='__main__': raise SystemExit(main())
