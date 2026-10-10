"""Command line client tests.

Two kinds of check:

* the parser and the pure helpers, which need no server;
* a full command run against the same in-process FTP server the session tests
  use, so ``ls``/``get``/``put``/``mkdir``/``rm`` are exercised end to end.

Nothing here imports PyQt5 through the CLI: the point of this test file is that
the command line client works without a GUI stack.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ftpclient import cli                      # noqa: E402
from ftpclient import core                     # noqa: E402
from ftpclient import session as S             # noqa: E402
from tests.ftpserver import TestFTPServer, make_tree  # noqa: E402

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print("  [ok]   %s" % name)
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def run(argv, expect=0, label=""):
    """Parse and run a command, returning (exit code, stdout, reporter)."""
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    out = io.StringIO()
    err = io.StringIO()
    report = cli.Reporter(quiet=True, stream=err)
    code = args.handler(args, out, report)
    if label:
        check("%s (exit %d)" % (label, code), code == expect,
              "wanted %d, got %d; stderr=%s" % (expect, code,
                                                err.getvalue()[:120]))
    return code, out.getvalue(), report


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="bluebird-cli-")
    server_root = os.path.join(workdir, "server")
    local_root = os.path.join(workdir, "client")
    os.makedirs(server_root)
    os.makedirs(local_root)
    make_tree(server_root)

    try:
        print("\n-- the data layer needs no Qt --")
        check("core exposes the data types",
              all(hasattr(core, name) for name in
                  ("Entry", "TransferItem", "format_size", "parse_size",
                   "format_time", "FILE_COLUMNS", "SORT_ROLE",
                   "ITEM_ID_ROLE")))
        # a subprocess keeps the parent's already-imported Qt out of the way
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        probe = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import ftpclient.core\n"
            "print('QT' if any(m.startswith('PyQt5') for m in sys.modules)"
            " else 'CLEAN')\n" % root)
        result = subprocess.run([sys.executable, "-c", probe],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        check("importing core loads no PyQt5",
              result.stdout.decode().strip() == "CLEAN",
              result.stdout.decode().strip())

        cli_probe = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import ftpclient.cli\n"
            "print('QT' if any(m.startswith('PyQt5') for m in sys.modules)"
            " else 'CLEAN')\n" % root)
        result = subprocess.run([sys.executable, "-c", cli_probe],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        check("importing the whole CLI loads no PyQt5",
              result.stdout.decode().strip() == "CLEAN",
              result.stdout.decode().strip())

        print("\n-- target parsing --")
        cases = [
            ("sftp://silence@192.168.31.142:22",
             {"protocol": "sftp", "user": "silence",
              "host": "192.168.31.142", "port": 22}),
            ("ftp://user@host", {"protocol": "ftp", "user": "user",
                                 "host": "host"}),
            ("host", {"host": "host"}),
            ("deploy@example.com:2222", {"user": "deploy",
                                         "host": "example.com", "port": 2222}),
            ("sftp://u@h:22/var/www", {"remote_dir": "/var/www",
                                       "port": 22}),
        ]
        for text, expected in cases:
            parsed = cli.parse_target(text)
            ok = all(parsed.get(key) == value
                     for key, value in expected.items())
            check("parse %s" % text, ok, str(parsed))
        try:
            cli.parse_target("gopher://host")
            check("an unknown scheme is rejected", False, "no error")
        except cli.CliError:
            check("an unknown scheme is rejected", True)
        try:
            cli.parse_target("host:notaport")
            check("a non numeric port is rejected", False, "no error")
        except cli.CliError:
            check("a non numeric port is rejected", True)

        print("\n-- output helpers --")
        check("human_size bytes", cli.human_size(512) == "512 B",
              cli.human_size(512))
        check("human_size kilobytes", cli.human_size(2048) == "2.0 KB",
              cli.human_size(2048))
        check("human_size none", cli.human_size(None) == "?")
        check("human_size huge", cli.human_size(5 * 1024 ** 4) == "5.0 TB",
              cli.human_size(5 * 1024 ** 4))

        print("\n-- the parser --")
        parser = cli.build_parser()
        args = parser.parse_args(["ls", "sftp://u@h", "-l", "--json"])
        check("ls flags parse", args.long and args.json and args.command == "ls")
        args = parser.parse_args(["get", "sftp://u@h", "-r", "/a/b", "-f"])
        check("get flags parse", args.remote == "/a/b" and args.force)
        args = parser.parse_args(["put", "sftp://u@h", "one", "two"])
        check("put takes several paths", args.local == ["one", "two"])
        args = parser.parse_args(["rm", "sftp://u@h", "-r", "/x",
                                  "--recursive"])
        check("rm flags parse", args.recursive and args.remote == "/x")
        args = parser.parse_args(["mirror", "sftp://u@h", "--delete", "-d",
                                  "/tmp/x"])
        check("mirror flags parse", args.delete and args.dest == "/tmp/x")
        check("every documented command has a handler",
              all(hasattr(cli, name) for name in cli._COMMANDS))
        # a real minimal command line for each, so the parser is exercised too
        minimal = {
            "ls": ["ls", "t"],
            "stat": ["stat", "t", "-r", "/x"],
            "get": ["get", "t", "-r", "/x"],
            "put": ["put", "t", "some-file"],
            "mirror": ["mirror", "t"],
            "tree": ["tree", "t"],
            "mkdir": ["mkdir", "t", "-r", "/x"],
            "rm": ["rm", "t", "-r", "/x"],
            "rename": ["rename", "t", "-r", "/x", "--to", "/y"],
            "chmod": ["chmod", "t", "644", "-r", "/x"],
            "cat": ["cat", "t", "-r", "/x"],
            "sites": ["sites"],
            "selftest": ["selftest"],
        }
        for name in cli._COMMANDS:
            key = name[4:].replace("_", "-")
            args = parser.parse_args(minimal[key])
            check("%s is wired up" % key,
                  args.handler is getattr(cli, name),
                  str(args.handler))

        print("\n-- usage errors --")
        # argparse exits with EXIT_USAGE on its own for a missing required
        # option, so the resolver is checked directly here
        class Missing(object):
            target = None
            saved = None
            protocol = port = user = password = key = None
            remote_dir = encoding = timeout = passive = None
            verify_host_key = False

        try:
            cli.resolve_connection(Missing())
            check("a target is required", False, "no error raised")
        except cli.CliError as exc:
            check("a target is required", "no target" in str(exc), str(exc))
        # argparse exits the process on its own, so ask a subprocess what code
        # an incomplete command line produces (a missing required option)
        result = subprocess.run(
            [sys.executable, "-m", "ftpclient.cli", "get", "sftp://u@h"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        check("a missing required option exits with the usage code",
              result.returncode == cli.EXIT_USAGE,
              str(result.returncode))
        # and a well formed command with no usable target exits with the error
        # code, because that is the CLI's own error rather than argparse's
        result = subprocess.run(
            [sys.executable, "-m", "ftpclient.cli", "stat", "-r", "/x"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        check("a well formed command with no target exits with the error code",
              result.returncode == cli.EXIT_ERROR,
              str(result.returncode))

        print("\n-- mkdir -p helper --")
        class FakeSession(object):
            """Records what was created; repeats are an error, as real ones are."""

            def __init__(self):
                self.made = []

            def mkdir(self, path):
                if path in self.made:
                    raise S.SessionError("File exists")
                self.made.append(path)

        fake = FakeSession()
        created = cli.remote_mkdir_p(fake, "/a/b/c")
        check("mkdir -p creates parents before children",
              fake.made == ["/a", "/a/b", "/a/b/c"], str(fake.made))
        check("mkdir -p reports creation", created is True)
        again = cli.remote_mkdir_p(fake, "/a/b/c")
        check("mkdir -p is idempotent", again is False, str(again))
        check("mkdir -p did not duplicate anything",
              fake.made == ["/a", "/a/b", "/a/b/c"], str(fake.made))

        class DeniedSession(object):
            def mkdir(self, path):
                raise S.SessionError("Permission denied")

        try:
            cli.remote_mkdir_p(DeniedSession(), "/x")
            check("mkdir -p still reports real errors", False, "no error")
        except S.SessionError:
            check("mkdir -p still reports real errors", True)

        print("\n-- against a live FTP server --")
        server = TestFTPServer(server_root)
        host, port = server.start()
        url = "ftp://tester:secret@%s:%d" % (host, port)
        os.environ["BLUEBIRD_PASSWORD"] = "secret"
        try:
            code, text, _r = run(["ls", url], label="ls lists the server")
            check("ls shows a file", "readme.txt" in text, text[:120])
            check("ls shows a folder with a slash", "docs/" in text,
                  text[:120])

            code, text, _r = run(["ls", url, "-l"], label="ls -l works")
            # a server may report Unix mode bits or the RFC 3659 perm letters
            first_column = text.strip().split()[0] if text.strip() else ""
            check("ls -l shows a permission column",
                  len(first_column) > 4 and not first_column.isdigit(),
                  text[:160])
            check("ls -l shows a size or <DIR>",
                  "B" in text or "<DIR>" in text, text[:160])

            code, text, _r = run(["ls", url, "--json"], label="ls --json works")
            check("json output parses", text.strip().startswith("["),
                  text[:60])

            code, text, _r = run(["stat", url, "-r", "/readme.txt"],
                                 label="stat a file")
            check("stat reports the size", "13 B" in text, text[:200])
            check("stat reports a permission column",
                  "permissions:" in text, text[:200])

            code, text, _r = run(["cat", url, "-r", "/readme.txt"],
                                 label="cat a file")
            check("cat returns the content", "hello" in text, text[:60])

            code, text, _r = run(["tree", url, "/", "--max-depth", "1"],
                                 label="tree walks the server")
            check("tree shows entries", "docs" in text, text[:120])

            target = os.path.join(local_root, "down.txt")
            code, _text, _r = run(["get", url, "-r", "/readme.txt", "-d",
                                   target], label="get downloads")
            check("the file arrived", os.path.isfile(target))
            if os.path.isfile(target):
                content = io.open(target, encoding="utf-8").read()
                check("its content matches", "hello" in content, repr(content))
            code, _text, _r = run(["get", url, "-r", "/readme.txt", "-d",
                                   target], expect=cli.EXIT_ERROR,
                                  label="get refuses to overwrite")
            code, _text, _r = run(["get", url, "-r", "/readme.txt", "-d",
                                   target, "--force"],
                                  label="get --force overwrites")

            upload = os.path.join(local_root, "up.txt")
            io.open(upload, "w", encoding="utf-8").write("uploaded\n")
            code, _text, _r = run(["put", url, upload, "-r", "/docs"],
                                  label="put uploads")
            code, text, _r = run(["ls", url, "/docs"], label="ls sees the upload")
            check("the upload is on the server", "up.txt" in text, text[:120])

            code, _text, _r = run(["mkdir", url, "-r", "/newdir"],
                                  label="mkdir creates a folder")
            code, _text, _r = run(["mkdir", url, "-r", "/newdir"],
                                  label="mkdir twice is not an error")
            code, text, _r = run(["ls", url, "-l"], label="the folder exists")
            check("newdir is listed", "newdir/" in text, text[:200])

            code, _text, _r = run(["rename", url, "-r", "/docs/up.txt", "--to",
                                   "/docs/renamed.txt"],
                                  label="rename works")
            code, text, _r = run(["ls", url, "/docs"], label="after rename")
            check("the new name is there", "renamed.txt" in text, text[:160])

            code, text, report = run(["rm", url, "-r", "/docs",
                                      "--recursive"],
                                     label="rm --recursive works")
            # the quiet reporter keeps stdout clean, so the count is reported
            # rather than printed: check both paths
            check("rm removed something and reported no failure",
                  report.items >= 1 and not report.failures,
                  "items=%d failures=%s" % (report.items, report.failures))
            code, _text, _r = run(["ls", url, "/docs"],
                                  expect=cli.EXIT_ERROR,
                                  label="a missing folder exits 1")
        finally:
            server.stop()

        print("\n-- sites command --")
        code, text, _r = run(["sites"], label="sites runs")
        check("sites prints a header or says there are none",
              "NAME" in text or "no saved" in text, text[:80])

    except Exception:
        traceback.print_exc()
        FAILED.append(("unexpected exception", traceback.format_exc()))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n%s" % ("=" * 62))
    print("passed: %d   failed: %d" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s  %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
