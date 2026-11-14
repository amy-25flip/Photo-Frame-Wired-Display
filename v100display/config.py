# SPDX-License-Identifier: GPL-2.0-or-later
"""Runtime configuration for the Windows side (watcher, installer scripts).

Settings (defaults in brackets), overridable by a JSON file and by environment variables:

  wsl_distro   [Ubuntu]                           WSL2 distribution that owns the frame's USB device       V100_WSL_DISTRO
  wsl_python   [/opt/v100display/venv/bin/python] Python inside that distribution (pyusb, numpy, adfu_tool, unicorn)   V100_WSL_PYTHON
  windows_python [python.exe next to the running interpreter]  Windows Python with numpy, opencv-python, mss         V100_WIN_PYTHON

File: %LOCALAPPDATA%\\v100display\\config.json (Windows) or ~/.config/v100display/config.json.
`windows\\setup.ps1` creates the WSL virtual environment at the default location, so most people never need a config file.
"""
import json
import os
import sys
from pathlib import Path

DEFAULTS = {
    "wsl_distro": "Ubuntu",
    "wsl_python": "/opt/v100display/venv/bin/python",
    "windows_python": None,
}
ENV = {"wsl_distro": "V100_WSL_DISTRO", "wsl_python": "V100_WSL_PYTHON", "windows_python": "V100_WIN_PYTHON"}


def config_path():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "v100display" / "config.json"


def load():
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.is_file():
        try:
            cfg.update({k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
    for key, env in ENV.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def windows_python(cfg=None):
    """python.exe (never pythonw.exe: child processes need a stdout) of the Windows interpreter to use."""
    cfg = cfg or load()
    if cfg.get("windows_python"):
        return cfg["windows_python"]
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return str(exe)
