# SPDX-License-Identifier: GPL-2.0-or-later
<#
.SYNOPSIS
  One-time setup for v100-usb-display on Windows 10/11. Run from an ELEVATED PowerShell.

.DESCRIPTION
  1. checks the prerequisites (WSL2 + a distribution, usbipd-win)
  2. lets usbipd attach the frame's ADFU USB ID (10d6:10d6) to WSL automatically (an AutoBind policy, removable with uninstall.ps1)
  3. creates the Python environment inside WSL (pyusb, numpy, the ADFU loader) at /opt/v100display/venv
  4. creates the Windows Python environment (numpy, opencv, mss) and writes the config file
  5. verifies and installs the signed Virtual Display Driver (MIT, VirtualDrivers/Virtual-Display-Driver 25.7.23) that makes the frame a real Windows monitor
  Nothing is downloaded silently: you supply the driver files (-DriverDir), pip downloads packages into the two virtual environments.

.PARAMETER DriverDir
  Folder with MttVDD.dll, MttVDD.inf and mttvdd.cat from the official 25.7.23 "Driver Only" release asset
  https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23   (their SHA-256 values are pinned below)
.PARAMETER Distro
  WSL distribution to use (default: Ubuntu)
.PARAMETER SkipDriver
  Skip step 5 (e.g. you already installed the virtual display driver)

  powershell -ExecutionPolicy Bypass -File windows\setup.ps1 -DriverDir C:\Downloads\VDD
#>
param(
    [string]$DriverDir,
    [string]$Distro = "Ubuntu",
    [switch]$SkipDriver
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $PSScriptRoot "setup.log"
Start-Transcript -Path $log -Force | Out-Null
try {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { throw "Run this script from an elevated (Administrator) PowerShell." }

    Write-Host "== 1/5 prerequisites"
    if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) { throw "usbipd-win is not installed. Install it with: winget install --exact dorssel.usbipd-win   (then open a new PowerShell)" }
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw "WSL is not installed. Install it with: wsl --install   (reboot, create a distribution, then run this again)" }
    $distros = (wsl.exe -l -q) -replace "`0", "" | Where-Object { $_.Trim() }
    if ($distros -notcontains $Distro) { throw "WSL distribution '$Distro' not found. Installed: $($distros -join ', '). Use -Distro <name>." }
    $wslVer = wsl.exe -l -v | Out-String
    Write-Host $wslVer

    Write-Host "== 2/5 usbipd policy for the frame (ADFU 10d6:10d6)"
    usbipd policy add --effect Allow --operation AutoBind --hardware-id 10d6:10d6
    if ($LASTEXITCODE -ne 0) { Write-Host "(policy may already exist)" }
    usbipd policy list

    Write-Host "== 3/5 Python environment inside WSL ($Distro)"
    $drive = $repo.Substring(0, 1).ToLower()
    $wslRepo = "/mnt/$drive" + ($repo.Substring(2) -replace "\\", "/")
    $script = @"
set -e
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git libusb-1.0-0 usbutils >/dev/null
python3 -m venv /opt/v100display/venv
/opt/v100display/venv/bin/pip install --quiet --upgrade pip
/opt/v100display/venv/bin/pip install --quiet -r '$wslRepo/requirements-wsl.txt'
/opt/v100display/venv/bin/pip install --quiet git+https://github.com/BlackLikeaCat/actions-adfu-tool
/opt/v100display/venv/bin/python -c 'import usb.core, numpy, adfu_tool; print("WSL environment OK")'
"@
    $script = $script -replace "`r", ""
    wsl.exe -d $Distro -u root -e bash -lc $script
    if ($LASTEXITCODE -ne 0) { throw "WSL environment setup failed (see above)." }

    Write-Host "== 4/5 Windows Python environment"
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "Python 3.10+ for Windows not found (python.org or winget install Python.Python.3.12)." }
    $venv = Join-Path $env:LOCALAPPDATA "v100display\venv"
    & python -m venv $venv
    & "$venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    & "$venv\Scripts\python.exe" -m pip install --quiet -r (Join-Path $repo "requirements-windows.txt")
    $cfgDir = Join-Path $env:LOCALAPPDATA "v100display"
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    @{ wsl_distro = $Distro; wsl_python = "/opt/v100display/venv/bin/python"; windows_python = "$venv\Scripts\python.exe" } |
        ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $cfgDir "config.json")
    Write-Host "config written to $cfgDir\config.json"

    if (-not $SkipDriver) {
        Write-Host "== 5/5 Virtual Display Driver"
        if (-not $DriverDir) { throw "Pass -DriverDir <folder with MttVDD.dll/.inf/.cat from the VDD 25.7.23 Driver-Only asset> (or -SkipDriver)." }
        $pins = @{
            "MttVDD.dll" = "c9ca837f57a98fbd43bc416a7f535a95843626e7759eaf85cf0cd7ce334dbb05"
            "MttVDD.inf" = "550d211fe481e74dfe3f9d724ed78be48b3a9113405965d683d9373e8d672f5d"
            "mttvdd.cat" = "08a0093fc9b2e32b287a6f8a77ca4de0a31830d29fc33d2b13a918dc859468f6"
        }
        foreach ($name in $pins.Keys) {
            $f = Join-Path $DriverDir $name
            if (-not (Test-Path $f)) { throw "$name missing in $DriverDir" }
            $h = (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower()
            if ($h -ne $pins[$name]) { throw "$name does not match the pinned SHA-256 of release 25.7.23 ($h). Refusing to install." }
            $sig = Get-AuthenticodeSignature $f
            if ($sig.Status -ne "Valid") { throw "$name has no valid Authenticode signature ($($sig.Status))." }
        }
        Copy-Item (Join-Path $PSScriptRoot "vdd_settings.xml") (Join-Path $DriverDir "vdd_settings.xml") -Force
        & "$venv\Scripts\python.exe" -u (Join-Path $PSScriptRoot "install_vdd.py") (Resolve-Path $DriverDir).Path
        if ($LASTEXITCODE -ne 0) { throw "Virtual display driver installation failed." }
    }
    Write-Host ""
    Write-Host "Setup finished. Next:  windows\autostart.ps1   (optional: start at sign-in)   then plug the frame in without holding any button."
    Write-Host "Start manually:  $venv\Scripts\python.exe $repo\v100display\frame_watcher.py"
}
catch {
    Write-Host "SETUP FAILED: $_" -ForegroundColor Red
    exit 1
}
finally { Stop-Transcript | Out-Null }
