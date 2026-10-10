#!/usr/bin/env python
"""Entry point for the packaged command line client (``BlueBird-cli.exe``).

The GUI is a windowed program, and Windows hands a windowed executable no
console for stdout, so the CLI needs its own console build.  Keeping it a
separate entry point also means PyInstaller analyses it without Qt.

Running this from source is equivalent to ``python -m ftpclient.cli``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ftpclient.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
