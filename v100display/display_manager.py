# SPDX-License-Identifier: GPL-2.0-or-later
"""Attach/detach only the VDD desktop; never change the primary monitor."""
import ctypes as c
from ctypes import wintypes as w
import json
import sys
import time

class POINT(c.Structure): _fields_=[('x',w.LONG),('y',w.LONG)]
class DUMMY(c.Structure):
    _fields_=[('dmPosition',POINT),('dmDisplayOrientation',w.DWORD),('dmDisplayFixedOutput',w.DWORD)]
class DEVMODE(c.Structure):
    _fields_=[('dmDeviceName',w.WCHAR*32),('dmSpecVersion',w.WORD),('dmDriverVersion',w.WORD),
        ('dmSize',w.WORD),('dmDriverExtra',w.WORD),('dmFields',w.DWORD),('display',DUMMY),
        ('dmColor',w.SHORT),('dmDuplex',w.SHORT),('dmYResolution',w.SHORT),('dmTTOption',w.SHORT),
        ('dmCollate',w.SHORT),('dmFormName',w.WCHAR*32),('dmLogPixels',w.WORD),
        ('dmBitsPerPel',w.DWORD),('dmPelsWidth',w.DWORD),('dmPelsHeight',w.DWORD),
        ('dmDisplayFlags',w.DWORD),('dmDisplayFrequency',w.DWORD),('dmICMMethod',w.DWORD),
        ('dmICMIntent',w.DWORD),('dmMediaType',w.DWORD),('dmDitherType',w.DWORD),
        ('dmReserved1',w.DWORD),('dmReserved2',w.DWORD),('dmPanningWidth',w.DWORD),('dmPanningHeight',w.DWORD)]
class DISPLAY_DEVICE(c.Structure):
    _fields_=[('cb',w.DWORD),('DeviceName',w.WCHAR*32),('DeviceString',w.WCHAR*128),
        ('StateFlags',w.DWORD),('DeviceID',w.WCHAR*128),('DeviceKey',w.WCHAR*128)]

def api():
    u=c.WinDLL('user32',use_last_error=True)
    u.EnumDisplayDevicesW.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(DISPLAY_DEVICE),w.DWORD]
    u.EnumDisplaySettingsExW.argtypes=[w.LPCWSTR,w.DWORD,c.POINTER(DEVMODE),w.DWORD]
    u.ChangeDisplaySettingsExW.argtypes=[w.LPCWSTR,c.POINTER(DEVMODE),w.HWND,w.DWORD,c.c_void_p]
    return u

def mode(name,index=0xffffffff):
    d=DEVMODE(); d.dmSize=c.sizeof(d)
    if api().EnumDisplaySettingsExW(name,index,c.byref(d),0): return d
    return None

def displays():
    result=[];i=0
    while True:
        dev=DISPLAY_DEVICE();dev.cb=c.sizeof(dev)
        if not api().EnumDisplayDevicesW(None,i,c.byref(dev),0): break
        d=mode(dev.DeviceName)
        result.append(dict(name=dev.DeviceName,description=dev.DeviceString,id=dev.DeviceID,
            attached=bool(dev.StateFlags&1),primary=bool(dev.StateFlags&4),
            left=d.display.dmPosition.x if d else 0,top=d.display.dmPosition.y if d else 0,
            width=d.dmPelsWidth if d else 0,height=d.dmPelsHeight if d else 0))
        i+=1
    return result

def virtual():
    candidates=[d for d in displays() if 'MTTVDD' in d['id'].upper() or d['description']=='Virtual Display Driver']
    if len(candidates)!=1: raise RuntimeError('Expected exactly one VDD adapter, found '+str(len(candidates)))
    if candidates[0]['primary']: raise RuntimeError('VDD is primary; refusing to alter it')
    return candidates[0]

def apply_mode(name,d):
    # Indirect displays need the saved topology staged before Windows applies it.
    # A direct dynamic change may work once, then fail after a detach.
    status=api().ChangeDisplaySettingsExW(name,c.byref(d),None,0x10000001,None)
    if not status:status=api().ChangeDisplaySettingsExW(None,None,None,0,None)
    return status

def attach():
    dev=virtual()
    if dev['attached'] and dev['width']==1024 and dev['height']==600: return dev
    d=mode(dev['name'],0) or mode(dev['name'],0xfffffffe)
    if d is None: raise RuntimeError('VDD exposes no display mode')
    right=max((x['left']+x['width'] for x in displays() if x['attached'] and x['name']!=dev['name']),default=1920)
    d.display.dmPosition.x,d.display.dmPosition.y=right,0
    d.dmPelsWidth,d.dmPelsHeight,d.dmBitsPerPel,d.dmDisplayFrequency=1024,600,32,30
    d.dmFields|=0x20|0x40000|0x80000|0x100000|0x400000
    # Attaching a detached indirect display needs its saved topology updated.
    # Dynamic-only flags (0) return DISP_CHANGE_FAILED on this driver.
    status=apply_mode(dev['name'],d)
    if status: raise RuntimeError('Attach display failed: '+str(status))
    time.sleep(.8)
    dev=virtual()
    if not dev['attached'] or (dev['width'],dev['height'])!=(1024,600):
        raise RuntimeError('Windows did not attach a 1024x600 desktop')
    return dev

def detach():
    dev=virtual()
    if not dev['attached']: return dev
    d=mode(dev['name']);d.dmFields=0x20|0x80000|0x100000
    d.dmPelsWidth=d.dmPelsHeight=0
    status=apply_mode(dev['name'],d)
    if status: raise RuntimeError('Detach display failed: '+str(status))
    return dev

if __name__=='__main__':
    action=sys.argv[1] if len(sys.argv)>1 else 'list'
    print(json.dumps(attach() if action=='attach' else detach() if action=='detach' else displays(),indent=2))
