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
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ftpclient import session as S            # noqa: E402
from ftpclient.models import TransferItem, format_size  # noqa: E402
from ftpclient.transfer import plan_downloads, plan_uploads  # noqa: E402
from tests.ftpserver import TestFTPServer, make_tree  # noqa: E402

PASSED = []
FAILED = []


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

        print("\n-- the two session classes stay separate --")
        # A patch once added an FTP-only helper call to SFTPSession.listdir(),
        # which broke every SFTP connection with an AttributeError the UI
        # swallowed.  These checks catch that class of mistake without needing
        # a real SSH server.
        import inspect
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
