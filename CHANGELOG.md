# Changelog

## 0.1.0 (unreleased)
- Fixes found by a clean-install test (fresh Windows 11 VM, WSL2 + Ubuntu 26.04, usbipd-win 5.3.0, Python 3.12): `setup.ps1` now runs the WSL setup from a temp script file (multi-line quoted arguments to `wsl.exe` broke under Windows PowerShell 5.1), checks Authenticode only on the files that can carry it (`.dll`, `.cat`; not the `.inf`), and no longer prints an error when the usbipd policy already exists. Setup docs describe the driver-trust prompt and the interactive `wsl --install` requirement.
- Device settings (`settings.json`): backlight brightness and CPU clock (324 MHz still holds 30 fps), power/hub troubleshooting notes.
- 30 fps lock: drift-free capture schedule and a 3-frame sender queue (no more dropped frames under host hiccups); sender reports drops and write times.
- First public version: Windows 10/11 (+ WSL2, usbipd-win) driver stack turning the Actions V100/ATJ2273F photo frame into a 1024×600 @ ~30 fps extended display.
- Two-stage on-device programs (2 KiB stage 1 + DMA/12-bit decoder blob), emulator-tested.
- Automatic normal-mode → recovery-mode switch, clean startup with a loading picture, virtual-display attach/detach on plug/unplug.
- Optional, guarded flash tools: splash-bypass boot patch and boot picture stored in flash.
