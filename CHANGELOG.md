# Changelog

## 0.1.0 (unreleased)
- Device settings (`settings.json`): backlight brightness and CPU clock (324 MHz still holds 30 fps), power/hub troubleshooting notes.
- 30 fps lock: drift-free capture schedule and a 3-frame sender queue (no more dropped frames under host hiccups); sender reports drops and write times.
- First public version: Windows 10/11 (+ WSL2, usbipd-win) driver stack turning the Actions V100/ATJ2273F photo frame into a 1024×600 @ ~30 fps extended display.
- Two-stage on-device programs (2 KiB stage 1 + DMA/12-bit decoder blob), emulator-tested.
- Automatic normal-mode → recovery-mode switch, clean startup with a loading picture, virtual-display attach/detach on plug/unplug.
- Optional, guarded flash tools: splash-bypass boot patch and boot picture stored in flash.
