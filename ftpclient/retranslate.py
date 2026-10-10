"""Small helper that keeps track of the widgets needing retranslation.

Each view registers a zero-argument callback that re-applies its texts.  When
:data:`ftpclient.i18n.i18n` emits ``changed`` every registered callback runs
again, which is what makes the language switch take effect immediately.
"""

from __future__ import annotations

from typing import Any, Callable, List

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
