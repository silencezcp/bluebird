"""Write THIRD-PARTY-NOTICES.txt from the licence texts shipped in the wheels.

MIT, BSD, Apache-2.0, PSF and LGPL all require their licence text to travel
with the binaries, so this collects the texts that are actually installed on
the build machine instead of reproducing them from memory.

    python tools/make_notices.py            # write the file
    python tools/make_notices.py --report   # show what was found, write nothing
"""
from __future__ import annotations

import glob
import io
import os
import re
import site
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from deps_report import licence_of                     # noqa: E402

SITE = site.getsitepackages()[-1]
RULE = "=" * 78
THIN = "-" * 78


def _dist_dirs() -> "dict":
    """distribution key -> its .dist-info folders."""
    table = {}
    for folder in glob.glob(os.path.join(SITE, "*.dist-info")):
        stem = os.path.basename(folder).split("-")[0]
        table.setdefault(stem.lower().replace("_", "-"), []).append(folder)
    return table


def licence_files(name: str) -> "list":
    """(basename, size, path) for every licence-looking file a wheel ships.

    Shortest first: a bundled MIT text is what should be quoted, while some
    wheels also carry a huge aggregated notice that would swamp the file.
    """
    key = name.lower().replace("_", "-")
    out = []
    for folder in _dist_dirs().get(key, []):
        for path in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
            if not os.path.isfile(path):
                continue
            base = os.path.basename(path)
            lowered = base.lower()
            interesting = (lowered.startswith(("licen", "copying", "notice"))
                           or lowered in ("license", "licence"))
            if not interesting:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size < 40:
                continue
            out.append((base, size, path))
    out.sort(key=lambda item: (item[1] > 150000, item[1]))
    return out


def read(path: str) -> str:
    return io.open(path, encoding="utf-8", errors="replace").read() \
        .replace("\r\n", "\n").strip()


def licence_texts() -> "set":
    """Fingerprints of the licence text that is already in LICENSE.

    The Qt wheel carries the whole GNU GPL ahead of its other content, and that
    text is the project's own LICENSE, so comparing whole files is not enough:
    the opening words differ.  Both sides are therefore fingerprinted from the
    GPL heading, and a match is what lets the notices point at LICENSE instead
    of quoting 32 KB again.
    """
    path = os.path.join(ROOT, "LICENSE")
    if not os.path.isfile(path):
        return set()
    body = read(path)
    prints = {re.sub(r"\W+", "", body[:300]).lower()}
    heading = "GNU GENERAL PUBLIC LICENSE"
    index = body.find(heading)
    if index >= 0:
        prints.add(re.sub(r"\W+", "", body[index:index + 300]).lower())
    return prints


def requirements_groups() -> "list":
    """[(group title, [distribution, ...])] in the order requirements.txt uses."""
    groups = []
    for line in io.open(os.path.join(ROOT, "requirements.txt"),
                        encoding="ascii").read().splitlines():
        if line.startswith("# ") and " - " in line:
            title = line.strip("# ").split(" - ")[0]
            if title.isupper():
                groups.append((title, []))
        elif "==" in line and not line.startswith("#") and groups:
            groups[-1][1].append(line.split("==")[0].strip())
    return groups


