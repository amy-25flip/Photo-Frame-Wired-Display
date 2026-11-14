# Flash tools (optional, advanced, can brick your frame)

The display works without any of this. These tools change the frame's **SPI flash** to (a) skip the stock photo-frame splash so the frame boots straight into the USB
recovery mode, and (b) store the boot picture inside the frame. They are only meant for the exact unit described in [../docs/HARDWARE.md](../docs/HARDWARE.md).

**Read this whole page before running anything. You do this at your own risk.** A failed or interrupted flash write can leave the frame unable to boot; recovery would then need
an external SPI programmer clamped to the flash chip. Mask-ROM recovery (MENU) is *not* guaranteed to survive a damaged boot sector.

## Safety design

* Everything reads/writes through the frame's own ROM SPI routines from a RAM-resident program; nothing is flashed unless you pass an explicit apply/write command.
* **Backup first, mandatory.** `boot_probe.py --dump` reads all 8 MiB (run it twice and compare the SHA-256 values). Keep the files; never publish them (vendor firmware).
* `analyze_direct_boot.py` / `prepare_boot_patch.py` refuse to proceed unless your backup matches the **known whole-flash SHA-256** (`c71b554e…b1cf0`) and every module/boot checksum verifies.
  If your flash differs (other firmware version), the boot patch is not offered: open an issue with your hash.
* `boot_flash.py` can only touch **one 4 KiB sector (0xC000)**, requires the exact JEDEC ID `c84017`, the current sector content to equal the known original or patched version, and a chip with no
  protection bits and no pending operation. It aborts before the first erase on any bus fault. `--restore` writes the original sector back.
* `pic_flash.py` can only touch the blank region 0x72B000–0x79FFFF (the blob refuses any address outside it; tests prove the writer cannot even be built for another range), refuses to overwrite
  non-blank foreign data, verifies the readback byte for byte; `clear` erases the region again.
* All flash writers are exercised against an SPI-flash model in the MIPS emulator (`flash/tests`).

## Requirements

The frame in recovery mode with the stage-1 stub resident and the watcher **stopped** (exclusive USB access): run `python v100displayrame_watcher.py --stop`; the stub stays in the frame's RAM
as long as it stays plugged in (after a replug, start the watcher once and stop it again, or run `python v100display/load_clean_receiver.py` inside WSL). Run the tools with the WSL Python
(`/opt/v100display/venv/bin/python`). Set `V100_WIN_PYTHON` to the WSL path of a Windows Python with OpenCV if you use `pic_flash.py write` (picture conversion needs OpenCV).

## 1. Backup (required)

```bash
python3 flash/boot_probe.py --jedec                         # must print jedec c84017
python3 flash/boot_probe.py --expect-id c84017 --size 0x800000 --dump ~/flash-pass1.bin
python3 flash/boot_probe.py --expect-id c84017 --size 0x800000 --dump ~/flash-pass2.bin
sha256sum ~/flash-pass1.bin ~/flash-pass2.bin               # identical, and equal to the hash above for the verified firmware
```

## 2. Skip the stock splash (boot patch)

```bash
export V100_FLASH_BACKUP=~/flash-pass1.bin
python3 flash/analyze_direct_boot.py                         # read-only; must verify everything
python3 flash/boot_flash.py                                  # status only
python3 flash/boot_flash.py --wel-test                       # write-enable/disable round trip, no data written
python3 flash/boot_flash.py --apply                          # erases + programs sector 0xC000 (12 changed bytes), then verifies the sector
python3 flash/boot_flash.py --restore                        # puts the original sector back
```

The patch makes the stock boot code take its existing "enter ADFU" exit before the splash. After it, plugging the frame in goes directly to recovery mode (no normal-mode switch needed).

## 3. Boot picture in flash

Stores a JPEG (≤ ~470 KB) in the blank region 0x72B000–0x79FFFF; the loader reads it at boot (0.3 s) and shows it instead of the built-in artwork.

```bash
python3 flash/pic_flash.py status
python3 flash/pic_flash.py write my_picture.jpg --fit contain|cover|stretch
python3 flash/pic_flash.py clear                              # back to the blank region
```

The watcher picks it up at the next cold plug-in (`v100display/load_clean_receiver.py --win-python <windows python>` is what the watcher runs; no other configuration).

## If something goes wrong

* Interrupted `pic_flash.py write`: run `pic_flash.py clear` (or write again); the region holds only the picture.
* Interrupted `boot_flash.py --apply/--restore`: do **not** power-cycle blindly. Keep the frame connected and run `boot_flash.py --restore`; it refuses unknown sector contents on purpose, in which
  case you need your backup and a reviewed recovery (an external SPI programmer is the safe answer).
