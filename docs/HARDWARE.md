# Hardware: which frame, and how to check yours

## The verified unit

| | |
|---|---|
| Product | 7" digital photo frame, board marking `P3-006 REV006` |
| SoC | Actions Semiconductor **V100 / ATJ2273F** (MIPS32 24Kc-class, ~366 MHz, 64 MB DDR2 `H5PS5162KFR-S6C`) |
| Panel | 7" RGB panel driven at **1024×600** (panel timing tables are in `v100display/stage1.py`) |
| Storage | 8 MiB SPI NOR (JEDEC `C8 40 17`, GD25Q64-class); a microSD slot (photos only) |
| USB device port | mini-USB, USB 2.0 high speed |
| USB IDs | normal mode `10d6:1101` (mass storage, INQUIRY `actions` / `media-player`), recovery (ADFU) `10d6:10d6` |
| Boot ROM | ADFU `GetInfo` identity: company `C`, id `ADFUD`, PID `0x0950`, ROM version `0x46` |
| Recovery entry | hold **MENU** while plugging in the mini-USB (manual), or the vendor SCSI command `CB 21 …` from normal mode (automatic, used by this project) |

## Will it work on my frame?

It can only work if all of these are true; the first two are cheap to check:

1. **USB IDs**: with the frame plugged in normally, Windows shows a USB device with hardware ID `VID_10D6&PID_1101` (Device Manager → Details → Hardware Ids).
   Holding MENU while plugging it in should give `VID_10D6&PID_10D6`.
2. **Boot ROM identity**: `adfu-tool info` (from `actions-adfu-tool`) prints `ADFUD`, PID `0x0950`, version `0x46`.
3. **Panel**: the stage-1 program contains the LCD controller timing for *this* panel (1024×600). A frame with a different panel (800×480 is common for
   this SoC) will show garbage or nothing until the timing tables in `stage1.py` are adapted. The stock firmware's `lcd` module contains the right values
   for a panel; see [RESEARCH_NOTES.md](RESEARCH_NOTES.md#panel-timing).
4. **Same memory map**: DDR is initialised by the boot ROM/stock loader before our code runs; other DRAM sizes should be fine as long as the first ~16 MB exist.

Failure in 3 or 4 is harmless (the frame just shows nothing useful); a power cycle restores it. The default mode never writes flash.

## Reporting a different frame

Open an issue with: the frame's brand/model, the board marking, USB hardware IDs in normal and MENU-held mode, the `adfu-tool info` output,
the panel size, and what the screen did. Please do **not** attach firmware or flash dumps (copyrighted vendor code); hashes are fine.

## What this project does *not* support

- Other SoCs (the ATJ2273F register map and boot ROM entry points are specific; sibling chips such as ATJ2279 differ).
- Driverless operation: the PC needs the software in this repository (the frame is not a standard USB display).
- Audio, touch, the frame's buttons or its remote.
