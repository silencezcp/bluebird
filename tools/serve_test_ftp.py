"""Run the project's test FTP server as a separate process.

The C++ checks are a different program, so they cannot use the in-process test
server the Python suite starts.  This prints the port on one line and then
serves until it is killed, which is what cpp/run_ftp_check.cmd reads.

    python tools/serve_test_ftp.py <root>

Prints: ``PORT <n>``
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.ftpserver import TestFTPServer, make_tree  # noqa: E402


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else ""
    if not root:
        print("usage: serve_test_ftp.py <root>", flush=True)
        return 2
    os.makedirs(root, exist_ok=True)
    make_tree(root)

    server = TestFTPServer(root)
    host, port = server.start()
    # the one line the caller waits for
    print("PORT %d" % port, flush=True)
    print("HOST %s" % host, flush=True)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
