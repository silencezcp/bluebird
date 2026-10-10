"""An in-process FTP server for tests and demos (pyftpdlib)."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional, Tuple

try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    HAVE_PYFTPDLIB = True
except ImportError:  # pragma: no cover - optional dependency
    HAVE_PYFTPDLIB = False


class TestFTPServer(object):
    """Serves a directory on 127.0.0.1 with a random port."""

    def __init__(self, root: str, user: str = "tester",
                 password: str = "secret") -> None:
        if not HAVE_PYFTPDLIB:
            raise RuntimeError("pyftpdlib is not installed")
        self.root = os.path.abspath(root)
        self.user = user
        self.password = password
        self.host = "127.0.0.1"
        self.port = 0
        self._server: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> Tuple[str, int]:
        authorizer = DummyAuthorizer()
        authorizer.add_user(self.user, self.password, self.root, perm="elradfmwMT")
        authorizer.add_anonymous(self.root, perm="elr")

        handler = FTPHandler
        handler.authorizer = authorizer
        handler.banner = "Nacre test server ready."
        handler.passive_ports = range(60000, 60050)

        server = FTPServer((self.host, 0), handler)
        server.max_cons = 32
        server.max_cons_per_ip = 16
        self._server = server
        self.port = server.socket.getsockname()[1]
        self._thread = threading.Thread(target=server.serve_forever,
                                        kwargs={"timeout": 0.2, "blocking": True,
                                                "handle_exit": False},
                                        daemon=True)
        self._thread.start()
        # give the loop a moment to accept connections
        for _ in range(50):
            time.sleep(0.02)
            if self._thread.is_alive():
                break
        return self.host, self.port

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close_all()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def __enter__(self) -> "TestFTPServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def make_tree(root: str) -> None:
    """Create a small, predictable directory tree for tests."""
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    os.makedirs(os.path.join(root, "media", "nested"), exist_ok=True)
    with open(os.path.join(root, "readme.txt"), "w", encoding="utf-8") as handle:
        handle.write("hello nacre\n")
    with open(os.path.join(root, "data.bin"), "wb") as handle:
        handle.write(bytes(range(256)) * 8)
    with open(os.path.join(root, "docs", "guide.md"), "w", encoding="utf-8") as handle:
        handle.write("# guide\n")
    with open(os.path.join(root, "media", "nested", "deep.txt"), "w",
              encoding="utf-8") as handle:
        handle.write("deep\n")
