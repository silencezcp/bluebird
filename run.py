#!/usr/bin/env python
"""Launch the Smart FTP client.

    python run.py
    python run.py sftp://user@host:22
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ftpclient.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
