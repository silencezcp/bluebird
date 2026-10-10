#!/usr/bin/env python
"""Regenerate / audit requirements.txt against the live environment.

Reads the installed distribution metadata (``importlib.metadata``) instead of
trusting a hand-written list, and reports four groups:

* RUNTIME   - what the client needs to run (direct imports + their transitive
              dependencies, excluding every extra-gated dev tool)
* TEST      - only needed by the test suite
* BUILD     - only needed to produce the exe
* unaccounted - installed but not required by any of the above

Every pin is taken from the environment, so the output can be pasted straight
into ``requirements.txt``.

    D:\\DSH_Workspaces\\Ftp\\python.exe tools\\deps_report.py
    D:\\DSH_Workspaces\\Ftp\\python.exe tools\\deps_report.py --write
"""

from __future__ import annotations

import ast
import io
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

from importlib_metadata import distribution, distributions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: importable module (or module prefix) -> the distribution providing it
MODULE_TO_DISTRIBUTION = {
    "PyQt5": "PyQt5",
    "PyQt5.QtSvg": "PyQt5",
    "PyQt5.QtPrintSupport": "PyQt5",
    "PyQt5.QtWebEngineWidgets": "PyQtWebEngine",
    "PyQt5.QtWebEngineCore": "PyQtWebEngine",
    "paramiko": "paramiko",
    "pyftpdlib": "pyftpdlib",
    "PyInstaller": "pyinstaller",
    "nacl": "PyNaCl",
    "bcrypt": "bcrypt",
    "cryptography": "cryptography",
    "cffi": "cffi",
    "pycparser": "pycparser",
    "win32ctypes": "pywin32-ctypes",
}

#: sibling distributions that ship no importable module of their own
IMPLICIT_REQUIRES = {
    "PyQt5": ("PyQt5-sip", "PyQt5-Qt5"),
    "PyQtWebEngine": ("PyQtWebEngine-Qt5",),
}

#: distributions that are only *invoked* (never imported), so the import scan
#: cannot discover them: build_exe.cmd runs "python -m PyInstaller ..."
BUILD_ROOTS = {
    "pyinstaller",
}

#: Tools run by tools/build_manual.py.  They are imported inside a function
#: there, so the static import scan of the package does not see them.
MANUAL_ROOTS = {
    "fonttools",
    "pymupdf",
}

#: Optional dependencies that nothing declares, but that our build needs.
#: fontTools writes WOFF2 subsets only when brotli is importable; without it the
#: fonts fall back to WOFF and the manual is a little larger, so the pin is
#: worth carrying.
EXTRA_BUILD_PINS = {
    "brotli",
}

#: where each requirement came from, for the comments in the generated file
NOTES = {
    "PyQt5": "the GUI framework",
    "PyQt5-sip": "binding layer between Python and Qt",
    "PyQt5-Qt5": "the Qt5 runtime shipped with the wheel (PyQt5 needs it)",
    "PyQtWebEngine": "renders Help > User manual inside the application",
    "PyQtWebEngine-Qt5": "its matching QtWebEngine runtime",
    "paramiko": "the SFTP (SSH) implementation",
    "cryptography": "low level crypto (AES / RSA / ECDSA / TLS); FTPS too",
    "PyNaCl": "Ed25519 signing - paramiko imports it unconditionally, so "
              "without it every ssh-ed25519 key stops working",
    "bcrypt": "reads passphrase-protected OpenSSH private keys",
    "cffi": "C bindings used by cryptography and PyNaCl",
    "pycparser": "C parser used by cffi",
    "typing-extensions": "cryptography needs it for type hints on Python 3.8",
    "pyftpdlib": "only used by tests/test_ftp_roundtrip.py (in-process server)",
    "pyinstaller": "builds the exe; 6.x dropped Python 3.8 so this stays 5.13.2",
    "pyinstaller-hooks-contrib": "PyInstaller hooks",
    "altgraph": "PyInstaller dependency",
    "fonttools": "subsets the manual's fonts; without it the PDF embeds whole "
                 "font files and grows from 5 MB to 37 MB",
    "brotli": "fontTools needs it to write WOFF2 font subsets",
    "pymupdf": "adds the clickable table of contents and the bookmark outline "
               "to the printed PDF (QtWebEngine writes none)",
    "pefile": "PyInstaller dependency",
    "pywin32-ctypes": "PyInstaller dependency",
    "importlib_metadata": "PyInstaller dependency",
    "zipp": "importlib_metadata dependency",
    "packaging": "PyInstaller dependency",
    "setuptools": "PyInstaller dependency",
}


