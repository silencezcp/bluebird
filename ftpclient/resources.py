"""Where do bundled files live at runtime?

Two situations have to be told apart:

* running from source - the resources sit next to the package;
* inside a PyInstaller build - ``sys.frozen`` is set, and the data has been
  unpacked into ``sys._MEIPASS`` for a one-file build.

This module is the single place that knows the difference.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional


def is_frozen() -> bool:
    """True when running from a packaged executable."""
    return bool(getattr(sys, "frozen", False))


def executable_dir() -> str:
    """The folder holding the program the user launched."""
    return os.path.dirname(os.path.abspath(sys.executable))


def bundle_root() -> str:
    """Where the bundled *data* was placed at build time.

    PyInstaller unpacks a one-file build into ``_MEIPASS``; the one-folder
    build used here puts the data beside the executable, which is what the
    fallback covers.
    """
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
    "is_frozen", "executable_dir", "bundle_root", "resource_root",
    "resource_path", "find_resource",
    "MANUAL_HTML", "MANUAL_MD", "MANUAL_PDF",
]
