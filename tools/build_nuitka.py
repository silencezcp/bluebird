"""Build ``dist-nuitka/BlueBird.dist/`` with Nuitka.

This is the Nuitka counterpart of ``packaging/BlueBird.spec`` and exists so the
two builders can be compared on the same source.  It deliberately reads the
exclusion lists *from the spec* rather than repeating them, so a module excluded
from one build cannot quietly be included in the other.

Run it through ``build_exe_nuitka.cmd``, or directly::

    D:\\DSH_Workspaces\\Ftp\\python.exe tools\\build_nuitka.py
    ... --jobs 8            parallel C compilers
    ... --no-patch          do not touch the Nuitka sources
    ... --skip-manual       do not rebuild the manuals first
    ... --dry-run           print the command line and stop
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "BlueBird.spec")
PACKAGING = os.path.join(ROOT, "packaging")
OUTPUT_DIR = os.path.join(ROOT, "dist-nuitka")
ENTRY = os.path.join(ROOT, "run.py")

#: files that ship beside the executable, as (source, destination folder)
DATA_FILES = [
    ("docs/\u7528\u6237\u624b\u518c.html", "docs"),
    ("docs/\u7528\u6237\u624b\u518c.md", "docs"),
    ("docs/\u7528\u6237\u624b\u518c.pdf", "docs"),
    ("LICENSE", "."),
    ("THIRD-PARTY-NOTICES.txt", "."),
]

#: whole folders that ship beside the executable
DATA_DIRS = [
    ("docs/screenshots", "docs/screenshots"),
]

#: the version metadata, mirroring packaging/version_info.txt.  Nuitka has no
#: option for the copyright or the author, so those are simply not set here;
#: the executable's own About box carries them.
VERSION = {
    "company": "silence",
    "product": "BlueBird",
    "description": "BlueBird - FTP / FTPS / SFTP client",
}


# ---------------------------------------------------------------------------
# reading the existing build configuration
# ---------------------------------------------------------------------------

def _literal(source: str, name: str, default):
    """Read a simple list assignment out of the spec without executing it.

    Executing the spec would run its build calls, so the value is parsed with
    ``ast`` instead.  Plain literals are all the exclusion lists contain.
    """
    match = re.search(r"^%s\s*=\s*(\[[^\]]*\]|\([^)]*\))" % re.escape(name),
                      source, re.MULTILINE | re.DOTALL)
    if not match:
        return default
    try:
        return list(ast.literal_eval(match.group(1)))
    except (ValueError, SyntaxError):
        return default


def spec_settings() -> dict:
    """The exclusions and trim rules the PyInstaller build uses."""
    if not os.path.isfile(SPEC):
        raise SystemExit("the spec is missing: %s" % SPEC)
    source = io.open(SPEC, encoding="utf-8").read()
    return {
        "excludes": _literal(source, "excludes", []),
        "trim_prefixes": _literal(source, "TRIM_PREFIXES", []),
    }


def app_version() -> str:
    """The version the package reports, which is what the exe should carry."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        from ftpclient import __version__
        return __version__
    except Exception:                              # noqa: BLE001
        return "1.30.0"


# ---------------------------------------------------------------------------
# assembling the command line
# ---------------------------------------------------------------------------

def build_command(settings: dict, args: argparse.Namespace) -> list:
    version = app_version()
    icon = os.path.join(PACKAGING, "bluebird.ico")
    command = [
        sys.executable, "-m", "nuitka",
        "--standalone",                    # onedir, to match the PyInstaller build
        "--assume-yes-for-downloads",
        "--output-dir=%s" % OUTPUT_DIR,
        "--output-filename=BlueBird.exe",
        "--enable-plugins=pyqt5",          # 4.3 renamed --enable-plugin
        "--windows-console-mode=disable",  # console=False in the spec
        "--windows-icon-from-ico=%s" % icon,
        "--company-name=%s" % VERSION["company"],
        "--product-name=%s" % VERSION["product"],
        "--file-description=%s" % VERSION["description"],
        "--file-version=%s" % version,
        "--product-version=%s" % version,
        "--report=%s" % os.path.join(OUTPUT_DIR, "nuitka-report.xml"),
        "--jobs=%d" % max(1, args.jobs),
    ]
    if args.lto and args.lto != "no":
        command.append("--lto=%s" % args.lto)

    # the same modules the PyInstaller build throws away
    for name in settings["excludes"]:
        command.append("--nofollow-import-to=%s" % name)

    # the same Qt payload it trims: the translations and the unused QML modules.
    # The spec spells these as bundle paths, so the leading folders are dropped
    # to leave a pattern relative to the PyQt5 package.
    for prefix in settings["trim_prefixes"]:
        pattern = prefix.replace("PyQt5\\Qt5\\", "").replace("\\", "/")
        command.append("--noinclude-data-files=PyQt5/Qt5/%s*" % pattern)

    for source, destination in DATA_FILES:
        full = os.path.join(ROOT, source.replace("/", os.sep))
        if not os.path.isfile(full):
            print("  WARNING %s is missing, skipped" % source)
            continue
        command.append("--include-data-files=%s=%s/%s"
                       % (full.replace(os.sep, "/"), destination,
                          os.path.basename(source)))

    for source, destination in DATA_DIRS:
        full = os.path.join(ROOT, source.replace("/", os.sep))
        if not os.path.isdir(full):
            print("  WARNING %s is missing, skipped" % source)
            continue
        command.append("--include-data-dir=%s=%s"
                       % (full.replace(os.sep, "/"), destination))

    command.append(ENTRY)
    return command


# ---------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------

