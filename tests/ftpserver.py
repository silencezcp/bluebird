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


#: incremented per server so each one gets its own passive port range
_PASSIVE_SEQ = 0


class TestFTPServer(object):
    """Serves a directory on 127.0.0.1 with a random port."""

    def __init__(self, root: str, user: str = "tester",
                 password: str = "secret", chatty: bool = False) -> None:
        if not HAVE_PYFTPDLIB:
            raise RuntimeError("pyftpdlib is not installed")
        self.root = os.path.abspath(root)
        self.user = user
        self.password = password
        self.host = "127.0.0.1"
        self.port = 0
        #: send an extra informational reply after each transfer, to exercise
        #: the "successful transfer reported as a failure" regression
        self.chatty = chatty
        # Each server needs its OWN passive port range: two servers sharing one
        # range fight over the ports and connections die mid-transfer
        # (EOFError from the control connection).
        global _PASSIVE_SEQ
        _PASSIVE_SEQ += 1
        self.passive_base = 60000 + _PASSIVE_SEQ * 60
        self._server: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> Tuple[str, int]:
        authorizer = DummyAuthorizer()
        authorizer.add_user(self.user, self.password, self.root, perm="elradfmwMT")
        authorizer.add_anonymous(self.root, perm="elr")

        base = ChattyFTPHandler if self.chatty else FTPHandler
        # A private subclass per server: the authorizer, banner and passive
        # port range live on the *class*, so configuring the shared FTPHandler
        # would let a second server clobber a running one.
        handler = type("Handler_%d" % id(self), (base,), {
            "authorizer": authorizer,
            "banner": "Nacre test server ready.",
            "passive_ports": range(self.passive_base,
                                   self.passive_base + 40),
        })

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
            # NOT server.close_all(): under pyftpdlib that is asyncore-wide and
            # tears down every server in the process, including a second test
            # server that is still meant to be running.  Closing the listener
            # and stopping the loop is enough for this harness.
            try:
                server.close()
            except Exception:
                pass
            try:
                server.ioloop.stop()
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


class ChattyFTPHandler(FTPHandler):
    """An FTP handler that injects exactly one extra informational reply.

    ``ftplib.voidresp()`` rejects anything that is not a 2xx *and* raises using
    the bare response text, so a single stray ``226`` used to turn a
    successful download into a failure whose message was literally
    "226 Transfer complete.".

    The injection is deliberately deterministic: after the next transfer the
    *first* following command receives one extra ``226`` line before its real
    reply, and then behaviour returns to normal.  Injecting an unbounded number
    of extra replies would make the channel unrecoverable for any client and
    would not model a real server.
    """

    #: how many transfers should be followed by one stray reply (0 = never)
    stray_after_transfers = 1
    #: set to False to disable injection at runtime
    inject = True

    def __init__(self, *args, **kwargs):
        FTPHandler.__init__(self, *args, **kwargs)
        self._stray_left = self.stray_after_transfers
        self._inject_next_command = False

    def _arm(self) -> None:
        if self.inject and self._stray_left > 0:
            self._inject_next_command = True
            self._stray_left -= 1

    def process_command(self, cmd, *args, **kwargs):
        if self._inject_next_command:
            self._inject_next_command = False
            try:
                self.push("226 Transfer complete.\r\n")
            except Exception:
                pass
        return FTPHandler.process_command(self, cmd, *args, **kwargs)

    def ftp_RETR(self, file):
        FTPHandler.ftp_RETR(self, file)
        self._arm()

    def ftp_STOR(self, file, mode="w"):
        FTPHandler.ftp_STOR(self, file, mode)
        self._arm()


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
    # names with spaces and non-ASCII characters, as music libraries use
    for name in ("Beyond - \u901d\u53bb\u65e5\u5b50.flac",
                 "Christine Welch - \u4e00\u767e\u4e07\u4e2a\u53ef\u80fd.flac"):
        with open(os.path.join(root, name), "wb") as handle:
            handle.write(b"fLaC" + bytes(range(64)) * 40)
