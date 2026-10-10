"""Small runtime helpers shared by the GUI and the command line client."""

from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

#: Third party dependency chatter that says nothing about this program.
#:
#: ``CryptographyDeprecationWarning`` is a plain ``UserWarning`` subclass, so
#: filtering by category would need cryptography imported first - which is
#: exactly when the message is printed.  The text is the reliable handle.
NOISE_PATTERNS = (
    "Python 3.8 is no longer supported by the Python core team",
    "the next release of cryptography will remove support",
    "pkg_resources is deprecated as an API",
    "datetime.datetime.utcnow() is deprecated",
)

_installed = False


def silence_dependency_noise(force: bool = False) -> bool:
    """Stop our dependencies from printing deprecation chatter.

    Called before anything imports ``cryptography`` (which paramiko does), so
    the message never reaches the console or the packaged executable's output.

    Returns True when the filters were installed now, False when they already
    were, so callers can log it once.
    """
    global _installed
    if _installed and not force:
        return False
    try:
        import warnings

        for pattern in NOISE_PATTERNS:
            warnings.filterwarnings("ignore", message=pattern, category=Warning)

        # cryptography's own class, once the module exists, so the filter also
        # covers messages that do not match one of the patterns above
        try:
            from cryptography.utils import CryptographyDeprecationWarning
            warnings.filterwarnings("ignore",
                                    category=CryptographyDeprecationWarning)
        except Exception:                       # pragma: no cover
            pass
    except Exception:                           # pragma: no cover
        return False
    _installed = True
    return True


# ---------------------------------------------------------------------------
# console behaviour for the packaged command line client
# ---------------------------------------------------------------------------
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def eprint(*parts: Any) -> None:
    """Print to stderr, tolerating a detached or missing stream."""
    try:
        sys.stderr.write(" ".join(str(part) for part in parts) + "\n")
        sys.stderr.flush()
    except Exception:                           # pragma: no cover
        pass


def pause_if_launched_by_double_click(args: Optional[List[str]] = None,
                                      failed: bool = False,
                                      force: Optional[bool] = None) -> bool:
    """Keep the console window open when nobody could read it anyway.

    A console program started from Explorer gets a fresh window that closes the
    instant the process ends, so a typed command and any error message flash
    past unseen.  When that happens the program waits for a key press.

    Only the packaged executable pauses: a script calling it, a pipe, or a
    redirect is never blocked, because stdin is not a terminal in those cases.
    ``--no-pause`` turns it off, and ``force`` overrides the console check so
    the behaviour can be tested from a terminal.
    """
    items = list(args or [])
    if "--no-pause" in items:
        return False
    if force is None:
        if os.name != "nt" or not is_frozen():
            return False
        if not sys.stdin or not sys.stdout:
            return False
        try:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                return False
        except (ValueError, AttributeError):
            return False
    elif not force:
        return False

    commands = [item for item in items if not item.startswith("-")]
    if commands and not failed:
        return False

    try:
        eprint("")
        if commands or failed:
            eprint("Press Enter to close this window...")
        else:
            eprint("Press Enter to close this window, or open a command prompt")
            eprint("in this folder first - then the output stays on screen.")
        sys.stdin.readline()
    except Exception:                           # pragma: no cover
        pass
    return True
