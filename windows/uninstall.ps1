# SPDX-License-Identifier: GPL-2.0-or-later
<#
.SYNOPSIS  Undo what setup.ps1 / autostart.ps1 changed. Run from an ELEVATED PowerShell. The frame itself is never modified by this script.
.PARAMETER RemoveDriver  also remove the virtual display device and driver package (pnputil)
#>
param([switch]$RemoveDriver)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot "autostart.ps1") -Remove
& python (Join-Path $repo "v100display\frame_watcher.py") --stop 2>$null
Write-Host "Removing the usbipd policy for 10d6:10d6 ..."
usbipd policy remove --effect Allow --operation AutoBind --hardware-id 10d6:10d6
if ($RemoveDriver) {
    Write-Host "Removing the virtual display device and driver ..."
    $dev = pnputil /enum-devices /deviceid "Root\MttVDD" | Select-String "Instance ID:\s*(.+)$"
    foreach ($m in $dev) { pnputil /remove-device $m.Matches[0].Groups[1].Value.Trim() }
    $oem = pnputil /enum-drivers | Select-String -Context 0, 6 "mttvdd.inf"
    foreach ($m in $oem) { $n = ($m.Context.PreContext + $m.Line) -join "`n"; if ($n -match "(oem\d+\.inf)") { pnputil /delete-driver $Matches[1] /uninstall /force } }
}
Write-Host "Done. The Python environments are left in place: %LOCALAPPDATA%\v100display\venv and /opt/v100display/venv in WSL (delete them manually if you wish)."
