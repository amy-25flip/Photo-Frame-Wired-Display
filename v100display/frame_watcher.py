#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""V100 USB frame: normal plug -> verified decoder -> independent Windows desktop.

The boot patch enters recovery before the stock splash. A clean RAM receiver
and loading picture precede the desktop. Requires signed VDD and usbipd setup.
"""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

HERE=Path(__file__).resolve().parent
import config
CFG=config.load()
PY=config.windows_python(CFG)
WPY=CFG['wsl_python']
DISTRO=CFG['wsl_distro']
NOWIN=getattr(subprocess,'CREATE_NO_WINDOW',0)
LOG=None

def log(*parts):
    line=time.strftime('%Y-%m-%d %H:%M:%S ')+' '.join(map(str,parts))
    print(line,flush=True)
    if LOG:
        with LOG.open('a',encoding='utf-8') as f:f.write(line+'\n')

def run(args,timeout=30):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout,creationflags=NOWIN)
    return p

def linux_path(path):
    path=Path(path).resolve()
    return '/mnt/'+path.drive[0].lower()+'/'+str(path)[3:].replace('\\','/')

def usb_devices():
    # JSON avoids version-dependent table formatting and returns the live bus ID.
    p=run(['usbipd','state'])
    if p.returncode: raise RuntimeError('usbipd state: '+p.stderr.strip())
    result=[]
    for d in json.loads(p.stdout).get('Devices',[]):
        hw=(d.get('InstanceId') or '').upper()
        if 'VID_10D6&PID_1101' in hw or 'VID_10D6&PID_10D6' in hw:
            if d.get('BusId'):
                result.append(dict(busid=d['BusId'],mode='normal' if 'PID_1101' in hw else 'adfu',
                    attached=bool(d.get('ClientIPAddress')),shared=bool(d.get('PersistedGuid'))))
    return result

def normal_to_adfu():
    # Prefer the current user's process. The existing elevated task is a fallback
    # only for storage drivers that refuse pass-through to a non-elevated caller.
    p=run([PY,'-u',str(HERE/'win_enter_adfu.py')],timeout=40)
    log('transition:',p.stdout.strip()[-1200:],p.stderr.strip()[-200:])
    if p.returncode==0:return
    if 'Errno 5' not in p.stdout and 'error\': 5' not in p.stdout:
        raise RuntimeError('Frame transition failed; see win_enter_adfu.log')
    p=run(['schtasks','/run','/tn','V100EnterADFU'])
    if p.returncode:raise RuntimeError('Storage access requires the one-time V100EnterADFU task')
    end=time.monotonic()+30
    while time.monotonic()<end:
        if any(d['mode']=='adfu' for d in usb_devices()):return
        time.sleep(.5)
    raise RuntimeError('Elevated transition did not produce an ADFU device')

class Session:
    def __init__(self,args):
        self.args=args;self.sender=None;self.mirror=None;self.active=False
        self.display=None;self.logs=[];self.last_health=0

    def start(self,dev):
        started=time.monotonic()
        import display_manager
        display_manager.virtual()  # fail before touching hardware if VDD is absent/ambiguous
        if not dev['attached']:
            p=run(['usbipd','attach','--wsl','--busid',dev['busid']])
            if p.returncode:raise RuntimeError(p.stderr.strip()+'; run setup_once.ps1 once if sharing is denied')
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            p=run(['wsl.exe','-d',DISTRO,'-u','root','-e','lsusb'])
            if '10d6:10d6' in p.stdout:break
            time.sleep(.5)
        else:raise RuntimeError('Frame did not appear in WSL')
        if dev['attached']:
            log('already attached: resuming the resident RAM loader')
        else:
            log('loading clean RAM receiver and artwork on',dev['busid'])
            p=run(['wsl.exe','-d',DISTRO,'-u','root','-e',WPY,'-u',linux_path(HERE/'load_clean_receiver.py'),'--win-python',linux_path(PY)],timeout=35)
            log('ROM upload:',p.stdout.strip())
            if p.returncode or 'stub loaded and running' not in p.stdout:
                raise RuntimeError('RAM loader failed: '+(p.stdout+p.stderr)[-1500:])
            log('EARLY PICTURE ACTIVE:',round(time.monotonic()-started,2),'seconds after session detection')
        sender_log=HERE/'sender.log'
        out=sender_log.open('w',encoding='utf-8');self.logs.append(out)
        sender_error=HERE/'sender.err.log'
        err=sender_error.open('w',encoding='utf-8');self.logs.append(err)
        sender_args=['wsl.exe','-d',DISTRO,'-u','root','-e',WPY,'-u',linux_path(HERE/'frame_sender.py'),'--c444']
        if not dev['attached']:sender_args.append('--fresh-loader')
        self.sender=subprocess.Popen(sender_args,
            stdout=out,stderr=err,creationflags=NOWIN)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if 'DISPLAY_READY:' in sender_log.read_text(encoding='utf-8',errors='replace'):break
            if self.sender.poll() is not None:raise RuntimeError('Sender failed: '+sender_log.read_text(encoding='utf-8',errors='replace')[-800:]+sender_error.read_text(encoding='utf-8',errors='replace')[-1600:])
            time.sleep(.3)
        else:raise RuntimeError('Decoder startup was not verified within 30 seconds')
        log('DECODER READY:',round(time.monotonic()-started,2),'seconds after session detection')
        self.display=display_manager.attach()
        self.start_mirror()
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if 'FIRST_DESKTOP_FRAME:' in sender_log.read_text(encoding='utf-8',errors='replace'):break
            if self.sender.poll() is not None or self.mirror.poll() is not None:raise RuntimeError('Desktop capture or sender failed')
            time.sleep(.1)
        else:raise RuntimeError('First desktop frame was not acknowledged')
        self.active=True
        log('DISPLAY ACTIVE:',self.display['name'],'1024x600, extended desktop;',round(time.monotonic()-started,2),'seconds after detection')

    def start_mirror(self):
        out=(HERE/'mirror.log').open('w',encoding='utf-8');self.logs.append(out)
        self.mirror=subprocess.Popen([PY,'-W','ignore','-u',str(HERE/'mirror.py'),'--c444',
            '--display-device',self.display['name'],'--fps','30','--cursor'],
            stdout=out,stderr=subprocess.STDOUT,creationflags=NOWIN,cwd=HERE)

    def health(self):
        if self.sender and self.sender.poll() is not None:raise RuntimeError('Sender exited; reconnect frame to restart safely')
        if self.mirror and self.mirror.poll() is not None:raise RuntimeError('Capture exited; reconnect frame to restart safely')
        if time.monotonic()-self.last_health>2:
            self.last_health=time.monotonic()
            import display_manager
            now=display_manager.virtual()
            if not now['attached']:raise RuntimeError('Virtual desktop was disconnected in Windows')
            if (now['left'],now['top'],now['width'],now['height'])!=(self.display['left'],self.display['top'],self.display['width'],self.display['height']):
                self.display=now
                if self.mirror:self.mirror.terminate();self.mirror.wait(timeout=5)
                self.start_mirror();log('capture followed desktop layout change')

    def stop(self):
        if self.mirror and self.mirror.poll() is None:
            self.mirror.terminate()
            try:self.mirror.wait(timeout=5)
            except subprocess.TimeoutExpired:self.mirror.kill()
        if self.sender:
            try:
                # Exact project path, not every Python or sender process in WSL.
                pattern=linux_path(HERE/'frame_sender.py').replace('/mnt/','[/]mnt/',1)
                run(['wsl.exe','-d',DISTRO,'-u','root','-e','pkill','-TERM','-f',pattern],timeout=5)
                self.sender.wait(timeout=18)
            except subprocess.TimeoutExpired:self.sender.kill()
        if self.display:
            try:
                import display_manager
                display_manager.detach();log('virtual desktop detached')
            except Exception as ex:log('could not detach virtual desktop:',ex)
        for f in self.logs:f.close()
        self.logs=[];self.sender=self.mirror=None;self.display=None;self.active=False

def main():
    global LOG
    ap=argparse.ArgumentParser()
    ap.add_argument('--log',default=str(HERE/'frame_watcher.log'))
    ap.add_argument('--stop',action='store_true',help='Gracefully stop the current watcher and detach its desktop')
    args=ap.parse_args();LOG=Path(args.log)
    # One watcher per interactive desktop. Windows releases the mutex on a crash.
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    k.OpenEventW.argtypes=[ctypes.c_uint32,ctypes.c_bool,ctypes.c_wchar_p];k.OpenEventW.restype=ctypes.c_void_p
    k.SetEvent.argtypes=[ctypes.c_void_p]
    event_name='Local\\V100FrameWatcherStop'
    if args.stop:
        event=k.OpenEventW(2,False,event_name)
        if event:k.SetEvent(event);k.CloseHandle(event)
        return
    k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p];k.CreateMutexW.restype=ctypes.c_void_p
    mutex=k.CreateMutexW(None,False,'Local\\V100FrameWatcher')
    if ctypes.get_last_error()==183:return
    if not mutex:raise RuntimeError('Cannot create watcher mutex')
    k.CreateEventW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_bool,ctypes.c_wchar_p];k.CreateEventW.restype=ctypes.c_void_p
    k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    stop_event=k.CreateEventW(None,True,False,event_name)
    if not stop_event:raise RuntimeError('Cannot create stop event')
    log('watcher started; normal plug-in, independent desktop, no MENU required')
    keep=subprocess.Popen(['wsl.exe','-d',DISTRO,'-u','root','-e','sleep','infinity'],creationflags=NOWIN)
    session=Session(args);blocked=None;blocked_mode=None;seen=None
    try:
        while k.WaitForSingleObject(stop_event,0)!=0:
            devices=usb_devices()
            if len(devices)>1:raise RuntimeError('Multiple V100 frames connected; refusing ambiguous USB ownership')
            dev=devices[0] if devices else None
            if dev is None:
                if session.sender:session.stop();log('frame unplugged; waiting')
                blocked=None;blocked_mode=None;seen=None
            elif dev['busid']!=blocked or dev['mode']!=blocked_mode:
                try:
                    if dev['mode']=='normal':
                        if session.sender:session.stop()
                        log('normal frame detected on',dev['busid'])
                        normal_to_adfu()
                    elif not session.active:session.start(dev)
                    else:session.health()
                except Exception as ex:
                    log('STOPPED:',ex,'Reconnect normally to retry.')
                    session.stop();blocked=dev['busid'];blocked_mode=dev['mode']
            time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        session.stop();keep.terminate()
        k.CloseHandle(stop_event);k.CloseHandle(mutex)
        log('watcher stopped')

if __name__=='__main__':
    try:main()
    except Exception:
        if LOG:
            with LOG.open('a',encoding='utf-8') as f:f.write(traceback.format_exc())
        raise
