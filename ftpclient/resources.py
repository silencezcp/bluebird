"""Where do bundled files live at runtime?

Three situations have to be told apart:

* running from source - the resources sit next to the package;
* a PyInstaller one-file build - they are unpacked into ``sys._MEIPASS``;
* a Nuitka standalone build - no such variable exists, and ``sys.executable``
  points at the *bundled copy of python.exe* rather than the program, so the
  directory has to come from ``sys.argv[0]``.

This module is the single place that knows the difference.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

#: Nuitka injects this into every compiled module; PyInstaller sets sys.frozen
COMPILED = "__compiled__"


def is_nuitka() -> bool:
    """True inside a Nuitka-compiled module."""
    return COMPILED in globals()


def is_pyinstaller() -> bool:
    """True inside a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False)) and not is_nuitka()


def is_frozen() -> bool:
    """True when running from a packaged executable, by either builder."""
    return is_nuitka() or bool(getattr(sys, "frozen", False))


def executable_dir() -> str:
    """The folder holding the program the user launched.

    ``sys.executable`` is only right under PyInstaller.  A Nuitka standalone
    build ships a copy of ``python.exe`` beside the program and points
    ``sys.executable`` at it, which happens to be the same directory - but it is
    spelled with short 8.3 path components there, so ``sys.argv[0]`` is used
    first for a clean, fully resolved path.
    """
    if is_nuitka():
        candidate = ""
        if sys.argv and sys.argv[0]:
            candidate = sys.argv[0]
        if candidate.endswith(".py") or not candidate:
            candidate = sys.executable
        return os.path.dirname(os.path.abspath(candidate))
    return os.path.dirname(os.path.abspath(sys.executable))


def bundle_root() -> str:
    """Where the bundled *data* was placed at build time.

    PyInstaller unpacks into ``_MEIPASS``.  Nuitka copies the data next to the
    program, so this is the same as :func:`executable_dir` there.
    """
    if is_nuitka():
        return executable_dir()
    return getattr(sys, "_MEIPASS", executable_dir())


def resource_root() -> str:
    """The directory that contains ``ftpclient/`` and ``docs/``."""
    if is_frozen():
        return bundle_root()
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """Absolute path to a bundled resource."""
    return os.path.join(resource_root(), *parts)


def find_resource(*parts: str, required: bool = True) -> Optional[str]:
    """Return the first existing candidate for a resource, or None.

    Besides the bundled location the folder next to the executable is checked,
    so a user can drop an updated manual beside the .exe without rebuilding.
    """
    candidates: List[str] = [os.path.join(resource_root(), *parts)]
    if is_frozen():
        candidates.append(os.path.join(executable_dir(), *parts))
        candidates.append(os.path.join(
            os.path.dirname(executable_dir()), *parts))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None if required else None


#: The documentation shipped with the application.  Only the user manual is
#: bundled; docs/开发手册.* stays in the repository, since it covers the source
#: tree, the dependencies and the build.
MANUAL_HTML = ("docs", "\u7528\u6237\u624b\u518c.html")
MANUAL_MD = ("docs", "\u7528\u6237\u624b\u518c.md")
MANUAL_PDF = ("docs", "\u7528\u6237\u624b\u518c.pdf")

__all__ = [
    "is_frozen", "is_nuitka", "is_pyinstaller", "executable_dir",
    "bundle_root", "resource_root", "resource_path", "find_resource",
    "MANUAL_HTML", "MANUAL_MD", "MANUAL_PDF",
]