def patch_nuitka(no_patch: bool) -> None:
    if no_patch:
        print("=== Nuitka source patch skipped (--no-patch) ===")
        return
    print("=== checking the Nuitka sources build with MSVC ===")
    tool = os.path.join(ROOT, "tools", "patch_nuitka.py")
    result = subprocess.call([sys.executable, tool], cwd=ROOT)
    if result != 0:
        raise SystemExit("tools/patch_nuitka.py failed with %d" % result)


def rebuild_manuals(skip: bool) -> None:
    if skip:
        print("=== manual rebuild skipped (--skip-manual) ===")
        return
    print("=== rebuilding the manuals ===")
    result = subprocess.call([sys.executable,
                              os.path.join(ROOT, "tools", "build_manual.py")],
                             cwd=ROOT)
    if result != 0:
        raise SystemExit("the manual build failed with %d" % result)


def compile_with_nuitka(command: list) -> None:
    print("=== compiling with Nuitka ===")
    print("  %s" % " ".join('"%s"' % part if " " in part else part
                           for part in command[3:]))
    print()
    started = time.time()
    result = subprocess.call(command, cwd=ROOT)
    elapsed = time.time() - started
    print()
    if result != 0:
        raise SystemExit("Nuitka failed with exit code %d after %.1f s"
                         % (result, elapsed))
    print("Nuitka finished in %.1f s (%.1f min)" % (elapsed, elapsed / 60.0))


def find_dist() -> str:
    """The ``BlueBird.dist`` folder Nuitka creates."""
    if not os.path.isdir(OUTPUT_DIR):
        return ""
    for name in sorted(os.listdir(OUTPUT_DIR)):
        candidate = os.path.join(OUTPUT_DIR, name)
        if name.endswith(".dist") and os.path.isdir(candidate):
            return candidate
    return ""


def report(dist: str) -> None:
    """Print the size breakdown, so it can be compared with PyInstaller."""
    exe = os.path.join(dist, "BlueBird.exe")
    total = 0
    count = 0
    biggest = []
    for folder, _dirs, files in os.walk(dist):
        for name in files:
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            total += size
            count += 1
            biggest.append((size, os.path.relpath(path, dist)))
    biggest.sort(reverse=True)
    print()
    print("=== result ===")
    print("  folder : %s" % dist)
    if os.path.isfile(exe):
        print("  exe    : %.1f MB" % (os.path.getsize(exe) / 1048576.0))
    print("  total  : %.1f MB in %d files" % (total / 1048576.0, count))
    print("  largest:")
    for size, name in biggest[:8]:
        print("    %8.2f MB  %s" % (size / 1048576.0, name))
    for required in ("docs/\u7528\u6237\u624b\u518c.html",
                     "docs/\u7528\u6237\u624b\u518c.pdf", "LICENSE",
                     "THIRD-PARTY-NOTICES.txt"):
        present = os.path.exists(
            os.path.join(dist, required.replace("/", os.sep)))
        print("  %-30s %s" % (required, "present" if present else "MISSING"))


def self_test(dist: str) -> int:
    exe = os.path.join(dist, "BlueBird.exe")
    if not os.path.isfile(exe):
        print("  no BlueBird.exe to test")
        return 1
    print()
    print("=== self test of the packaged GUI ===")
    log_dir = os.path.join(dist, "logs")
    before = set(os.listdir(log_dir)) if os.path.isdir(log_dir) else set()
    result = subprocess.call([exe, "--selftest", "--log"], cwd=dist)
    print("  exit code: %d" % result)

    # the report goes to the daily log beside the exe
    if os.path.isdir(log_dir):
        for name in sorted(set(os.listdir(log_dir)) - before):
            path = os.path.join(log_dir, name)
            print("  log file : %s" % path)
            with io.open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "selftest" in line:
                        print("    %s" % line.rstrip())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build BlueBird with Nuitka, for comparison with PyInstaller.")
    parser.add_argument("--jobs", type=int,
                       default=max(1, min(8, (os.cpu_count() or 2) // 2)),
                       help="parallel C compilers (default: half the cores, "
                            "capped at 8; each one is a full cl.exe)")
    parser.add_argument("--lto", default="no", choices=["no", "yes"],
                       help="link time optimisation; much slower, smaller output")
    parser.add_argument("--no-patch", action="store_true",
                       help="do not patch the Nuitka sources")
    parser.add_argument("--skip-manual", action="store_true",
                       help="do not rebuild the manuals first")
    parser.add_argument("--dry-run", action="store_true",
                       help="print the command line and stop")
    parser.add_argument("--no-selftest", action="store_true",
                       help="do not run the packaged self test")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    settings = spec_settings()
    if settings["excludes"]:
        print("read %d excluded modules and %d Qt trims from the spec"
              % (len(settings["excludes"]), len(settings["trim_prefixes"])))
    else:
        print("WARNING could not read the excludes from the spec")

    if not os.path.isfile(os.path.join(PACKAGING, "bluebird.ico")):
        print("=== regenerating the icon and version resource ===")
        subprocess.call([sys.executable,
                         os.path.join(ROOT, "tools", "make_icon.py")], cwd=ROOT)

    rebuild_manuals(args.skip_manual)
    patch_nuitka(args.no_patch)

    command = build_command(settings, args)
    if args.dry_run:
        print()
        print("=== command line (dry run) ===")
        for part in command:
            print("  %s" % part)
        return 0

    compile_with_nuitka(command)

    dist = find_dist()
    if not dist:
        raise SystemExit("Nuitka reported success but no .dist folder was found")
    report(dist)
    if args.no_selftest:
        return 0
    return self_test(dist)


if __name__ == "__main__":
    sys.exit(main())
