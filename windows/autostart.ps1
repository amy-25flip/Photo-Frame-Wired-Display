# SPDX-License-Identifier: GPL-2.0-or-later
<#
.SYNOPSIS  Start the frame watcher hidden at every sign-in of the current user (HKCU Run key, no admin, no scheduled task). -Remove undoes it.
#>
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$name = "V100FrameWatcher"
if ($Remove) {
    Remove-ItemProperty -LiteralPath $key -Name $name -ErrorAction SilentlyContinue
    Write-Host "Removed the sign-in entry."
    exit 0
}
$repo = Split-Path -Parent $PSScriptRoot
$cfg = Join-Path $env:LOCALAPPDATA "v100display\config.json"
if (-not (Test-Path $cfg)) { throw "Run windows\setup.ps1 first (no config at $cfg)." }
$py = (Get-Content $cfg -Raw | ConvertFrom-Json).windows_python
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
if (-not (Test-Path $pyw)) { throw "pythonw.exe not found next to $py" }
$command = '"' + $pyw + '" -u "' + (Join-Path $repo "v100display\frame_watcher.py") + '"'
New-ItemProperty -LiteralPath $key -Name $name -PropertyType String -Value $command -Force | Out-Null
Write-Host "The watcher will start hidden at your next sign-in. Log: $repo\v100display\frame_watcher.log"
