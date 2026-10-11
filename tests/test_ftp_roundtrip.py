#!/usr/bin/env python
"""End-to-end test of the session + transfer layer against a local FTP server.

Run with the bundled interpreter::

    .\\run_tests.cmd

or directly::

    D:\\DSH_Workspaces\\Ftp\\python.exe tests\\test_ftp_roundtrip.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ftpclient import session as S            # noqa: E402
from ftpclient import transfer as _transfer    # noqa: E402
from ftpclient.models import TransferItem, format_size  # noqa: E402
from ftpclient.transfer import plan_downloads, plan_uploads  # noqa: E402
from tests.ftpserver import TestFTPServer, make_tree  # noqa: E402

import inspect                                 # noqa: E402
import io                                      # noqa: E402

PASSED = []
FAILED = []


def _qt_available() -> bool:
    """True when PyQt5 is importable, so the queue can be exercised."""
    try:
        import PyQt5.QtWidgets  # noqa: F401
        return True
    except ImportError:
        return False


def _make_qapp():
    """A QApplication for the queue test, or False when it cannot be made.

    The offscreen platform is used when no display is set so this works in the
    same headless run as the rest of the suite.
    """
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PyQt5.QtWidgets import QApplication
        return QApplication.instance() or QApplication(["test"])
    except Exception:
        return False


def _pump_events() -> None:
    from PyQt5.QtCore import QEventLoop
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.processEvents(QEventLoop.AllEvents, 50)


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  [ok]   %s" % name)
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def main():
    workdir = tempfile.mkdtemp(prefix="smart-ftp-")
    server_root = os.path.join(workdir, "server")
    local_root = os.path.join(workdir, "client")
    os.makedirs(server_root)
    os.makedirs(local_root)
    make_tree(server_root)

    server = TestFTPServer(server_root)
    host, port = server.start()
    print("FTP test server on %s:%d (root %s)" % (host, port, server_root))

    config = {
        "protocol": "ftp", "host": host, "port": port,
        "user": "tester", "password": "secret", "timeout": 15,
        "passive": True, "keepalive": 0,
    }
    ftp = S.create_session(config)

    try:
        print("\n-- connect --")
        ftp.connect()
        check("connect", ftp.connected)
        check("banner", "BlueBird" in (ftp.banner or ""), ftp.banner)

        print("\n-- listing --")
        entries = ftp.listdir()
        names = sorted(e.name for e in entries)
        check("listdir finds items", "readme.txt" in names and "docs" in names, names)
        by_name = {e.name: e for e in entries}
        expected_size = os.path.getsize(os.path.join(server_root, "readme.txt"))
        check("folder marked as dir", by_name.get("docs") and by_name["docs"].is_dir)
        check("file size reported",
              by_name.get("readme.txt") and by_name["readme.txt"].size == expected_size,
              str(by_name.get("readme.txt").size if by_name.get("readme.txt") else None))
        check("file not a dir",
              by_name.get("readme.txt") and not by_name["readme.txt"].is_dir)

        print("\n-- remote permissions --")
        # pyftpdlib answers MLSD without unix.mode, so the Permissions column
        # has to be filled from the RFC 3659 perm fact instead of staying blank
        file_entry = by_name.get("readme.txt")
        check("a remote file reports permissions",
              bool(file_entry and file_entry.permissions),
              file_entry.permissions if file_entry else "no entry")
        check("a file's permissions start with '-'",
              bool(file_entry and file_entry.permissions.startswith("-")),
              file_entry.permissions if file_entry else "")
        check("a remote folder reports permissions",
              bool(by_name.get("docs") and by_name["docs"].permissions),
              by_name["docs"].permissions if by_name.get("docs") else "")
        check("a folder's permissions start with 'd'",
              bool(by_name.get("docs")
                   and by_name["docs"].permissions.startswith("d")),
              by_name["docs"].permissions if by_name.get("docs") else "")
        check("the raw MLSD perm fact is kept for the tooltip",
              bool(file_entry and file_entry.extra.get("mlsd_perm")),
              str(file_entry.extra) if file_entry else "")
        check("the perm fact is spelled out for humans",
              "read" in S.describe_mlsd_perm("radfwMT")
              and "write" in S.describe_mlsd_perm("radfwMT"),
              S.describe_mlsd_perm("radfwMT"))
        check("M and T are not described twice",
              S.describe_mlsd_perm("MT").count("last-modified") == 1,
              S.describe_mlsd_perm("MT"))

        # a server that does send unix.mode must produce a real mode string
        class _FakeFTP(object):
            def retrlines(self, command, callback):
                for line in ("type=file;size=10;unix.mode=0644;"
                             "modify=20260101120000; a.txt",
                             "type=dir;unix.mode=0755;"
                             "modify=20260101120000; sub"):
                    callback(line)

        parsed = ftp._list_mlsd(_FakeFTP())
        modes = {e.name: e.permissions for e in parsed}
        check("unix.mode becomes a readable file mode",
              modes.get("a.txt") == "-rw-r--r--", str(modes))
        check("unix.mode becomes a readable folder mode",
              modes.get("sub") == "drwxr-xr-x", str(modes))
        check("octal parsing rejects junk", S._mode_from_octal("zz") is None)
        check("octal parsing accepts the 0o prefix",
              S._mode_from_octal("0o644") == 0o644,
              str(S._mode_from_octal("0o644")))

        print("\n-- navigation --")
        cwd = ftp.chdir("docs")
        check("chdir docs", cwd.rstrip("/").endswith("docs"), cwd)
        docs = ftp.listdir()
        check("listdir in docs", any(e.name == "guide.md" for e in docs),
              [e.name for e in docs])
        ftp.chdir("/")
        check("chdir root", ftp.cwd() in ("/", ""))

        print("\n-- download a single file --")
        progress = []
        target = os.path.join(local_root, "readme.txt")
        written = ftp.download_file("readme.txt", target,
                                    lambda d, t: progress.append((d, t)))
        with open(target, "r", encoding="utf-8") as handle:
            content = handle.read()
        check("download size", written == expected_size, str(written))
        check("download content", content.strip() == "hello smart", repr(content))
        check("progress reported", len(progress) >= 2, str(len(progress)))
        check("progress reached total", progress[-1][0] == expected_size,
              str(progress[-1]))

        print("\n-- upload a single file --")
        upload_src = os.path.join(local_root, "upload.bin")
        payload = bytes(range(256)) * 32          # 8 KiB
        with open(upload_src, "wb") as handle:
            handle.write(payload)
        sent = ftp.upload_file(upload_src, "upload.bin")
        check("upload size", sent == len(payload), "%s vs %s" % (sent, len(payload)))
        got = ftp.listdir()
        uploaded = [e for e in got if e.name == "upload.bin"]
        check("uploaded file appears", bool(uploaded))
        check("uploaded size correct",
              uploaded and uploaded[0].size == len(payload),
              str(uploaded[0].size if uploaded else None))

        print("\n-- download it back and compare --")
        back = os.path.join(local_root, "upload-back.bin")
        ftp.download_file("upload.bin", back)
        with open(back, "rb") as handle:
            check("round trip identical", handle.read() == payload)

        print("\n-- large file (2 MiB) --")
        big_src = os.path.join(local_root, "big.bin")
        big = os.urandom(2 * 1024 * 1024)
        with open(big_src, "wb") as handle:
            handle.write(big)
        started = time.time()
        ftp.upload_file(big_src, "big.bin")
        elapsed = time.time() - started
        big_back = os.path.join(local_root, "big-back.bin")
        ftp.download_file("big.bin", big_back)
        with open(big_back, "rb") as handle:
            check("2 MiB round trip identical", handle.read() == big)
        print("       (2 MiB up+down in %.2fs)" % elapsed)

        print("\n-- mkdir / rename / delete --")
        ftp.mkdir("created")
        check("mkdir", any(e.name == "created" and e.is_dir
                           for e in ftp.listdir()))
        ftp.rename("created", "renamed")
        names = [e.name for e in ftp.listdir()]
        check("rename", "renamed" in names and "created" not in names, names)
        ftp.delete("renamed", is_dir=True)
        check("rmdir", "renamed" not in [e.name for e in ftp.listdir()])
        ftp.delete("upload.bin", is_dir=False)
        check("delete file", "upload.bin" not in [e.name for e in ftp.listdir()])

        print("\n-- recursive upload plan --")
        tree_src = os.path.join(local_root, "tree")
        os.makedirs(os.path.join(tree_src, "a", "b"))
        with open(os.path.join(tree_src, "a", "one.txt"), "w") as handle:
            handle.write("one")
        with open(os.path.join(tree_src, "a", "b", "two.txt"), "w") as handle:
            handle.write("two")
        items = plan_uploads([tree_src], "/")
        check("plan includes directories", sum(1 for i in items if i.is_dir) == 3,
              [i.target for i in items])
        check("plan includes files", sum(1 for i in items if not i.is_dir) == 2,
              [i.target for i in items])
        check("nested target path",
              any(i.target == "tree/a/b/two.txt" for i in items),
              [i.target for i in items])
        for item in items:
            if item.is_dir:
                try:
                    ftp.mkdir(item.target)
                except S.SessionError:
                    pass
            else:
                ftp.upload_file(item.source, item.target)
        probe = ftp.listdir("/tree/a/b")
        check("nested upload landed", any(e.name == "two.txt" for e in probe),
              [e.name for e in probe])

        print("\n-- recursive download plan --")
        target_dir = os.path.join(local_root, "pulled")
        os.makedirs(target_dir, exist_ok=True)
        root_entries = [e for e in ftp.listdir() if e.name == "tree"]
        items = plan_downloads(ftp, "/", root_entries, target_dir)
        for item in items:
            if item.is_dir:
                S.ensure_local_dir(item.target)
            else:
                ftp.download_file(item.source, item.target)
        check("recursive download",
              os.path.isfile(os.path.join(target_dir, "tree", "a", "b", "two.txt")))

        print("\n-- text read/write --")
        ftp.write_text("notes.txt", "line one\nline two\n")
        check("write_text", ftp.read_text("notes.txt") == "line one\nline two\n")

        print("\n-- delete_recursive --")
        ftp.delete_recursive("tree", True)
        check("recursive delete", "tree" not in [e.name for e in ftp.listdir()])

        print("\n-- error handling --")
        try:
            ftp.chdir("/definitely-not-here")
            check("bad chdir raises", False, "no exception")
        except S.SessionError as exc:
            check("bad chdir raises", True)
            check("bad chdir message", bool(exc.message), exc.message)
        # every FTP error path must surface a SessionError, never a TypeError
        # from a malformed `except` tuple
        for label, call in [
                ("delete", lambda: ftp.delete("no-such-file.txt", False)),
                ("rmdir", lambda: ftp.delete("no-such-dir", True)),
                ("rename", lambda: ftp.rename("no-a", "no-b")),
                ("mkdir existing", lambda: ftp.mkdir("docs")),
                ("chmod", lambda: ftp.chmod("no-such-file.txt", 0o644)),
                ("write bad path", lambda: ftp.write_text("nodir/x.txt", "x")),
                ("read missing", lambda: ftp.read_text("no-such-file.txt"))]:
            try:
                call()
                check("error path %s reports a SessionError" % label, False,
                      "call unexpectedly succeeded")
            except S.SessionError as exc:
                check("error path %s reports a SessionError" % label,
                      bool(exc.message), exc.message)
            except Exception as exc:  # noqa: BLE001
                check("error path %s reports a SessionError" % label, False,
                      "%s: %s" % (type(exc).__name__, exc))

        print("\n-- per-file size lookup (SIZE / MDTM) --")
        info = ftp.stat_file("readme.txt")
        check("stat_file reports a size", info and info.get("size") == expected_size,
              str(info))
        check("stat_file reports a modification time", info and info.get("mtime"),
              str(info))
        check("stat_file on a missing file returns None",
              ftp.stat_file("no-such-file.txt") is None)
        check("listing still supplies sizes",
              all(e.size is not None for e in ftp.listdir() if not e.is_dir))
        check("connection still usable after stat round trip",
              "readme.txt" in [e.name for e in ftp.listdir()])
        bad = S.create_session({
            "protocol": "ftp", "host": "127.0.0.1", "port": 1,
            "user": "x", "password": "y", "timeout": 3})
        try:
            bad.connect()
            check("bad connect raises", False, "no exception")
        except S.SessionError as exc:
            check("bad connect raises", True)
            check("bad connect message readable",
                  "refused" in exc.message.lower() or "connect" in exc.message.lower(),
                  exc.message)

        print("\n-- a chatty server must not break transfers --")
        # Some servers (and proxies) repeat the completion line.  ftplib's
        # voidresp() rejects anything that is not a 2xx and raises with the bare
        # response text, so one stray "226 Transfer complete." used to make a
        # successful download report as failed with exactly that message.
        chatty_root = os.path.join(workdir, "chatty")
        os.makedirs(chatty_root, exist_ok=True)
        make_tree(chatty_root)
        chatty = TestFTPServer(chatty_root, chatty=True)
        chatty_host, chatty_port = chatty.start()
        talkative = S.create_session({
            "protocol": "ftp", "host": chatty_host, "port": chatty_port,
            "user": "tester", "password": "secret", "timeout": 15})
        try:
            talkative.connect()
            names = [e.name for e in talkative.listdir()]
            flac = [n for n in names if n.endswith(".flac")]
            check("the chatty server lists the music files", len(flac) == 2,
                  str(names))
            failures = []
            for name in flac:
                target = os.path.join(local_root, "chatty_" + name)
                try:
                    got = talkative.download_file(name, target)
                except Exception as exc:  # noqa: BLE001
                    failures.append("%s: %s" % (name, S.human_error(exc)))
                    continue
                expected = os.path.getsize(os.path.join(chatty_root, name))
                if got != expected:
                    failures.append("%s: %d/%d bytes" % (name, got, expected))
                elif open(target, "rb").read() != open(
                        os.path.join(chatty_root, name), "rb").read():
                    failures.append("%s: content differs" % name)
            check("stray completion replies do not fail the download",
                  not failures, "; ".join(failures))
            check("a non-ASCII name with spaces downloads intact",
                  os.path.isfile(os.path.join(
                      local_root, "chatty_" + flac[0])),
                  flac[0])
            # the session must still be usable afterwards
            check("the session is still usable after the stray reply",
                  len(talkative.listdir()) == len(names),
                  str(len(talkative.listdir())))
            # and a second pass must work too - a desync would show up here
            again = 0
            for name in flac:
                try:
                    talkative.download_file(
                        name, os.path.join(local_root, "again_" + name))
                    again += 1
                except Exception:  # noqa: BLE001
                    pass
            check("a second pass over the same files also succeeds",
                  again == len(flac), "%d/%d" % (again, len(flac)))
        finally:
            try:
                talkative.disconnect()
            except Exception:
                pass
            chatty.stop()

        print("\n-- cancel a transfer --")
        control = S.TransferControl()
        control.cancel()
        try:
            ftp.download_file("data.bin", os.path.join(local_root, "cancelled.bin"),
                              None, control)
            check("cancelled transfer raises", False, "no exception")
        except S.Cancelled:
            check("cancelled transfer raises", True)
        ftp.connect()
        check("reconnect after cancel", ftp.connected)
        ended = ftp.listdir()
        check("usable after reconnect", any(e.name == "readme.txt" for e in ended))

        print("\n-- FTP cannot run two transfers at once --")
        # Two transfers started together race for the one data socket, and the
        # loser is truncated to a single chunk with no error raised.  The check
        # below is the wrong-file evidence, not a fix: it is kept so the reason
        # the queue clamps FTP is visible in the suite and cannot be "cleaned
        # up" by accident.
        check("the FTP session asks for serial transfers",
              getattr(S.FTPSession, "serial_transfers", False) is True)
        check("the SFTP session does not",
              getattr(S.SFTPSession, "serial_transfers", True) is False)

        calls = {"active": 0, "peak": 0}
        real = S.FTPSession.download_file

        def counting(self, name, target, progress=None, control=None):
            calls["active"] += 1
            calls["peak"] = max(calls["peak"], calls["active"])
            try:
                return real(self, name, target, progress, control)
            finally:
                calls["active"] -= 1

        big = "parallel-probe.bin"
        payload = os.urandom(512 * 1024)
        local_big = os.path.join(workdir, big)
        with open(local_big, "wb") as handle:
            for _ in range(4):
                handle.write(payload)
        ftp.upload_file(local_big, big)
        expected = os.path.getsize(local_big)

        def fetch(index, suffix=""):
            target = os.path.join(workdir, "parallel-out%s%d" % (suffix, index))
            try:
                return True, ftp.download_file(big, target)
            except Exception as exc:                  # noqa: BLE001
                return False, "%s: %s" % (type(exc).__name__, exc)

        def run_together(count):
            results = {}

            def work(index):
                results[index] = fetch(index, "raw")

            workers = [threading.Thread(target=work, args=(i,))
                       for i in range(count)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            return results

        S.FTPSession.download_file = counting
        try:
            raw = run_together(4)
        finally:
            S.FTPSession.download_file = real
        sizes = sorted(value for ok, value in raw.values() if ok)
        check("running four FTP transfers at once really does truncate",
              sizes != [expected] * 4,
              "all four were correct (%s), so the clamp is untested" % sizes)
        print("        (reproduced: %s of %s bytes)"
              % (sizes, expected))

        # the queue must clamp, because the session itself does not
        check("the queue reads the serial-transfers flag",
              "serial_transfers" in inspect.getsource(
                  _transfer.TransferManager._pump))

        if _qt_available():
            workdir_qt = _make_qapp()
            if workdir_qt:
                from ftpclient import config as _config
                from ftpclient.models import TransferItem as _Item

                settings = _config.Settings()
                settings.set("transfers", "concurrency", 4)
                manager = _transfer.TransferManager(ftp, settings)
                queued = []
                for index in range(3):
                    item = _Item("download", big,
                                 os.path.join(workdir, "queued%d" % index))
                    item.size = expected
                    queued.append(item)
                calls["peak"] = 0
                S.FTPSession.download_file = counting
                try:
                    manager.enqueue(queued)
                    deadline = time.time() + 60
                    while time.time() < deadline:
                        _pump_events()
                        if manager.pending() == 0:
                            break
                        time.sleep(0.02)
                finally:
                    S.FTPSession.download_file = real
                check("the queued FTP downloads all finished",
                      manager.pending() == 0, manager.summary())
                check("the queue ran them one at a time, despite 4 being asked",
                      calls["peak"] == 1, "peak was %d" % calls["peak"])
                arrived = [index for index in range(3)
                           if os.path.isfile(
                               os.path.join(workdir, "queued%d" % index))
                           and os.path.getsize(
                               os.path.join(workdir, "queued%d" % index))
                           == expected]
                check("every queued download arrived whole",
                      len(arrived) == 3, str(arrived))
        else:
            print("        (PyQt5 not installed: the queue clamp is only "
                  "checked for the flag)")

        print("\n-- ASCII mode only for whitelisted extensions --")
        # Binary is the default because it is byte exact; ASCII re-encodes line
        # endings, so it must not be used for a file that is not on the list.
        from ftpclient.transfer import TransferManager as _TM
        from ftpclient import config as _cfg

        cfg_dir = os.path.join(workdir, "modecfg")
        os.makedirs(cfg_dir)
        os.environ["BLUEBIRD_SETTINGS"] = os.path.join(cfg_dir, "settings.json")
        os.environ["BLUEBIRD_CONFIG"] = os.path.join(cfg_dir, "config.ini")
        mode_settings = _cfg.Settings()
        mode_settings.set("transfers", "ascii_extensions",
                          ".txt .html .md")
        mode_manager = _TM(ftp, mode_settings)

        def item_named(name):
            return TransferItem("download", name, os.path.join(workdir, name))

        check("a .txt file is sent as ASCII",
              mode_manager.mode_for(item_named("readme.txt")) == "ascii")
        check("a .MD file matches case insensitively",
              mode_manager.mode_for(item_named("NOTES.MD")) == "ascii")
        check("a .zip file stays binary",
              mode_manager.mode_for(item_named("archive.zip")) == "binary")
        check("a file with no extension stays binary",
              mode_manager.mode_for(item_named("Makefile")) == "binary")
        check("a name merely containing .txt stays binary",
              mode_manager.mode_for(item_named("notes.txt.bak")) == "binary")
        check("a folder is binary",
              mode_manager.mode_for(
                  TransferItem("download", "dir", "dir", is_dir=True))
              == "binary")

        mode_settings.set("transfers", "ascii_extensions", "")
        check("an empty whitelist means everything is binary",
              mode_manager.mode_for(item_named("readme.txt")) == "binary")

        mode_settings.set("transfers", "ascii_extensions", "txt, log")
        check("extensions may be separated by commas and lack the dot",
              mode_manager.mode_for(item_named("a.txt")) == "ascii"
              and mode_manager.mode_for(item_named("b.log")) == "ascii")

        mode_settings.set("transfers", "ascii_extensions", ".txt")
        check("the retry default is five",
              _cfg.Settings().get("transfers", "retries", None) == 5
              or mode_settings.get("transfers", "retries", None) == 5)
        check("the concurrency default is five",
              mode_settings.get("transfers", "concurrency", None) == 5)

        print("\n-- ASCII mode converts line endings --")
        crlf = b"one\r\ntwo\r\nthree\r\n"
        lf = b"one\ntwo\nthree\n"
        text_path = os.path.join(workdir, "newlines.txt")
        with open(text_path, "wb") as handle:
            handle.write(crlf)

        ftp2 = S.create_session({"protocol": "ftp", "host": host, "port": port,
                                 "user": "tester", "password": "secret",
                                 "timeout": 20})
        ftp2.connect()
        try:
            # binary must be byte exact in both directions
            ftp2._set_transfer_type("binary")
            ftp2.upload_file(text_path, "nl-bin.txt")
            with open(os.path.join(server_root, "nl-bin.txt"), "rb") as fh:
                check("binary upload is byte exact", fh.read() == crlf)
            back = os.path.join(workdir, "nl-bin-back.txt")
            ftp2.download_file("nl-bin.txt", back)
            with open(back, "rb") as fh:
                check("binary download is byte exact", fh.read() == crlf)

            # ASCII: the server convention is Unix, the local one is Windows
            ftp2._set_transfer_type("ascii")
            ftp2.upload_file(text_path, "nl-asc.txt")
            with open(os.path.join(server_root, "nl-asc.txt"), "rb") as fh:
                check("ascii upload sends LF to the server", fh.read() == lf)
            # stage an LF file on the server, which is what a Unix server has
            with open(os.path.join(server_root, "nl-lf.txt"), "wb") as fh:
                fh.write(lf)
            back2 = os.path.join(workdir, "nl-lf-back.txt")
            ftp2.download_file("nl-lf.txt", back2)
            with open(back2, "rb") as fh:
                check("ascii download writes CRLF locally", fh.read() == crlf)
        finally:
            ftp2.disconnect()

        print("\n-- a large batch is queued without asking per file --")
        # Listing the directory once per file cost 33 seconds for 600 files
        # before the first byte moved.  This reproduces that path directly.
        listed = {"n": 0}
        real_listdir = S.FTPSession.listdir

        def counted_listdir(self, path=""):
            listed["n"] += 1
            return real_listdir(self, path)

        class _StubWindow(object):
            """The parts of MainWindow._confirm_overwrite_upload."""

            def __init__(self, session):
                self.session = session
                self.settings = mode_settings
                self._overwrite_all = False
                self._upload_dir_names = None
                self._remote_dir = "/"

            def _remote_join(self, name):
                return "/" + name

            def _message(self, *_args, **_kwargs):
                return 0

        from ftpclient.main import MainWindow as _MW
        stub = _StubWindow(ftp2 if False else ftp)
        confirm = _MW._confirm_overwrite_upload.__get__(stub)
        batch = [item_named("batch%04d.txt" % index) for index in range(300)]
        for entry_index, item in enumerate(batch):
            item.target = "/batch%04d.txt" % entry_index

        S.FTPSession.listdir = counted_listdir
        try:
            answers = [confirm(item) for item in batch]
        finally:
            S.FTPSession.listdir = real_listdir
        check("every file in the batch was answered", len(answers) == 300,
              str(len(answers)))
        check("the directory was listed once, not once per file",
              listed["n"] == 1, "%d listings" % listed["n"])

        print("\n-- the daily log file --")
        from ftpclient import logfile as _logfile

        log = _logfile.reset(os.path.join(workdir, "logs"))
        log.write("info", "first line")
        log.write("error", "second line")
        log.write("success", "third line")
        name = os.path.basename(log.path())
        check("the log is named for today, YYYYMMDD.log",
              name == "%s.log" % _logfile.date_stamp(), name)
        check("the log lives in a logs folder",
              os.path.basename(log.directory) == "logs", log.directory)
        text = io.open(log.path(), encoding="utf-8").read()
        check("every line reached the file",
              all(marker in text
                  for marker in ("first line", "second line", "third line")))
        check("the level is recorded",
              "INFO" in text and "ERROR" in text and "OK" in text)
        check("a multi line message is kept on one line",
              len([line for line in text.splitlines()
                   if "second line" in line]) == 1)
        check("the file opens with a header",
              "log started" in text.splitlines()[:6].__str__()
              or "log started" in text[:400])

        # reopening must append, not truncate or repeat the header
        log.close()
        again = _logfile.reset(os.path.join(workdir, "logs"))
        again.write("info", "after a restart")
        after = io.open(again.path(), encoding="utf-8").read()
        check("a restart appends to today's file",
              "first line" in after and "after a restart" in after)
        check("the header is written only for a new day",
              after.count("log started") == 1, str(after.count("log started")))

        # the date the file is named for must roll over
        again._day = "20260101"          # pretend we are on a different day
        again.write("info", "the next day")
        rolled = os.path.join(again.directory, "%s.log"
                              % _logfile.date_stamp())
        check("a new day starts a new file", os.path.isfile(rolled))
        if os.path.isfile(rolled):
            check("the new day gets its own header",
                  "log started" in io.open(rolled, encoding="utf-8").read())
        again.close()

        # logging must never raise, even when the folder cannot be made
        blocked = _logfile.DailyLog(os.path.join(workdir, "nul", "logs"))
        try:
            blocked.write("info", "into nowhere")
            raised = False
        except Exception:                          # noqa: BLE001
            raised = True
        check("a bad log folder does not raise", not raised)
        check("a bad log folder is reported once", bool(blocked.error))
        blocked.close()

        print("\n-- the queue writes what the pane shows --")
        # The pane used to be the only place a transfer was visible: the queue
        # emitted no log lines at all, so a finished batch left nothing on disk.
        from ftpclient.transfer import describe_item, describe_result

        up = TransferItem("upload", r"C:\local\big file.zip",
                          "/remote/docs/big file.zip", size=2411724)
        down = TransferItem("download", "/remote/docs/big file.zip",
                            r"C:\local\big file.zip", size=2411724)
        up_line = describe_item(up)
        down_line = describe_item(down)
        check("an upload reads as -> and names the local path first",
              "UPLOAD ->" in up_line and "local: %s" % up.source in up_line
              and "remote: %s" % up.target in up_line, up_line)
        check("a download reads as <- and names the remote path first",
              "DOWNLOAD <-" in down_line
              and "remote: %s" % down.source in down_line
              and "local: %s" % down.target in down_line, down_line)
        check("the size and the file name are in the line",
              "2.3 MB" in up_line and "big file.zip" in up_line, up_line)
        folder = TransferItem("download", "/remote/docs", r"C:\out\docs",
                              is_dir=True)
        check("a folder is labelled as one", "folder" in describe_item(folder))
        check("the line is single line, so the log stays greppable",
              "\n" not in up_line and "\n" not in down_line)

        done_item = TransferItem("download", "/r/a.bin", "C:/a.bin", size=2048)
        done_item.status = "done"
        done_item.transferred = 2048
        result = describe_result(done_item, 1.0)
        check("a finished transfer reports size, rate and time",
              "2.0 KB" in result and "/s" in result and "1.0 s" in result,
              result)
        done_item.status = "error"
        check("a failed transfer says so", describe_result(done_item, 1.0) == "failed")
        done_item.status = "cancel"
        check("a cancelled transfer says so",
              describe_result(done_item, 1.0) == "cancelled")

        queue_source = inspect.getsource(_transfer.TransferManager)
        worker_source = inspect.getsource(_transfer.TransferWorker)
        check("enqueue records every item it accepts",
              '"Queued %s %s %s' in queue_source, "no line in enqueue")
        check("a started transfer is recorded",
              '"Started: %s"' in worker_source, "no Started line")
        check("a settled transfer is recorded",
              '"Finished"' in queue_source and '"Failed"' in queue_source,
              "no outcome line")
        check("a retry is recorded", '"Retrying (%d/%d)' in queue_source,
              "no retry line")

        if _qt_available() and _make_qapp():
            from ftpclient import config as _config2

            settings2 = _config2.Settings()
            manager3 = _transfer.TransferManager(ftp, settings2)
            manager3._stopped = True                # do not start transferring
            seen = []
            manager3.log.connect(lambda level, message: seen.append(
                (level, message)))
            probe = [TransferItem("download", "/r/one.bin", "C:/one.bin",
                                  size=100),
                     TransferItem("upload", "C:/two.bin", "/r/two.bin",
                                  size=200)]
            manager3.enqueue(probe)
            queued = [message for _level, message in seen
                      if message.startswith("Queued")]
            check("the queue emits one log line per item", len(queued) == 2,
                  str(len(queued)))
            check("those lines carry the direction",
                  any("download <-" in line for line in queued)
                  and any("upload ->" in line for line in queued),
                  str(queued))
            manager3.shutdown()

        print("\n-- the two session classes stay separate --")
        # A patch once added an FTP-only helper call to SFTPSession.listdir(),
        # which broke every SFTP connection with an AttributeError the UI
        # swallowed.  These checks catch that class of mistake without needing
        # a real SSH server.
        import re as _re
        ftp_only = ("_sync_control", "_drain_control", "_begin_transfer",
                    "_finish_command", "_remote_size", "_pasv_socket")
        sftp_source = inspect.getsource(S.SFTPSession)
        leaked = [name for name in ftp_only
                  if ("self.%s(" % name) in sftp_source]
        check("SFTPSession does not call FTP-only helpers", not leaked,
              str(leaked))
        check("the FTP helpers live on FTPSession",
              all(hasattr(S.FTPSession, name) for name in ftp_only))
        check("SFTPSession has none of them",
              not any(hasattr(S.SFTPSession, name) for name in ftp_only))
        # every private helper a class calls must exist on that class
        for cls in (S.FTPSession, S.SFTPSession):
            called = set(_re.findall(r"self\.(_[a-z_]+)\(", 
                                     inspect.getsource(cls)))
            missing = sorted(name for name in called if not hasattr(cls, name))
            check("%s only calls methods it has" % cls.__name__, not missing,
                  str(missing))

    except Exception:
        traceback.print_exc()
        FAILED.append(("unexpected exception", traceback.format_exc()))
    finally:
        try:
            ftp.disconnect()
        except Exception:
            pass
        server.stop()
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n%s" % ("=" * 62))
    print("passed: %d   failed: %d" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s  %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
