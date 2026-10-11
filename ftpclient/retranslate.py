"""Small helper that keeps track of the widgets needing retranslation.

Each view registers a zero-argument callback that re-applies its texts.  When
:data:`ftpclient.i18n.i18n` emits ``changed`` every registered callback runs
again, which is what makes the language switch take effect immediately.
"""

from __future__ import annotations

from typing import Any, Callable, List

if __name__ == "__main__" and not __package__:
    # Started directly: right-clicking this file in an IDE, or running
    # `python ftpclient/retranslate.py`.  Every module in this package uses relative
    # imports, which cannot work that way, and the resulting "attempted
    # relative import with no known parent package" says nothing useful.
    # Re-run the file as the module it is, from the project root.
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    sys.stderr.write("Starting retranslate.py directly; running it as "
                     "'python -m ftpclient.retranslate' instead.\n")
    runpy.run_module("ftpclient.retranslate", run_name="__main__", alter_sys=True)
    # A library module has no main block, so nothing above ran.  Say so rather
    # than exiting silently.  Start the application with run.py.
    sys.stderr.write("  (ftpclient.retranslate has no main entry point; "
                     "start the client with run.py)\n")
    raise SystemExit(0)
from .i18n import T, i18n


class Retranslator(object):
    """A list of callbacks to run whenever the language changes."""

    def __init__(self) -> None:
        self._callbacks: List[Callable[[], Any]] = []
        self._connected = False

    def bind(self, callback: Callable[[], Any]) -> Callable[[], Any]:
        self._callbacks.append(callback)
        if not self._connected:
            i18n.changed.connect(self.retranslate)
            self._connected = True
        return callback

    def retranslate(self) -> None:
        for callback in list(self._callbacks):
            try:
                callback()
            except RuntimeError:
                # the C++ object behind a widget is already gone
                self._callbacks.remove(callback)
            except Exception:
                continue

    def clear(self) -> None:
        self._callbacks = []


def set_text(widget: Any, english: str) -> None:
    """Set a widget's text from an English key, tolerating deleted widgets."""
    try:
        widget.setText(T(english))
    except RuntimeError:
        pass


def set_tip(widget: Any, english: str) -> None:
    try:
        widget.setToolTip(T(english))
    except RuntimeError:
        pass


__all__ = ["Retranslator", "set_text", "set_tip"]
