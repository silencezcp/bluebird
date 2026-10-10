"""Plain data types shared by the GUI and the command line client.

Nothing here imports Qt, so the command line client runs on a machine without
PyQt5.  The Qt table models stay in :mod:`ftpclient.models`, which re-exports
these names so existing imports keep working.
"""

from __future__ import annotations

import os
import posixpath
import stat
import time
from itertools import count
from typing import Any, Dict, List, Optional, Tuple

#: Qt.UserRole is 0x0100; spelled out so these names exist without PyQt5.
_USER_ROLE = 0x0100

FILE_COLUMNS: List[Tuple[str, str]] = [
    ("name", "Name"),
    ("size", "Size"),
    ("type", "Type"),
    ("modified", "Modified"),
    ("permissions", "Permissions"),
    ("owner", "Owner"),
]


def format_size(size: Optional[int]) -> str:
    """Human readable size with an automatic unit (B / KB / MB / GB / TB / PB)."""
    if size is None:
        return ""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return "%d B" % int(value)
    if value >= 100.0:
        return "%.0f %s" % (value, units[index])
    return "%.1f %s" % (value, units[index])


def parse_size(text: str) -> Optional[int]:
    """Parse strings such as ``1.5 MB`` / ``2048`` / ``-`` into a byte count."""
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "")
    if not cleaned or cleaned in ("-", "--", "?"):
        return None
    units = {"b": 1, "k": 1024, "kb": 1024, "kib": 1024, "m": 1024 ** 2,
             "mb": 1024 ** 2, "mib": 1024 ** 2, "g": 1024 ** 3,
             "gb": 1024 ** 3, "gib": 1024 ** 3, "t": 1024 ** 4,
             "tb": 1024 ** 4, "tib": 1024 ** 4}
    number = ""
    suffix = ""
    for char in cleaned:
        if char.isdigit() or char == ".":
            if suffix:
                return None
            number += char
        elif char.isalpha():
            suffix += char.lower()
        elif char in " \t":
            continue
        else:
            return None
    if not number:
        return None
    try:
        value = float(number)
    except ValueError:
        return None
    return int(value * units.get(suffix, 1))


def format_time(timestamp: Optional[float], with_seconds: bool = True) -> str:
    if not timestamp:
        return ""
    try:
        struct = time.localtime(timestamp)
    except (ValueError, OSError):
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M",
                         struct)


_NAME, _SIZE, _TYPE, _MODIFIED, _PERMISSIONS, _OWNER = range(6)

SORT_ROLE = _USER_ROLE + 1
ENTRY_ROLE = _USER_ROLE + 2
KIND_ROLE = _USER_ROLE + 3
ITEM_ID_ROLE = _USER_ROLE + 4


class Entry(object):
    """One row in a directory listing (local or remote)."""

    __slots__ = ("name", "size", "mtime", "is_dir", "is_link", "mode",
                 "permissions", "owner", "group", "link_target", "extra",
                 "is_parent")

    def __init__(self, name: str, size: Optional[int] = None,
                 mtime: Optional[float] = None, is_dir: bool = False,
                 is_link: bool = False, mode: Optional[int] = None,
                 permissions: str = "", owner: str = "", group: str = "",
                 link_target: str = "", is_parent: bool = False) -> None:
        self.name = name
        self.size = size
        self.mtime = mtime
        self.is_dir = is_dir
        self.is_link = is_link
        self.mode = mode
        self.permissions = permissions or (stat.filemode(mode) if mode else "")
        self.owner = owner
        self.group = group
        self.link_target = link_target
        self.extra: Dict[str, Any] = {}
        self.is_parent = is_parent

    # -- helpers --------------------------------------------------------
    @property
    def kind(self) -> str:
        if self.is_parent:
            return "parent"
        if self.is_dir:
            return "folder"
        if self.is_link:
            return "link"
        return "file"

    @property
    def extension(self) -> str:
        dot = self.name.rfind(".")
        if dot <= 0:
            return ""
        return self.name[dot:].lower()

    @property
    def sort_name(self) -> str:
        return self.name.lower()

    def type_label(self) -> str:
        from .i18n import T
        if self.is_parent:
            return T("Parent directory")
        if self.is_link:
            return T("Symbolic link")
        if self.is_dir:
            return T("Folder")
        extension = self.extension
        if extension:
            return T("%s file") % extension.lstrip(".").upper()
        return T("File")

    def size_value(self) -> int:
        if self.is_dir:
            return -1
        return int(self.size or 0)

    def time_value(self) -> float:
        return float(self.mtime or 0.0)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return "<Entry %s%s size=%s>" % (
            self.name, "/" if self.is_dir else "", self.size)


# ---------------------------------------------------------------------------
# File list model
# ---------------------------------------------------------------------------


class TransferItem(object):
    """A queued upload/download."""

    _ids = count(1)

    __slots__ = ("uid", "kind", "source", "target", "size", "transferred",
                 "status", "message", "speed", "started_at", "finished_at",
                 "created_at", "retries", "remote_dir", "local_dir",
                 "override_name", "is_dir", "expanded")

    def __init__(self, kind: str, source: str, target: str,
                 size: Optional[int] = None, is_dir: bool = False) -> None:
        self.uid = next(TransferItem._ids)
        self.kind = kind                 # "upload" | "download"
        self.source = source
        self.target = target
        self.size = size
        self.transferred = 0
        self.status = "queued"           # queued|active|done|error|skipped|cancel
        self.message = ""
        self.speed = 0.0
        self.started_at = 0.0
        self.finished_at = 0.0
        #: set when the item is queued, so the Time column can show something
        #: while a transfer is still waiting its turn
        self.created_at = time.time()
        self.retries = 0
        self.remote_dir = ""
        self.local_dir = ""
        self.override_name = ""
        self.is_dir = is_dir
        self.expanded = False

    @property
    def display_name(self) -> str:
        if self.is_dir:
            base = os.path.basename(self.source.rstrip("/\\")) or self.source
            return base + "/"
        return os.path.basename(self.source.rstrip("/\\")) or self.source

    @property
    def remote_name(self) -> str:
        if self.override_name:
            return self.override_name
        base = posixpath.basename(self.source.replace("\\", "/").rstrip("/"))
        return base or self.source

    def progress_percent(self) -> int:
        if self.status == "done":
            return 100
        if not self.size:
            return 0
        value = int(self.transferred * 100 / float(self.size))
        return max(0, min(100, value))

    def time_text(self) -> str:
        """Hours:minutes:seconds for the Time column.

        A queued item shows the moment it entered the queue, so the column is
        never blank; once the transfer starts the timestamp is pinned to the
        start time and stays put for the life of the row.
        """
        when = self.started_at or self.created_at
        if not when:
            return ""
        try:
            return time.strftime("%H:%M:%S", time.localtime(when))
        except (ValueError, OSError, OverflowError):
            return ""

    def kind_label(self) -> str:
        from .i18n import T
        return T("Upload →") if self.kind == "upload" else T("← Download")

    def status_label(self) -> str:
        from .i18n import T
        if self.status == "queued":
            return T("Queued")
        if self.status == "active":
            return T("Transferring")
        if self.status == "done":
            return T("Completed")
        if self.status == "error":
            return self.message or T("Failed")
        if self.status == "skipped":
            return self.message or T("Skipped")
        if self.status == "cancel":
            return T("Cancelled")
        return self.status
