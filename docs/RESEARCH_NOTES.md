# Reverse-engineering notes

What was learned about the ATJ2273F while building this, including the dead ends, so nobody has to repeat them. All facts come from an owned unit and static analysis of
its own boot ROM and flash; no vendor binaries are included in this repository (and please do not add any).

## Boot ROM entry points (base 0xBFC00000, kseg1, usable from our code)

| address | function |
|---|---|
| 0xBFC06C2C / 0xBFC06DD8 | SPI controller init / exit (SPI controller at 0xB0258000) |
| 0xBFC070AC | send one byte on SPI (bounded wait for TX completion; returns 0 on success) |
| 0xBFC06E8C | `spi_read(offset, length, dst)` (0x03 READ, 64-byte blocks) — used to read the whole 8 MiB flash read-only |
| 0xBFC0185C / 0xBFC01978 | SD-controller "prepare" (clock/reset/pin-mux, saves old values in SRAM 0xB406068C…) / restore |
| 0xBFC01A00 | `sd_init()` — CMD0/8/55/ACMD41/2/3/9/7… returns 1 on success, card state in SRAM 0xB4060680 (bit7 = SDHC), RCA at 0xB4060684 |
| 0xBFC01DA0 | `sd_read(lba, _, count, dst_phys)` — CMD18 + DMA channel 0 into DRAM |

SRAM 0xB4060000–0xB4061000 belongs to the ROM; our stage 1 runs at 0xB4061000 (2 KiB).

## Peripheral facts

* **Display**: `DE` 0xB02F0000, `LCD` 0xB02A0000, CMU 0xB0010000, GPIO/MFP 0xB01C0000. Normal plane: `DE_PLANE0_CFG`=0x40000, `STRD`=512 (words) for 1024-px RGB565 lines; hardware 2× zoom with `CFG`=0xC0000, `STRD`=256.
* **USB device controller** 0xB0290000: OUT1 byte count 0x08/09, OUT1CON 0x0A, OUT1CS 0x0B (write 1 to arm, bit 1 set while busy), FIFO read port 0x84 (one pop per 32-bit load),
  IN2 length/CS 0x14/0x15/0x17, IN FIFO write port 0x88. `OUT1CON` 0x89 = double buffered.
* **System DMA** 0xB0220000: channel *n* registers at 0x100 + 0x30·*n* (MODE, SRC, DST, CNT, REM, CMD at +0x14). Registers persist after a transfer. The working mode for FIFO→RAM is
  `0x00120052` (source DRQ field 0x12 = SDRAM, fixed source address). The USB request line (DRQ 23) never fired in any configuration we tried.
* **CPU**: MIPS32, cache lines 32 B, 16 KiB 4-way I- and D-caches; `Count` reads 0. Kseg0 code runs at ~366 MIPS after an `Index_Store_Tag_I` sweep; uncached code runs at ~17 MIPS.

## Dead ends (negative results)

* **DE overlay / YUV (NV12) plane**: all registers (`OVL_SIZE/POS`, `BA0/BA1UV`, `STRD`, `CFG`, `ISIZE/OSIZE/SR`, scaler coefficients, `OVLP_CFG`, `LCD_CTL` bit 3, `DE+0x120`, `DE_ENABLE` variants) accept writes and read back,
  but nothing ever renders (solid-colour test, ~30 combinations); plane 1 as a second layer likewise. The register-map author reports the same ("TODO make it work").
* **microSD slot from our stub**: the ROM driver (above) runs, the controller gets clock/reset, but sd_init always fails and the controller state is identical with the card inserted or removed;
  all 40 GPIO registers are identical card in/out. The pin-function (MFP) fields for the SD pins are never set in this state; ~120 combinations of `MFP_CTL0` bits 18–30 did not make the card answer.
  Unsolved: needs the stock firmware's pin/power sequence. (A working FAT16/32 reader + ROM-driver blob existed for this; see the git history of the research repository if you want to continue.)
* **USB-DMA with the USB DRQ** (never fires), **arming the next OUT packet during a DMA** (corrupts data), **DMA reading past one 512-byte packet** (hangs the USB controller; re-reading the same packet is fine),
  **DMA channel 4** (hung the USB block while channel 3 works), **reading USB registers 0x1A8/0x400/0x414/0x1B4** (was blamed for hangs; the real cause was a lost first acknowledgement).
* **Faster than ~30 MB/s**: the FIFO read port is the ceiling (CPU ~36 MB/s best case, DMA ~30 MB/s); the only lever is fewer bytes per frame (hence the 12-bit format).

## Panel timing

`stage1.py` programs the LCD controller for a 1024×600 panel (`LCD+0x04` = 0x025703FF size, timing registers 0x0C/0x10/0x14, CMU LCD clock/PLL). The stock firmware's LCD module contains these tables;
for another panel read them there (or from the panel datasheet) and adapt `TBL_LCD`/`TBL_DE`/the constants `W`,`H` in `stage1.py` and the 1024×600 assumptions in `c444.py`/`mirror.py`.

## Flash layout (verified unit, 8 MiB)

First record at 0x000 (magic words at 0x1F4/0x1F8 `ActB` / 0x55AA6D72, word sum + 0x1234 check at 0x1FC), second-stage checksum at 0x23FE, a module directory at 0x2400 (32-byte entries: name, start/512, length, additive checksum), modules between 0x9400 and ~0x3E0000 (the stock firmware),
unused (0xFF) space at 0x72B000–0x79FFFF and 0x7A1000–0x7FFFFF. The boot-patch tool changes 12 bytes inside module `brecf03` (0xC404/0xC414) and keeps every checksum valid.
