"""The application log, one file per day.

Everything the log pane shows also goes to ``logs/YYYYMMDD.log``, written beside
the executable (or beside ``run.py`` when running from source).  The date comes
from the local clock, so the file changes over at local midnight even in a
session that stays open.

Logging must never be able to take the application down: every write is guarded,
and a failure is recorded once and then swallowed so the console keeps working
even when the log directory is read-only.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

#: the folder that holds the daily files
LOG_DIR_NAME = "logs"

#: how the level reads in the file; the console uses its own colours
LEVEL_TAGS = {
    "debug": "DEBUG",
    "info": "INFO",
    "success": "OK",
    "warn": "WARN",
    "warning": "WARN",
    "error": "ERROR",
}


@lru_cache(maxsize=1)
def log_directory() -> str:
    """``<base>/logs``, where base is the exe's folder or the project root.

    A one-folder build puts everything beside ``BlueBird.exe``, so that is the
    directory a user looks in.  Frozen builds must not use ``_MEIPASS``: that is
    a temporary unpack directory, and the log would vanish with it.
    """
    from .resources import is_frozen, resource_root

    if is_frozen():
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = resource_root()
    return os.path.join(base, LOG_DIR_NAME)


def log_path_for(day: Optional[datetime] = None) -> str:
    """``logs/YYYYMMDD.log`` for the given day, today by default."""
    stamp = (day or datetime.now()).strftime("%Y%m%d")
    return os.path.join(log_directory(), "%s.log" % stamp)


def date_stamp() -> str:
    """The current day as it appears in the file name."""
    return datetime.now().strftime("%Y%m%d")


class DailyLog(object):
    """Appends timestamped lines to today's file, rolling over at midnight."""

    def __init__(self, directory: Optional[str] = None) -> None:
        self._directory = directory
        self._handle: Optional[Any] = None
        self._day = ""
        self._lock = threading.RLock()
        #: set once if the log could not be written, so the UI can say so
        self.error: Optional[str] = None
        self.entries = 0

    # -- paths ----------------------------------------------------------
    @property
    def directory(self) -> str:
        return self._directory or log_directory()

    def path(self) -> str:
        """The file currently being written, whether or not it exists yet."""
        return os.path.join(self.directory, "%s.log" % (self._day or date_stamp()))

    # -- writing --------------------------------------------------------
    def _open(self, day: str) -> bool:
        """Open the handle for ``day``, creating the directory if needed."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            path = os.path.join(self.directory, "%s.log" % day)
            fresh = not os.path.exists(path)
            # line buffered so a crash still leaves the last line on disk
            self._handle = open(path, "a", encoding="utf-8", buffering=1)
            self._day = day
            if fresh:
                self._write_raw(self._header())
            self.error = None
            return True
        except OSError as exc:
            self._handle = None
            self.error = "Could not open the log file: %s" % exc
            return False

    def _header(self) -> str:
        from . import __appname__, __version__
        from .resources import is_frozen

        where = "packaged build" if is_frozen() else "running from source"
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return (
            "\n"
            + "=" * 78 + "\n"
            + "%s %s, %s\n" % (__appname__, __version__, where)
            + "log started %s\n" % started
            + "=" * 78 + "\n"
        )

    def _write_raw(self, text: str) -> None:
        if self._handle is None:
            return
        self._handle.write(text)

    def write(self, level: str, message: str) -> None:
        """Append one line.  Never raises."""
        tag = LEVEL_TAGS.get(str(level).lower(), str(level).upper() or "INFO")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = " ".join(str(message).splitlines()) or " "
        line = "%s  %-5s  %s\n" % (stamp, tag, text)
        with self._lock:
            day = date_stamp()
            if self._handle is None or day != self._day:
                if not self._open(day):
                    return
            try:
                self._write_raw(line)
                self.entries += 1
            except (OSError, ValueError) as exc:
                # the handle can go bad if the file is removed underneath us;
                # report once and stop trying rather than repeating every line
                self.error = "Could not write to the log file: %s" % exc
                try:
                    if self._handle is not None:
                        self._handle.close()
                except OSError:
                    pass
                self._handle = None

    def flush(self) -> None:
        with self._lock:
            try:
                if self._handle is not None:
                    self._handle.flush()
            except (OSError, ValueError):
                pass

    def close(self) -> None:
        with self._lock:
            try:
                if self._handle is not None:
                    self._handle.close()
            except (OSError, ValueError):
                pass
            self._handle = None

    # -- convenience ----------------------------------------------------
    def open_folder(self) -> str:
        """Create the directory if needed and return it, for the UI to reveal."""
        try:
            os.makedirs(self.directory, exist_ok=True)
        except OSError:
            pass
        return self.directory

    def prune(self, keep_days: int = 30) -> int:
        """Delete daily files older than ``keep_days``.  Returns how many went.

        Off by default: keeping every file is the safer choice, and this exists
        so a long-lived install can be tidied deliberately.
        """
        if keep_days <= 0:
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        try:
            names = os.listdir(self.directory)
        except OSError:
            return 0
        for name in names:
            if not (len(name) == 14 and name.endswith(".log")
                    and name[:8].isdigit()):
                continue
            full = os.path.join(self.directory, name)
            try:
                if os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                    os.remove(full)
                    removed += 1
            except OSError:
                continue
        return removed


#: the application-wide log, created on first use
_INSTANCE: Optional[DailyLog] = None
_INSTANCE_LOCK = threading.Lock()


def instance() -> DailyLog:
    """The shared :class:`DailyLog`."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = DailyLog()
        return _INSTANCE


def write(level: str, message: str) -> None:
    """Append to the application log."""
    instance().write(level, message)


def reset(directory: Optional[str] = None) -> DailyLog:
    """Start a new log in ``directory``; used by the tests."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is not None:
            _INSTANCE.close()
        _INSTANCE = DailyLog(directory)
        return _INSTANCE
