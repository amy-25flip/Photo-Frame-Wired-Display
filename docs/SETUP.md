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
of that release and carry a valid Authenticode signature. It does not disable driver signature enforcement and does not import certificates.

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

## Uninstall

`windows\uninstall.ps1` (add `-RemoveDriver` to remove the virtual display device and driver package). It never touches the frame.
