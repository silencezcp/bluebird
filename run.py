#!/usr/bin/env python
"""Launch the BlueBird client.

    python run.py
    python run.py sftp://user@host:22
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# before paramiko imports cryptography, so its Python 3.8 deprecation notice
# does not appear in the console or the packaged build's output
from ftpclient.utils import silence_dependency_noise  # noqa: E402

silence_dependency_noise()

from ftpclient.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
