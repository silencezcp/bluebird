"""Where do bundled files live at runtime?

Running from source the resources sit next to the package; inside a
PyInstaller one-file build they are unpacked into ``sys._MEIPASS``.  This
module is the single place that knows the difference.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional


def is_frozen() -> bool:
    """True when running from a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> str:
    """The directory that contains ``ftpclient/`` and ``docs/``."""
    if is_frozen():
        # PyInstaller sets _MEIPASS to the unpacked bundle directory
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
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
        candidates.append(os.path.join(os.path.dirname(sys.executable), *parts))
        candidates.append(os.path.join(
            os.path.dirname(os.path.dirname(sys.executable)), *parts))
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
    "is_frozen", "resource_root", "resource_path", "find_resource",
    "MANUAL_HTML", "MANUAL_MD", "MANUAL_PDF",
]
