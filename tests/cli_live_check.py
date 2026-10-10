"""Exercise the CLI against the real SFTP server (writes go to a temp dir)."""
from __future__ import annotations

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ftpclient import cli  # noqa: E402
from ftpclient import session as _session  # noqa: E402

TARGET = "sftp://silence@192.168.31.142:22"
SCRATCH = "/tmp/smartftp-cli-check"
LOCAL = os.path.join(os.environ.get("TEMP", "/tmp"), "smartftp-cli-check")


def clean_previous_run() -> None:
    """Start from a clean slate so the check can be run repeatedly."""
    import shutil

    password = os.environ.get("SMART_FTP_PASSWORD")
    client = _session.create_session({
        "protocol": "sftp", "host": "192.168.31.142", "port": 22,
        "user": "silence", "password": password, "timeout": 15})
    try:
        client.connect()
        try:
            removed = client.delete_recursive(SCRATCH)
            print("removed %d leftover object(s) from %s" % (removed, SCRATCH))
        except Exception:  # noqa: BLE001 - it was not there
            print("no leftovers at", SCRATCH)
        client.disconnect()
    except Exception as exc:  # noqa: BLE001
        print("could not pre-clean:", _session.human_error(exc))
    if os.path.isdir(LOCAL):
        shutil.rmtree(LOCAL, ignore_errors=True)


results = []


def run(label, argv, expect=0):
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    out = io.StringIO()
    report = cli.Reporter(quiet=True, stream=io.StringIO())
    code = args.handler(args, out, report)
    body = out.getvalue()
    ok = (code == expect)
    results.append((label, ok, code, body, report))
    print("%s %-34s exit=%d (want %d)"
          % ("[ok]  " if ok else "[FAIL]", label, code, expect))
    if body.strip():
        for line in body.rstrip().splitlines()[:8]:
            print("        " + line[:96])
    if report.failures:
        for name, message in report.failures[:3]:
            print("        failed: %s: %s" % (name, message[:70]))
    print()
    return body


os.environ["SMART_FTP_PASSWORD"] = "123456"

print("=" * 70)
print("CLI against %s" % TARGET)
print("=" * 70)
print()
clean_previous_run()
print()

run("sites", ["sites"])
run("selftest", ["selftest"])
run("ls (short)", ["ls", TARGET])
run("ls -l", ["ls", "-l", TARGET])
run("ls --json", ["ls", "--json", TARGET])
run("ls with pattern", ["ls", TARGET, "--pattern", ".*"])
run("stat a file", ["stat", TARGET, "-r", "/etc/hostname"])
run("cat a file", ["cat", TARGET, "-r", "/etc/hostname"])
run("tree (depth 1)", ["tree", TARGET, "/etc", "--max-depth", "1"])

print("=" * 70)
print("write tests, all inside %s" % SCRATCH)
print("=" * 70)
print()

run("mkdir", ["mkdir", TARGET, "-r", SCRATCH])
run("ls the scratch dir", ["ls", TARGET, SCRATCH])

# a local file to upload
if not os.path.isdir(LOCAL):
    os.makedirs(LOCAL)
sample = os.path.join(LOCAL, "hello.txt")
with io.open(sample, "w", encoding="utf-8") as handle:
    handle.write("hello from the smartftp cli\n")

run("put", ["put", TARGET, sample, "-r", SCRATCH])
run("ls after put", ["ls", "-l", TARGET, SCRATCH])
run("get", ["get", TARGET, "-r", SCRATCH + "/hello.txt",
            "-d", os.path.join(LOCAL, "back.txt")])

downloaded = os.path.join(LOCAL, "back.txt")
if os.path.isfile(downloaded):
    content = io.open(downloaded, encoding="utf-8").read().strip()
    print("round trip content: %r" % content)
    print("MATCHES: %s" % (content == "hello from the smartftp cli"))
print()

run("rename", ["rename", TARGET, "-r", SCRATCH + "/hello.txt",
               "--to", SCRATCH + "/renamed.txt"])
run("rm (recursive)", ["rm", TARGET, "-r", SCRATCH, "--recursive"])
run("ls the scratch dir again", ["ls", TARGET, SCRATCH], expect=1)

print()
print("=" * 70)
failed = [r for r in results if not r[1]]
print("checks: %d   failed: %d" % (len(results), len(failed)))
for label, _ok, code, _body, _report in failed:
    print("  FAILED %s (exit %d)" % (label, code))
