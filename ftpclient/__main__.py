"""Run the client with ``python -m ftpclient``."""

import sys

from .app import run

if __name__ == "__main__":
    sys.exit(run())
