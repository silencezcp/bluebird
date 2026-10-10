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
import sys
from typing import Dict, List, Set, Tuple

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
    # also starts from the explicitly invoked tools (PyInstaller).
    lower_runtime = {name.lower() for name in runtime}
    test_extra = {name for name in closure(tests)
                  if name.lower() not in lower_runtime}
    build_roots = (tools | BUILD_ROOTS) - app - tests
    build_extra = {name for name in closure(build_roots)
                   if name.lower() not in lower_runtime
                   and name.lower() not in {n.lower() for n in test_extra}}

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
            print("   %-28s %s" % (name, version))
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


def write_requirements(groups, installed) -> None:
    """Rewrite requirements.txt (ASCII only - see the note below)."""
    lines: List[str] = [
        "# " + "=" * 73,
        "#  Smart FTP - complete dependency list (exported from the real "
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
            lines.append("%s==%s" % (name, version))
        lines.append("")

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
