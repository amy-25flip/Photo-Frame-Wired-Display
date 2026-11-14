# Troubleshooting

Always start with `v100display\frame_watcher.log` (session), `sender.log` / `sender.err.log` (USB + decoder), `mirror.log` (capture).

| symptom | cause / fix |
|---|---|
| Watcher says *normal frame detected* but never goes ADFU | the vendor mode switch was refused. Check `win_enter_adfu.log`. Try holding MENU while plugging in (direct ADFU). Make sure no other program (photo software, Explorer previews) holds the frame's drive. Without a microSD card some units answer the switch command differently: try again with a card inserted |
| `usbipd attach` fails, "not shared" / "access denied" | run `windows\setup.ps1` once (it adds the AutoBind policy for `10d6:10d6`); `usbipd policy list` must show it |
| Frame not visible in WSL (`lsusb` has no `10d6:10d6`) | WSL was shut down and restarted: the watcher keeps it alive with a `sleep infinity` process; do not `wsl --shutdown` while the frame is in use. Replug the frame |
| Black or garbage image, no loading picture | the panel timing in `stage1.py` does not match your panel (see [HARDWARE.md](HARDWARE.md)), or the frame is a different model |
| Loading picture shows, desktop never appears | the decoder stage failed; `sender.err.log` says where. Replug (the stub in RAM is never reloaded over a running stub on purpose) |
| "Frame did not appear in WSL" right after plugging in | USB enumeration was slow; the watcher stops that attempt. Unplug, wait 5 s, plug in again |
| Image tears or stutters | the capture side or the USB link is saturated; close heavy USB traffic on the same controller. Static screens send nothing; full-motion video needs ~28 MB/s |
| Colour banding | the format is 12 bit (4096 colours) with ordered dither. `mirror.py --nodither` trades dither noise for banding |
| "Multiple V100 frames connected" | the watcher refuses ambiguous USB ownership: connect one frame |
| Windows shows a drive for the frame for a moment | normal: that is the frame in mass-storage mode before the switch |

## Rules of thumb (learned the hard way)

* **Never hot-reload** a stage over a running stub, and never `wsl --shutdown`/USB-reset while the stub runs: it wedges. Unplug, wait 5 s, replug fixes everything; nothing persistent is changed.
* The first packet after a fresh stage-1 load can be lost; the software sends a junk packet first. If you write your own tools: complete a command/ack round trip before queueing code.
* Do not read the USB IN endpoint with very short timeouts to "flush" it; under usbipd that can swallow the next acknowledgement.
* Do not read a register range you do not know on a live stub: some reads hang the bus (e.g. USB controller registers 0x1A8/0x400/0x414/0x1B4 were suspected before the real cause, a lost first ack, was found).

If everything fails: unplug, replug holding MENU, run `windows\uninstall.ps1`, and open an issue with the logs.