def module_imports(paths: List[str]) -> Set[str]:
    found: Set[str] = set()
    for base in paths:
        for directory, _dirs, files in os.walk(base):
            if "__pycache__" in directory:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(directory, name)
                try:
                    tree = ast.parse(io.open(path, encoding="utf-8").read())
                except (SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            found.add(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.level == 0 and node.module:
                            found.add(node.module)
    return found


def resolve(modules: Set[str]) -> Set[str]:
    """Map imported module names onto the distributions that provide them.

    The longest matching prefix wins, otherwise ``PyQt5.QtWebEngineWidgets``
    would match the plain ``PyQt5`` entry first and PyQtWebEngine would be
    silently lost from the list.
    """
    ordered = sorted(MODULE_TO_DISTRIBUTION.items(),
                     key=lambda item: -len(item[0]))
    result: Set[str] = set()
    for module in modules:
        for prefix, dist in ordered:
            if module == prefix or module.startswith(prefix + "."):
                result.add(dist)
                break
    return result


def runtime_requires(name: str) -> Set[str]:
    """Requirements with no ``extra`` marker (dev tools are skipped)."""
    try:
        dist = distribution(name)
    except Exception:
        return set()
    result: Set[str] = set()
    for item in (dist.requires or []):
        if "extra ==" in item:
            continue
        token = item.split(";")[0].strip()
        for separator in ("[", " ", "=", "<", ">", "!", "~", "("):
            if separator in token:
                token = token.split(separator)[0]
        token = token.strip()
        if token:
            result.add(token)
    return result


def closure(roots: Set[str]) -> Set[str]:
    seen: Set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name.lower() in {s.lower() for s in seen}:
            continue
        seen.add(name)
        stack.extend(runtime_requires(name))
    return seen


def canonical(name: str) -> str:
    """Resolve a requirement name to the distribution actually installed.

    Requirements use a normalised spelling (``PyQt5-sip``, ``typing-extensions``)
    while the installed metadata may keep another (``PyQt5_sip``,
    ``typing_extensions``), so both are probed.
    """
    for candidate in (name, name.replace("-", "_"), name.replace("_", "-"),
                      name.replace("-", "").replace("_", "")):
        try:
            return distribution(candidate).metadata["Name"]
        except Exception:
            continue
    return name


def version_of(name: str) -> str:
    for candidate in (name, name.replace("-", "_"), name.replace("_", "-")):
        try:
            return distribution(candidate).version
        except Exception:
            continue
    return ""


def main() -> int:
    app = resolve(module_imports([os.path.join(ROOT, "ftpclient")]))
    tests = resolve(module_imports([os.path.join(ROOT, "tests")]))
    tools = resolve(module_imports([os.path.join(ROOT, "tools")]))

    # RUNTIME is the direct roots plus their transitive closure.  The roots must
    # survive: PyQtWebEngine, for instance, is declared by us, not pulled in by
    # PyQt5, so dropping it silently would break the manual viewer.
    runtime = closure(app)
    runtime |= set(app)
    for name in list(runtime):
        runtime.update(IMPLICIT_REQUIRES.get(name, ()))

    # TEST and BUILD add whatever is not already part of the runtime.  BUILD
    # also starts from the explicitly invoked tools (PyInstaller); the manual
    # tools are imported from inside a function, so they are named explicitly
    # rather than found by the scan.
    lower_runtime = {name.lower() for name in runtime}
    test_extra = {name for name in closure(tests)
                  if name.lower() not in lower_runtime}
    build_roots = (tools | BUILD_ROOTS | MANUAL_ROOTS) - app - tests
    build_extra = {name for name in closure(build_roots)
                   if name.lower() not in lower_runtime
                   and name.lower() not in {n.lower() for n in test_extra}}
    build_extra |= EXTRA_BUILD_PINS

    def pins(names: Set[str]) -> List[Tuple[str, str]]:
        rows = []
        for name in sorted(names, key=str.lower):
            version = version_of(name)
            if version:
                rows.append((canonical(name), version))
        return sorted(set(rows), key=lambda item: item[0].lower())

    groups = [("RUNTIME", pins(runtime)),
              ("TEST", pins(test_extra)),
              ("BUILD", pins(build_extra))]

    for title, rows in groups:
        print("=== %s ===" % title)
        for name, version in rows:
            print("   %-28s %-14s %s"
                  % (name, version, LICENSES.get(name, "(unrecorded)")))
        print()

    every = [name for _title, rows in groups for name, _version in rows]
    print("=== licence check ===")
    problems = check_licenses_rows(every)
    if problems:
        for line in problems:
            print("   ! %s" % line)
        print("   %d entr(ies) to check" % len(problems))
    else:
        print("   all %d entries agree with the installed metadata" % len(every))
    print()

    installed = {d.metadata["Name"]: d.version for d in distributions()
                 if d.metadata["Name"]}
    accounted = {n.lower() for _t, rows in groups for n, _v in rows}
    accounted |= {"pip", "setuptools", "wheel"}
    loose = [n for n in sorted(installed, key=str.lower)
             if n.lower() not in accounted]
    if loose:
        print("=== installed but not required ===")
        for name in loose:
            print("   %-28s %s" % (name, installed[name]))

    if "--write" in sys.argv:
        write_requirements(groups, installed)
    return 0


#: SPDX identifiers for the licences that ship with this application.  Blank
#: values mean the distribution does not declare one in any metadata field; the
#: audit prints those rather than inventing an answer.
LICENSES = {
    # runtime
    "PyQt5": "GPL-3.0-only",
    "PyQt5-sip": "SIP",
    "PyQt5-Qt5": "LGPL-3.0-only",
    "PyQtWebEngine": "GPL-3.0-only",
    "PyQtWebEngine-Qt5": "LGPL-3.0-only",
    "paramiko": "LGPL-2.1-or-later",
    "cryptography": "Apache-2.0 OR BSD-3-Clause",
    "PyNaCl": "Apache-2.0",
    "bcrypt": "Apache-2.0",
    "cffi": "MIT",
    "pycparser": "BSD-3-Clause",
    "typing-extensions": "PSF-2.0",
    # tests
    "pyftpdlib": "MIT",
    # build
    "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception",
    "pyinstaller-hooks-contrib": "Apache-2.0 OR GPL-2.0-or-later",
    "altgraph": "MIT",
    "pefile": "MIT",
    "pywin32-ctypes": "BSD-3-Clause",
    "setuptools": "MIT",
    "packaging": "Apache-2.0 OR BSD-2-Clause",
    "importlib_metadata": "Apache-2.0",
    "zipp": "MIT",
    # documentation toolchain: used to build the manual, not shipped in the exe
    "fonttools": "MIT",
    "brotli": "MIT",
    "PyMuPDF": "AGPL-3.0-only",
}

#: licences worth a word of explanation in the generated file
LICENSE_NOTES = {
    "PyQt5": "GPL-3.0 or a commercial licence from Riverbank.  Distributing "
             "the exe under the GPL is what makes this compliant; a closed "
             "source build needs the commercial licence.",
    "PyQt5-Qt5": "the Qt libraries themselves, used under the LGPL option.  "
                 "They are shipped as separate DLLs (dynamic linking), which "
                 "is the condition the LGPL attaches.",
    "PyQtWebEngine": "same terms as PyQt5",
    "PyQtWebEngine-Qt5": "same terms as PyQt5-Qt5",
    "PyMuPDF": "AGPL-3.0.  Used only by tools/build_manual.py to add the "
               "manual's table of contents links and bookmarks, so it is a "
               "build tool and is not part of the distributed exe.",
    "pyinstaller": "the bootloader exception is what lets a GPL-2.0 build "
                   "tool package a program under other terms.",
    "SIP": "",
}


#: Licence families, most specific first, each with a version pattern.  Free
#: text metadata ("GNU AFFERO GPL 3.0", "Apache Software License") is matched
#: against these rather than being stripped down blindly, which mangled both
#: "GPLv2" and "2.0".
_LICENCE_PATTERNS = (
    ("agpl", r"affero|agpl", (0, 3)),
    ("lgpl", r"lgpl|lesser general public|library or lesser", (2, 1)),
    ("gpl", r"gpl|gnu general public", (2, 0)),
    ("apache", r"apache", (2, 0)),
    ("bsd", r"bsd", (3, 0)),
    ("mit", r"\bmit\b", (0, 0)),
    ("psf", r"psf|python software foundation", (2, 0)),
    ("mpl", r"mozilla public|mpl", (2, 0)),
    ("isc", r"\bisc\b", (0, 0)),
    ("zlib", r"zlib", (0, 0)),
    ("sip", r"^sip\b|sip license", (0, 0)),
    ("unlicense", r"unlicense", (0, 0)),
)


def _normalise(text: str) -> str:
    """Reduce a licence name to a comparable key, or '' when unrecognised.

    Recognising a family and its version is what makes "GPL v3" and
    "GPL-3.0-only" compare equal without also making "GPLv2" equal to them.
    """
    lowered = text.lower()
    # the family, then the major.minor version seen next to it
    for family, pattern, default in _LICENCE_PATTERNS:
        if not re.search(pattern, lowered):
            continue
        # only a real version counts: "2.0", "v3", "version 2.1".  A bare digit
        # is not enough, because "PyQt5" and "GPLv2 (GPLv2)" otherwise supply
        # the wrong number.
        version = (re.search(r"(?:v|version[\s-]*)(\d+)(?:[.\s-](\d+))?", lowered)
                   or re.search(r"\b(\d+)\.(\d+)", lowered))
        if version:
            major = int(version.group(1))
            minor = int(version.group(2) or 0)
        else:
            major, minor = default
        if family in ("mit", "isc", "zlib", "unlicense", "sip"):
            return family
        if family == "bsd":
            # BSD is told apart by its clause count, not its version
            if "2" in lowered and "clause" in lowered:
                return "bsd2clause"
            if "3" in lowered and "clause" in lowered:
                return "bsd3clause"
            return "bsd"
        return "%s%d%d" % (family, major, minor)
    return ""


def declared_license(name: str) -> Tuple[str, str]:
    """What the installed distribution says: (text, where it came from)."""
    try:
        meta = distribution(name).metadata
    except Exception:
        return "", ""
    for field in ("License-Expression", "License"):
        value = (meta.get(field) or "").strip()
        if value and len(value) < 120:
            return value, field
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip(), "Classifier"
    # a licence file inside the wheel is the last resort
    try:
        files = distribution(name).files or []
    except Exception:
        files = []
    for entry in files:
        base = os.path.basename(str(entry))
        if "licen" in base.lower() or base.upper().startswith("COPYING"):
            return base, "licence file"
    return "", ""


def check_licenses(names: "List[str]") -> "List[str]":
    """Compare the table above with the metadata.  Returns complaints."""
    problems = []
    for name in names:
        expected = licence_of(name)
        if expected is None:
            problems.append("%s: no licence recorded in LICENSES" % name)
            continue
        if not expected:
            continue                      # deliberately blank
        declared, source = declared_license(name)
        if not declared:
            problems.append("%s: declares no licence (%s expected)"
                            % (name, expected))
            continue
        if source == "licence file":
            # a licence file is present but no field names the licence, so
            # there is nothing to compare against
            continue
        # SPDX "A OR B" expressions are satisfied by either half
        halves = [part.strip() for part in expected.replace(" OR ", "|")
                  .replace(" AND ", "|").split("|")]
        if any(_normalise(part) and _normalise(part) in _normalise(declared)
               for part in halves):
            continue
        problems.append("%s: table says %s, metadata says %r (%s)"
                        % (name, expected, declared, source))
    return problems


def _licence_key(name: str) -> str:
    """The LICENSES key for a distribution name.

    Wheel names are inconsistent - PyQt5_sip, typing_extensions - so the table
    is keyed on a normalised form.
    """
    return name.strip().lower().replace("_", "-")


#: LICENSES keyed by the normalised distribution name, built once
_LICENCE_INDEX: Dict[str, str] = {}


def licence_of(name: str) -> "Optional[str]":
    """The recorded licence for a distribution, or None when unrecorded."""
    if not _LICENCE_INDEX:
        for key, value in LICENSES.items():
            _LICENCE_INDEX[_licence_key(key)] = value
    return _LICENCE_INDEX.get(_licence_key(name))


def check_licenses_rows(rows: "List") -> "List[str]":
    """check_licenses over (name, version) rows."""
    return check_licenses(list(rows))


def licence_summary(groups) -> "List[str]":
    """A closing section that names the licences and the obligations."""
    lines = [
        "# " + "=" * 73,
        "#  LICENCES",
        "# " + "=" * 73,
        "#  Read from each distribution's own metadata (License-Expression, "
        "License",
        "#  or the OSI classifier); run tools/deps_report.py to re-check them.",
        "#",
    ]
    for title, rows in groups:
        if not rows:
            continue
        lines.append("#  %s" % title)
        for name, _version in rows:
            lines.append("#      %-26s %s"
                         % (name, licence_of(name) or "not recorded"))
        lines.append("#")
    lines.append("#  What this means for distributing BlueBird.exe")
    lines.append("#")
    for name in ("PyQt5", "PyQt5-Qt5", "PyMuPDF", "pyinstaller"):
        note = LICENSE_NOTES.get(name)
        if note:
            lines.append("#  * %s" % name)
            for chunk in _wrap(note, 68):
                lines.append("#      %s" % chunk)
    lines.append("#  * everything else is MIT, BSD, Apache-2.0, PSF or "
                 "LGPL, all of which")
    lines.append("#      only require the licence text to travel with the "
                 "binaries.")
    lines.append("# " + "=" * 73)
    return lines


def _wrap(text: str, width: int) -> "List[str]":
    """Break a sentence into lines, so the output stays readable."""
    words = text.split()
    out: List[str] = []
    line = ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
            continue
        line = ("%s %s" % (line, word)).strip()
    if line:
        out.append(line)
    return out


def write_requirements(groups, installed) -> None:
    """Rewrite requirements.txt (ASCII only - see the note below)."""
    lines: List[str] = [
        "# " + "=" * 73,
        "#  BlueBird - complete dependency list (exported from the real "
        "environment)",
        "# " + "=" * 73,
        "#  Environment : Python %s on Windows" % sys.version.split()[0],
        "#  Generated by: tools/deps_report.py --write  (reads importlib"
        ".metadata)",
        "#",
        "#  NOTE: this file is deliberately ASCII-only.  pip reads a "
        "requirements file",
        "#  using the ANSI code page on Windows (GBK on a Chinese system), so "
        "non-ASCII",
        "#  comments make `pip install -r requirements.txt` fail with",
        "#  UnicodeDecodeError.",
        "#",
        "#  Install everything (runtime + tests + packaging):",
        "#      python -m pip install -r requirements.txt",
        "# " + "=" * 73,
        "",
    ]
    titles = {"RUNTIME": "required to run the client",
              "TEST": "only needed by the test suite",
              "BUILD": "only needed to produce the exe"}
    for title, rows in groups:
        if not rows:
            continue
        lines.append("# " + "-" * 73)
        lines.append("# %s - %s" % (title, titles.get(title, "")))
        lines.append("# " + "-" * 73)
        for name, version in rows:
            note = NOTES.get(name)
            if note:
                lines.append("#   %-20s %s" % (name, note))
            lines.append("#   %-20s %s" % ("", "licence: %s"
                                           % LICENSES.get(name, "not recorded")))
            lines.append("%s==%s" % (name, version))
        lines.append("")

    lines.extend(licence_summary(groups))

    target = os.path.join(ROOT, "requirements.txt")
    payload = "\n".join(lines)
    if not payload.isascii():
        print("refusing to write: the generated file is not ASCII-only")
        return
    with io.open(target, "w", encoding="ascii", newline="\n") as handle:
        handle.write(payload)
    print("wrote %s (%d bytes)" % (target, os.path.getsize(target)))


if __name__ == "__main__":
    sys.exit(main())
