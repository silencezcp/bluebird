"""Qt item models for the file lists and the transfer queue."""

from __future__ import annotations

import os
import posixpath
import stat
import time
from itertools import count
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, Qt, QVariant
from PyQt5.QtGui import QFont, QIcon

from . import theme as _theme

#: Display order of the file-list columns: (key, English header).
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

_NAME, _SIZE, _TYPE, _MODIFIED, _PERMISSIONS, _OWNER = range(6)

SORT_ROLE = Qt.UserRole + 1
ENTRY_ROLE = Qt.UserRole + 2
KIND_ROLE = Qt.UserRole + 3
ITEM_ID_ROLE = Qt.UserRole + 4


class FileListModel(QAbstractTableModel):
    """A sortable, filterable directory listing."""

    def __init__(self, theme: _theme.Theme, icons: Any,
                 parent: Any = None) -> None:
        super(FileListModel, self).__init__(parent)
        self._theme = theme
        self._icons = icons
        self._entries: List[Entry] = []
        self._visible: List[Entry] = []
        self._filter = ""
        self._show_hidden = True
        self._show_parent = False
        self._sort_column = _NAME
        self._sort_order = Qt.AscendingOrder
        self._folders_first = True
        # icons, fonts and row colours all come from the palette, so the whole
        # view has to be repainted whenever the user edits a colour
        theme.changed.connect(self.refresh_theme)

    def refresh_theme(self) -> None:
        """Re-emit every row so icons/colours pick up a new palette."""
        if not self._visible:
            return
        top = self.index(0, 0)
        bottom = self.index(len(self._visible) - 1, len(FILE_COLUMNS) - 1)
        self.dataChanged.emit(top, bottom)

    def retranslate(self) -> None:
        """Column headers and type labels follow the active language."""
        if self.columnCount():
            self.headerDataChanged.emit(Qt.Horizontal, 0, self.columnCount() - 1)
        self.refresh_theme()

    # -- population -----------------------------------------------------
    def set_entries(self, entries: List[Entry], show_parent: bool = False) -> None:
        self.beginResetModel()
        self._entries = list(entries or [])
        self._show_parent = show_parent
        if show_parent:
            self._entries.insert(0, Entry("..", is_dir=True, is_parent=True))
        self._apply_view(keep_sort=True)
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._entries = []
        self._visible = []
        self.endResetModel()

    def entries(self) -> List[Entry]:
        return list(self._entries)

    def visible_entries(self) -> List[Entry]:
        return list(self._visible)

    def entry_at(self, row: int) -> Optional[Entry]:
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def index_of_name(self, name: str) -> int:
        lowered = name.lower()
        for row, entry in enumerate(self._visible):
            if entry.name.lower() == lowered:
                return row
        return -1

    # -- filtering ------------------------------------------------------
    def set_filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        if text == self._filter:
            return
        self.beginResetModel()
        self._filter = text
        self._apply_view(keep_sort=True)
        self.endResetModel()

    def set_show_hidden(self, value: bool) -> None:
        value = bool(value)
        if value == self._show_hidden:
            return
        self.beginResetModel()
        self._show_hidden = value
        self._apply_view(keep_sort=True)
        self.endResetModel()

    def _matches(self, entry: Entry) -> bool:
        if entry.is_parent:
            return True
        if not self._show_hidden and entry.name.startswith("."):
            return False
        if not self._filter:
            return True
        return self._filter in entry.name.lower()

    def _apply_view(self, keep_sort: bool = False) -> None:
        self._visible = [e for e in self._entries if self._matches(e)]
        if keep_sort:
            self._sort_visible()

    def _sort_visible(self) -> None:
        column = self._sort_column
        reverse = self._sort_order == Qt.DescendingOrder
        key = self._sort_key(column)
        parents = [e for e in self._visible if e.is_parent]
        rest = [e for e in self._visible if not e.is_parent]
        if self._folders_first and column != _SIZE:
            folders = [e for e in rest if e.is_dir]
            files = [e for e in rest if not e.is_dir]
            folders.sort(key=key, reverse=reverse)
            files.sort(key=key, reverse=reverse)
            rest = folders + files
        else:
            rest.sort(key=key, reverse=reverse)
        self._visible = parents + rest

    def _sort_key(self, column: int):
        if column == _SIZE:
            return lambda e: (1 if e.is_dir else 0, e.size_value(), e.sort_name)
        if column == _MODIFIED:
            return lambda e: (e.time_value(), e.sort_name)
        if column == _TYPE:
            return lambda e: (e.type_label().lower(), e.sort_name)
        if column == _PERMISSIONS:
            return lambda e: (e.permissions or "", e.sort_name)
        if column == _OWNER:
            return lambda e: ((e.owner or "").lower(), e.sort_name)
        return lambda e: e.sort_name

    # -- size resolution ------------------------------------------------
    def entries_without_size(self) -> List[Entry]:
        """Files whose size the server did not report in the listing."""
        return [e for e in self._visible
                if not e.is_dir and not e.is_parent and e.size is None]

    def set_entry_size(self, entry: Entry, size: Optional[int],
                       mtime: Optional[float] = None,
                       permissions: str = "") -> None:
        """Store a size discovered by a follow-up stat and repaint that row."""
        if size is None or size < 0:
            entry.size = 0 if entry.size is None and size == 0 else entry.size
        else:
            entry.size = size
        if mtime:
            entry.mtime = mtime
        if permissions and not entry.permissions:
            entry.permissions = permissions
        try:
            row = self._visible.index(entry)
        except ValueError:
            return
        left = self.index(row, 0)
        right = self.index(row, len(FILE_COLUMNS) - 1)
        self.dataChanged.emit(left, right)

    # -- QAbstractTableModel -------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._visible)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(FILE_COLUMNS)

    @staticmethod
    def column_alignment(column: int) -> int:
        """Numeric / date columns are right aligned, in header *and* cells.

        Keeping one helper means the header can never drift away from the
        values underneath it (Size and Modified used to disagree).
        """
        if column in (_SIZE, _MODIFIED):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return int(Qt.AlignLeft | Qt.AlignVCenter)

    def headerData(self, section: int, orientation: int,
                   role: int = Qt.DisplayRole) -> Any:
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            if 0 <= section < len(FILE_COLUMNS):
                from .i18n import T
                return T(FILE_COLUMNS[section][1])
            return None
        if role == Qt.TextAlignmentRole:
            return self.column_alignment(section)
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        entry = self.entry_at(index.row())
        if entry is None:
            return None
        column = index.column()
        if role == Qt.DisplayRole:
            return self._display(entry, column)
        if role == Qt.DecorationRole and column == _NAME:
            return self._icon_for(entry)
        if role == Qt.TextAlignmentRole:
            return self.column_alignment(column)
        if role == Qt.FontRole and column == _NAME:
            font = QFont()
            return self._theme.item_font(entry.kind, font)
        if role == Qt.ForegroundRole and column == _NAME:
            from PyQt5.QtGui import QBrush
            color = self._theme.qcolor(self._color_key(entry))
            return QBrush(color)
        if role == Qt.ToolTipRole:
            return self._tooltip(entry)
        if role == SORT_ROLE:
            if column == _SIZE:
                return entry.size_value()
            if column == _MODIFIED:
                return entry.time_value()
            return self._display(entry, column)
        if role == ENTRY_ROLE:
            return QVariant(entry)
        if role == KIND_ROLE:
            return entry.kind
        return None

    def _display(self, entry: Entry, column: int) -> str:
        if column == _NAME:
            if entry.is_parent:
                return ".."
            return entry.name
        if column == _SIZE:
            if entry.is_dir:
                return "<DIR>"
            if entry.size is None:
                return "…"          # server did not report it (yet)
            return format_size(entry.size)
        if column == _TYPE:
            return entry.type_label()
        if column == _MODIFIED:
            return format_time(entry.mtime)
        if column == _PERMISSIONS:
            return entry.permissions or ""
        if column == _OWNER:
            owner = entry.owner or ""
            if entry.group:
                return "%s / %s" % (owner, entry.group) if owner else entry.group
            return owner
        return ""

    def _color_key(self, entry: Entry) -> str:
        if entry.is_parent:
            return "text_muted"
        if entry.is_dir:
            return "folder"
        if entry.is_link:
            return "link"
        return "file"

    def _icon_for(self, entry: Entry) -> QIcon:
        if entry.is_parent:
            return self._icons.file_icon("folder_up", self._theme.color("folder"),
                                         "folder")
        spec = _theme.icon_spec_for(entry, self._theme)
        return self._icons.file_icon(spec.name, self._theme.color(spec.color_key),
                                     spec.kind)

    def _tooltip(self, entry: Entry) -> str:
        lines = [entry.name]
        if entry.is_parent:
            return "Parent directory"
        lines.append("Type: %s" % entry.type_label())
        if not entry.is_dir:
            if entry.size is None:
                lines.append("Size: unknown (the server did not report it)")
            else:
                lines.append("Size: %s (%s bytes)"
                             % (format_size(entry.size), entry.size))
        if entry.mtime:
            lines.append("Modified: %s" % format_time(entry.mtime))
        if entry.permissions:
            lines.append("Permissions: %s" % entry.permissions)
        if entry.owner:
            lines.append("Owner: %s" % entry.owner)
        if entry.link_target:
            lines.append("Target: %s" % entry.link_target)
        return "\n".join(lines)

    def sort(self, column: int, order: int = Qt.AscendingOrder) -> None:
        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        self._apply_view(keep_sort=True)
        self.layoutChanged.emit()

    # -- convenience ----------------------------------------------------
    def total_selected_size(self, rows: List[int]) -> int:
        total = 0
        for row in rows:
            entry = self.entry_at(row)
            if entry is not None and not entry.is_dir:
                total += entry.size_value()
        return total


