#!/usr/bin/env python
"""Command line front end for BlueBird.

    python bluebird.py ls sftp://user@host:22
    python bluebird.py --help

The same thing without a wrapper script::

    python -m ftpclient.cli ls sftp://user@host:22

(the plain ``python -m ftpclient`` still starts the graphical client)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ftpclient.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
