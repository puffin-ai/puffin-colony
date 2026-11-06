"""Windows only: a Python the suite starts, such as `python -m colony` or a race test's worker, runs the suite's stubs
and keeps its HOME the way the suite's own process does (tests/winshim.py). conftest puts this folder on PYTHONPATH
only on Windows, and only for the suite's children."""
import os
import sys

if os.name == "nt":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import winshim

    winshim.install(setattr)
