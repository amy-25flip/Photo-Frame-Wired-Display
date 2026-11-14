# Setup (Windows 10/11)

Total time: about 15 minutes, two admin prompts. Everything is reversible with `windows\uninstall.ps1`.

## 1. Prerequisites

| need | how |
|---|---|
| WSL2 + a distribution | `wsl --install` (reboot), create the Ubuntu user. `wsl -l -v` must show VERSION 2 |
| usbipd-win ≥ 4 | `winget install --exact dorssel.usbipd-win`, then open a new PowerShell. `usbipd --version` |
| Python 3.10+ for Windows | python.org or `winget install Python.Python.3.12`; must be on PATH |
| Virtual Display Driver 25.7.23 | download the **Driver Only** asset of <https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23> and unzip it |

The VDD package is signed (SignPath Foundation). `setup.ps1` refuses to install it unless `MttVDD.dll`, `MttVDD.inf` and `mttvdd.cat` match the pinned SHA-256 values
of that release and `MttVDD.dll` and `mttvdd.cat` carry a valid Authenticode signature (an `.inf` has none of its own; Windows checks it against the signed catalog). It does not disable
driver signature enforcement and does not import certificates.

Notes from a test on a clean Windows 11 install:

* Run `wsl --install` from a normal interactive PowerShell window, not from a remote/SSH session: the Windows stub only completes there. Reboot afterwards, then `wsl --install -d Ubuntu`
  (or let the first `wsl --install` do both). Any recent Ubuntu works; the test used Ubuntu 26.04.
* During step 5 Windows shows **"Would you like to install this device software?"** for *MikeTheTech Display adapters*, publisher *SignPath Foundation*. Choose **Install**.
  The prompt appears on your desktop, so run `setup.ps1` from a terminal you are looking at (not as a hidden or scheduled job), otherwise it fails with error `0xE0000242`.
* Running `setup.ps1` a second time is safe; it skips the usbipd policy that already exists.

## 2. One-time setup (elevated PowerShell)

```powershell
git clone <this repository> ; cd v100-usb-display
powershell -ExecutionPolicy Bypass -File windows\setup.ps1 -DriverDir C:\path\to\unzipped\VDD
```

It (1) checks the prerequisites, (2) adds a usbipd *AutoBind* policy for the frame's recovery ID `10d6:10d6` (any USB port), (3) creates `/opt/v100display/venv` inside WSL
with pyusb, numpy and the ADFU loader, (4) creates a Windows venv with numpy/opencv/mss and writes `%LOCALAPPDATA%\v100display\config.json`, (5) installs the virtual display driver.
The log is `windows\setup.log`. If WSL uses a different distribution name, pass `-Distro <name>`.

## 3. Run

```powershell
& "$env:LOCALAPPDATA\v100display\venv\Scripts\python.exe" v100display\frame_watcher.py
```

Plug the frame's mini-USB into the PC **without holding MENU**. Expected log (`v100display\frame_watcher.log`):

```
normal frame detected ... → transition → loading clean RAM receiver and artwork → EARLY PICTURE ACTIVE (≈2 s) → DECODER READY → DISPLAY ACTIVE (≈10 s)
```

Windows then shows a second 1024×600 display; arrange it in Settings → System → Display. Unplugging detaches it; plugging in again restarts the session.
Stop cleanly with `python v100display\frame_watcher.py --stop`. Start at every sign-in with `windows\autostart.ps1` (`-Remove` undoes it).

## 4. Optional: your own boot picture

```powershell
python v100display\set_boot_image.py my_picture.jpg --fit contain    # --fit cover|stretch, --restore
```

Takes effect at the next plug-in.

## 5. Optional tuning (`settings.json`)

Copy `v100display\settings.example.json` to `v100display\settings.json` and edit; the values are applied at every plug-in, right after the frame's stage-1 program is up:

```json
{ "brightness": 90, "cpu_mhz": 324 }
```

| key | range | effect |
|---|---|---|
| `brightness` | 1–100 (percent of the default backlight duty) | lower = less current and heat. **If the image flickers when the frame is on a USB hub, lower this** (see below) |
| `cpu_mhz` | 240–360 (stock 360) | lower = cooler. Measured on a direct USB port with the 12-bit decoder: 360 MHz = 33.3 fps, 336 = 31.9, **324 = 31.0**, 312 = 30.0, 300 = 29.4. The mirror caps at 30 fps, so 324 is the lowest clock with headroom |

Each value is verified by readback; the clock is only changed when the PLL is at its stock value and is never raised above it. Remove a key to use the stock value.

**Power note.** The frame runs from the USB cable. A bus-powered hub, a long or thin cable, or a weak port can sag under the backlight's load and make the picture
flicker or the USB link drop (I/O errors at startup). Best: a direct motherboard port or a *powered* hub; otherwise lower `brightness` (70–90 worked on a cheap bus-powered USB 2.0 hub).
The chip has no temperature sensor that software can read; if the back gets very hot (above ~70 °C by an infrared thermometer), lower `brightness`/`cpu_mhz` or add a small stick-on heatsink to the main chip.

## Uninstall

`windows\uninstall.ps1` (add `-RemoveDriver` to remove the virtual display device and driver package). It never touches the frame.
