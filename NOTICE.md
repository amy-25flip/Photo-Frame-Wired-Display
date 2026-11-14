# Notices and credits

This project is licensed **GPL-2.0-or-later** (see `LICENSE`). It builds on, and is only possible because of, other people's work:

* **actions-adfu-tool** — Actions ADFU boot-ROM loader/recovery tool, GPL-2.0-or-later, <https://github.com/BlackLikeaCat/actions-adfu-tool>, itself based on the
  Rockbox project's work on Actions SoCs (Amaury Pouly / Rockbox). We import its `adfu_tool.device/protocol/codec` modules at run time (installed by `windows/setup.ps1`), and
  `v100display/win_enter_adfu.py` follows the normal-mode → ADFU transition sequence documented and proven there.
* **actions-hacking** by Siarhei Volkau — reverse-engineered ATJ2273 register definitions and a bare-metal LCD bring-up for the same SoC family,
  <https://github.com/SiarheiVolkau/actions-hacking> (GPL). Register names/semantics used in `stage1.py` and the docs come from there; the register map itself is not redistributed here.
* **Virtual Display Driver** — VirtualDrivers/Virtual-Display-Driver 25.7.23 (MIT, signed by SignPath Foundation), <https://github.com/VirtualDrivers/Virtual-Display-Driver>.
  Not included in this repository: `windows/setup.ps1` installs it from files you download, after verifying pinned SHA-256 values and the Authenticode signature. Only our `vdd_settings.xml` is included.
* **Unicorn Engine** (GPL-2.0) and **Capstone** (BSD) — used by the test suite to emulate the MIPS code that runs on the frame.
* The vendor mode-switch command encoding was recovered by static analysis of publicly available Actions Producer Tool software (not executed, not redistributed).

No firmware, boot-ROM or flash content of any vendor is included in this repository, and none must be added. "Actions" and "V100/ATJ2273F" are names used only to identify
the hardware; this project is not affiliated with or endorsed by Actions Semiconductor.