def main() -> int:
    report_only = "--report" in sys.argv
    groups = requirements_groups()
    total = sum(len(rows) for _title, rows in groups)
    print("read %d component(s) in %d group(s)" % (total, len(groups)))

    # distinct licence texts, keyed on a fingerprint of the opening words
    already = licence_texts()
    texts = {}          # fingerprint -> {"names": [...], "text": str,
                        #                "in_license": bool}
    for _title, rows in groups:
        for name in rows:
            found = licence_files(name)
            if not found:
                continue
            body = read(found[0][2])
            if len(body) < 60:
                continue
            fingerprint = re.sub(r"\W+", "", body[:300]).lower()
            heading = "GNU GENERAL PUBLIC LICENSE"
            index = body.find(heading)
            if index >= 0:
                fingerprint = re.sub(r"\W+", "", body[index:index + 300]).lower()
            entry = texts.setdefault(
                fingerprint,
                {"names": [], "text": body,
                 "in_license": fingerprint in already})
            entry["names"].append(name)

    print("distinct licence text(s) found in the wheels: %d" % len(texts))
    embedded = 0
    for entry in texts.values():
        first = entry["text"].splitlines()[0][:54]
        if entry["in_license"]:
            print("   %-52s (already in LICENSE)" % ", ".join(
                entry["names"])[:52])
            continue
        embedded += 1
        print("   %-52s %s" % (", ".join(entry["names"])[:52], first))
    print("   embedded: %d, skipped as duplicates of LICENSE: %d"
          % (embedded, len(texts) - embedded))

    without = [name for _t, rows in groups for name in rows
               if not licence_files(name)]
    print("component(s) shipping no licence file: %d" % len(without))
    if without:
        print("   %s" % ", ".join(without))

    lines = [
        "THIRD-PARTY NOTICES AND LICENSING NOTES",
        "======================================",
        "",
        "BlueBird is distributed under the GNU General Public License version 3.",
        "The full text is in LICENSE beside this file.  The program name and",
        "copyright line sit at the top of it, as the GPL itself instructs.",
        "",
        "This file carries the rest of the licensing picture: why the GPL applies",
        "here, and the licence of every component the program is built on.",
        "",
        "-" * 78,
        "WHY THE GPL APPLIES",
        "-" * 78,
        "",
        "* PyQt5 and PyQtWebEngine are GPL-3.0-only or commercial, from Riverbank",
        "  Computing, at your choice.  Distributing BlueBird under the GPL is what",
        "  makes that use compliant.  A build distributed as closed source would",
        "  instead need the commercial licence from Riverbank.",
        "* The Qt libraries those wheels carry (PyQt5-Qt5, PyQtWebEngine-Qt5) are",
        "  used under the LGPL option.  They are installed as separate DLLs beside",
        "  the executable rather than linked into it, which is the arrangement the",
        "  LGPL asks for.",
        "* PyMuPDF is AGPL-3.0, but only tools/build_manual.py uses it, to add the",
        "  manual's contents links and bookmarks.  It is a build tool and is not",
        "  part of the distributed executable.",
        "* PyInstaller is GPL-2.0-or-later with the Bootloader exception, which is",
        "  what allows a GPL build tool to package a program under other terms.",
        "",
        "*" * 78,
        "-" * 78,
        "THIRD-PARTY COMPONENTS",
        "-" * 78,
        "",
        "The texts below were copied from the files installed alongside each",
        "component on the build machine, not retyped.  MIT, BSD, Apache-2.0, PSF",
        "and LGPL all require their licence text to accompany the binaries, which",
        "is why this file must be distributed with BlueBird.exe.  Regenerate it",
        "with tools/make_notices.py after changing requirements.txt.",
        "",
        "*" * 78,
        "=" * 78,
        "COMPONENTS",
        "=" * 78,
        "",
    ]
    for title, rows in groups:
        if not rows:
            continue
        lines.append(title)
        lines.append(THIN)
        for name in rows:
            lines.append("  %-28s %s" % (name, licence_of(name) or "see upstream"))
        lines.append("")

    lines.extend([RULE, "LICENCE TEXTS", RULE, ""])
    for entry in texts.values():
        if entry["in_license"]:
            lines.append(THIN)
            lines.append("Used by: %s" % ", ".join(sorted(entry["names"])))
            lines.append(THIN)
            lines.append("")
            lines.append("This is the GNU General Public License version 3, which")
            lines.append("is the licence of BlueBird itself.  Its full text is in")
            lines.append("LICENSE beside this file and is not repeated here.")
            lines.append("")
            continue
        lines.append(THIN)
        lines.append("Used by: %s" % ", ".join(sorted(entry["names"])))
        lines.append(THIN)
        lines.append("")
        lines.append(entry["text"])
        lines.append("")

    lines.extend([RULE,
                  "COMPONENTS WHOSE WHEEL SHIPS NO LICENCE FILE",
                  RULE, ""])
    for name in without:
        lines.append("  %-28s %s" % (name, licence_of(name) or "see upstream"))
    lines.append("")
    lines.append("Their licence text is available from the project page, or from")
    lines.append("https://spdx.org/licenses/ under the identifier shown above.")
    lines.append("")

    payload = "\n".join(lines)
    if report_only:
        print()
        print("report only; would write %d bytes" % len(payload.encode("utf-8")))
        return 0

    target = os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt")
    io.open(target, "w", encoding="utf-8", newline="\n").write(payload)
    print()
    print("wrote %s (%d bytes, %d lines)"
          % (target, len(payload.encode("utf-8")), payload.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
