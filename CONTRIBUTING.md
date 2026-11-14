# Contributing

* **Hardware reports** are the most useful thing right now: see `docs/HARDWARE.md` ("Reporting a different frame").
* Run the tests before sending a change: `python -m unittest discover -s tests` and `python -m unittest discover -s flash/tests`
  (needs numpy, unicorn, pyusb; `tests/test_startup.py` also runs on Linux because it mocks the Windows calls).
* Changes to the on-device programs (`v100display/stage1.py`, `s2_c444.py`) need an emulator test and, when they change the uploaded image, a regenerated
  `v100display/stage1-clean.bin` (`python v100display/stage1.py dump v100display/stage1-clean.bin`); CI checks that the committed binary equals the generator output.
* Never commit vendor firmware, boot ROM, flash dumps or anything derived from them in bulk. Hashes and short factual descriptions are fine.
* Anything that writes to the frame's flash must keep the existing guards (region/sector lock, identity check, backup requirement, readback verification) and add model tests.