# ---------------------------------------------------------------------------
# Transfer queue model
# ---------------------------------------------------------------------------

XFER_NAME, XFER_DIRECTION, XFER_SIZE, XFER_PROGRESS, XFER_SPEED, XFER_STATUS = range(6)

TRANSFER_COLUMNS: List[str] = ["File", "Direction", "Size", "Progress",
                               "Speed", "Status"]


class TransferItem(object):
    """A queued upload/download."""

    _ids = count(1)

    __slots__ = ("uid", "kind", "source", "target", "size", "transferred",
                 "status", "message", "speed", "started_at", "finished_at",
                 "retries", "remote_dir", "local_dir", "override_name",
                 "is_dir", "expanded")

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


class TransferModel(QAbstractTableModel):
    """Backing model for the transfer queue view."""

    def __init__(self, theme: _theme.Theme, parent: Any = None) -> None:
        super(TransferModel, self).__init__(parent)
        self._theme = theme
        self._items: List[TransferItem] = []

    # -- access ---------------------------------------------------------
    def items(self) -> List[TransferItem]:
        return list(self._items)

    def item_at(self, row: int) -> Optional[TransferItem]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def add_items(self, items: List[TransferItem]) -> None:
        if not items:
            return
        start = len(self._items)
        self.beginInsertRows(QModelIndex(), start, start + len(items) - 1)
        self._items.extend(items)
        self.endInsertRows()

    def remove_rows(self, rows: List[int]) -> None:
        for row in sorted(rows, reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._items[row]
                self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._items = []
        self.endResetModel()

    def clear_finished(self) -> None:
        keep = [i for i in self._items if i.status in ("queued", "active")]
        if len(keep) == len(self._items):
            return
        self.beginResetModel()
        self._items = keep
        self.endResetModel()

    def next_queued(self) -> Optional[TransferItem]:
        for item in self._items:
            if item.status == "queued":
                return item
        return None

    def row_of(self, item: TransferItem) -> int:
        try:
            return self._items.index(item)
        except ValueError:
            return -1

    def item_by_id(self, uid: int) -> Optional[TransferItem]:
        for item in self._items:
            if item.uid == uid:
                return item
        return None

    def touch(self, item: TransferItem) -> None:
        row = self.row_of(item)
        if row < 0:
            return
        self.dataChanged.emit(self.index(row, 0),
                              self.index(row, len(TRANSFER_COLUMNS) - 1))

    def pending_count(self) -> int:
        return sum(1 for i in self._items if i.status in ("queued", "active"))

    def active_count(self) -> int:
        return sum(1 for i in self._items if i.status == "active")

    def failed_count(self) -> int:
        return sum(1 for i in self._items if i.status == "error")

    # -- QAbstractTableModel -------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(TRANSFER_COLUMNS)

    def headerData(self, section: int, orientation: int,
                   role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(TRANSFER_COLUMNS):
                from .i18n import T
                return T(TRANSFER_COLUMNS[section])
        return None

    def retranslate(self) -> None:
        if self.columnCount():
            self.headerDataChanged.emit(Qt.Horizontal, 0, self.columnCount() - 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self.item_at(index.row())
        if item is None:
            return None
        column = index.column()
        if role == Qt.DisplayRole:
            if column == XFER_NAME:
                return item.display_name
            if column == XFER_DIRECTION:
                return item.kind_label()
            if column == XFER_SIZE:
                return format_size(item.size) if item.size else ""
            if column == XFER_PROGRESS:
                if item.status == "active":
                    return "%d%%" % item.progress_percent()
                if item.status == "done":
                    return "100%"
                return ""
            if column == XFER_SPEED:
                if item.status == "active" and item.speed > 0:
                    return "%s/s" % format_size(int(item.speed))
                if item.status == "done" and item.speed > 0:
                    return "%s/s" % format_size(int(item.speed))
                return ""
            if column == XFER_STATUS:
                return item.status_label()
            return ""
        if role == Qt.TextAlignmentRole:
            if column in (XFER_SIZE, XFER_PROGRESS):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            from PyQt5.QtGui import QBrush
            key = {"queued": "text_muted", "active": "info", "done": "success",
                   "error": "danger", "skipped": "warning",
                   "cancel": "text_muted"}.get(item.status, "text")
            return QBrush(self._theme.qcolor(key))
        if role == Qt.BackgroundRole:
            from PyQt5.QtGui import QBrush
            key = {"queued": "queued_row", "active": "active_row",
                   "done": "ok_row", "error": "error_row"}.get(item.status)
            if key:
                color = self._theme.qcolor(key)
                color.setAlpha(140)
                return QBrush(color)
            return None
        if role == Qt.ToolTipRole:
            return "%s\n%s → %s\n%s" % (item.source, item.source, item.target,
                                        item.status_label())
        if role == KIND_ROLE:
            return item.status
        if role == ITEM_ID_ROLE:
            return item.uid
        if role == ENTRY_ROLE:
            return QVariant(item)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable
