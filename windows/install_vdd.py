# SPDX-License-Identifier: GPL-2.0-or-later
"""Install the signed root-enumerated UMDF display driver; run elevated once.

Uses Windows SetupAPI/NewDev directly; does not download/run DevCon, import
certificates, disable signature checks, or change the primary display.
"""
import ctypes as c
from ctypes import wintypes as w
import json
from pathlib import Path
import subprocess
import sys
import uuid
import winreg

class GUID(c.Structure):
    _fields_=[('Data1',w.DWORD),('Data2',w.WORD),('Data3',w.WORD),('Data4',w.BYTE*8)]
class DEVINFO(c.Structure):
    _fields_=[('cbSize',w.DWORD),('ClassGuid',GUID),('DevInst',w.DWORD),('Reserved',c.c_size_t)]

def install(folder):
    if not c.windll.shell32.IsUserAnAdmin(): raise RuntimeError('Administrator elevation is required')
    folder=Path(folder).resolve()
    inf=folder/'MttVDD.inf'
    if not inf.is_file() or not (folder/'mttvdd.cat').is_file(): raise RuntimeError('Driver package is incomplete')
    # The settings file (vdd_settings.xml) is read from the folder given on the command line. The package itself is verified by setup.ps1 first.
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\MikeTheTech\VirtualDisplayDriver',0,winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key,'VDDPATH',0,winreg.REG_SZ,str(folder))
    existing=subprocess.run(['pnputil','/enum-devices','/deviceid',r'Root\MttVDD'],capture_output=True,text=True).stdout
    if 'ROOT\\DISPLAY' in existing.upper(): raise RuntimeError('A VDD root device already exists; inspect it rather than creating a duplicate')
    api=c.WinDLL('setupapi',use_last_error=True)
    api.SetupDiCreateDeviceInfoList.argtypes=[c.POINTER(GUID),w.HWND]
    api.SetupDiCreateDeviceInfoList.restype=w.HANDLE
    api.SetupDiCreateDeviceInfoW.argtypes=[w.HANDLE,w.LPCWSTR,c.POINTER(GUID),w.LPCWSTR,w.HWND,w.DWORD,c.POINTER(DEVINFO)]
    api.SetupDiSetDeviceRegistryPropertyW.argtypes=[w.HANDLE,c.POINTER(DEVINFO),w.DWORD,c.c_void_p,w.DWORD]
    api.SetupDiCallClassInstaller.argtypes=[w.DWORD,w.HANDLE,c.POINTER(DEVINFO)]
    api.SetupDiDestroyDeviceInfoList.argtypes=[w.HANDLE]
    guid=GUID.from_buffer_copy(uuid.UUID('4d36e968-e325-11ce-bfc1-08002be10318').bytes_le)
    handle=api.SetupDiCreateDeviceInfoList(c.byref(guid),None)
    if handle==c.c_void_p(-1).value: raise c.WinError(c.get_last_error())
    info=DEVINFO();info.cbSize=c.sizeof(info)
    registered=False
    try:
        if not api.SetupDiCreateDeviceInfoW(handle,'Display',c.byref(guid),'V100 USB Frame Display',None,1,c.byref(info)):
            raise c.WinError(c.get_last_error())
        hwid=c.create_unicode_buffer('Root\\MttVDD\0\0')
        if not api.SetupDiSetDeviceRegistryPropertyW(handle,c.byref(info),1,hwid,c.sizeof(hwid)):
            raise c.WinError(c.get_last_error())
        if not api.SetupDiCallClassInstaller(0x19,handle,c.byref(info)):
            raise c.WinError(c.get_last_error())
        registered=True
        new=c.WinDLL('newdev',use_last_error=True)
        new.UpdateDriverForPlugAndPlayDevicesW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.POINTER(w.BOOL)]
        reboot=w.BOOL()
        if not new.UpdateDriverForPlugAndPlayDevicesW(None,'Root\\MttVDD',str(inf),1,c.byref(reboot)):
            raise c.WinError(c.get_last_error())
        print(json.dumps(dict(installed=True,reboot_required=bool(reboot.value),settings=str(folder))),flush=True)
    except Exception:
        if registered: api.SetupDiCallClassInstaller(5,handle,c.byref(info))
        raise
    finally: api.SetupDiDestroyDeviceInfoList(handle)

if __name__=='__main__': install(sys.argv[1])
