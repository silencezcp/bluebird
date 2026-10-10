"""The local and remote file panes."""

from __future__ import annotations

import os
import posixpath
from typing import Any, Callable, List, Optional

from PyQt5.QtCore import QObject, QPoint, QSize, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMenu, QSizePolicy, QToolButton, QVBoxLayout,
                             QWidget)

from . import session as _session
from .i18n import T
from .models import Entry, FileListModel
from .retranslate import Retranslator
from .widgets import FileTableView, LogView, PathBar, PaneHeader

#: how many files to stat before telling the UI about the progress
SIZE_BATCH = 20
#: safeguard: never stat more than this many files in one directory
SIZE_LIMIT = 4000


class SizeFetcher(QObject):
    """Asks the server for the file sizes a directory listing left out.

    Runs the (blocking) per-file ``stat`` calls on its own ``QThread`` and
    reports back in small batches, so a slow or huge directory never freezes
    the window.  The thread always runs to completion: :meth:`stop` only tells
    it to finish early, which keeps the Qt object lifetimes trivial.
    """

    batch_ready = pyqtSignal(object, int, int, list)

    def __init__(self, session: _session.BaseSession, names: List[str],
                 parent: Any = None) -> None:
        super(SizeFetcher, self).__init__(parent)
        self.session = session
        self.names = list(names)
        self._stop = False
        self._thread = QThread()
        self._thread.setObjectName("smart-size-fetcher")
        self.moveToThread(self._thread)
        self._thread.started.connect(self._work)
        self._thread.finished.connect(self.deleteLater)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Ask the worker to finish early (the thread still exits cleanly)."""
        self._stop = True

    def wait(self, timeout_ms: int = 3000) -> None:
        try:
            self._thread.wait(timeout_ms)
        except Exception:
            pass

    @property
    def running(self) -> bool:
        try:
            return self._thread.isRunning()
        except RuntimeError:
            return False

    def _work(self) -> None:
        total = len(self.names)
        done = 0
        batch: List[Any] = []
        for name in self.names:
            if self._stop:
                break
            try:
                info = self.session.stat_file(name)
            except Exception:
                info = None
            batch.append((name, info))
            done += 1
            if len(batch) >= SIZE_BATCH:
                self.batch_ready.emit(self, done, total, batch)
                batch = []
        if batch:
            self.batch_ready.emit(self, done, total, batch)
        self._thread.quit()


class FilePane(QWidget):
    """A pane showing one directory (local or remote)."""

    #: emitted after a successful listing
    listing_ready = pyqtSignal(object, object)      # pane, entries
    #: emitted when navigation failed; message is user friendly
    listing_failed = pyqtSignal(object, str)
    #: emitted when another pane dropped files here
    files_dropped = pyqtSignal(object, str, list)   # pane, source side, names
    #: emitted when the user activates a row (double click / Enter)
    activated = pyqtSignal(object, object)          # pane, entry
    #: emitted when the current directory changed
    directory_changed = pyqtSignal(object, str)
    #: log a message on behalf of the pane
    log = pyqtSignal(str, str)
    #: the user asked for a context menu
    context_requested = pyqtSignal(object, QPoint)
    #: the user asked to transfer the current selection
    transfer_requested = pyqtSignal(object)
    #: refresh requested by the user
    refresh_requested = pyqtSignal(object)

    def __init__(self, side: str, title_key: str, theme: Any, icons: Any,
                 settings: Any, parent: QWidget = None) -> None:
        super(FilePane, self).__init__(parent)
        self.side = side                    # "local" | "remote"
        self.title_key = title_key          # English key, for retranslation
        self.theme = theme
        self.icons = icons
        self.settings = settings
        self.local = side == "local"
        # the Home button of the local pane opens the Desktop folder
        self.home_dir = _session.local_desktop() if self.local else ""

        self.session: Optional[_session.BaseSession] = None
        self.path: str = ""
        self._history: List[str] = []
        self._history_index = -1
        self._busy = False
        self._size_fetcher: Optional[SizeFetcher] = None
        self._size_pending: Dict[str, Entry] = {}
        self._retranslator = Retranslator()

        self._build_ui()
        theme.changed.connect(self._apply_theme)
        self._retranslator.bind(self.retranslate)
        self._apply_theme()

    @property
    def title(self) -> str:
        from .i18n import T
        return T(self.title_key)

    def retranslate(self) -> None:
        try:
            self.header.retranslate()
            self.path_bar.retranslate()
            self.model.retranslate()
            self._update_status()
        except RuntimeError:
            pass

    # -- construction ---------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = PaneHeader(self.title_key, self._header_icon, self)
        self.header.search_changed.connect(self._on_search)
        self.header.toggle_hidden.connect(self._on_toggle_hidden)
        outer.addWidget(self.header)

        self.path_bar = PathBar(lambda name: self.icons.action_icon(name, size=18),
                                self, show_drives=self.local)
        self.path_bar.go.connect(self.navigate)
        self.path_bar.up.connect(self.navigate_up)
        self.path_bar.home.connect(self.navigate_home)
        self.path_bar.back.connect(self.path_bar.go_back)
        self.path_bar.forward.connect(self.path_bar.go_forward)
        self.path_bar.refresh.connect(lambda: self.refresh(force=True))
        if self.local:
            self.path_bar.set_drive_provider(_session.local_roots)
        outer.addWidget(self.path_bar)

        self.model = FileListModel(self.theme, self.icons, self)
        self.table = FileTableView(self.side, self)
        self.table.setModel(self.model)
        # crisp vertical rules between the columns (Name | Size | Type | ...)
        self.table.attach_column_separators(self.theme)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.drop_files.connect(
            lambda source, names: self.files_dropped.emit(self, source, names))
        self.table.context_requested.connect(
            lambda point: self.context_requested.emit(self, point))
        outer.addWidget(self.table, 1)

        self.status = QLabel("", self)
        self.status.setObjectName("Hint")
        self.status.setContentsMargins(8, 3, 8, 3)
        outer.addWidget(self.status)

        self.table.selectionModel().selectionChanged.connect(self._update_status)
        self.table.horizontalHeader().sectionResized.connect(self._on_column_resized)

    def _on_column_resized(self, column: int, _old: int, _new: int) -> None:
        """Remember a manual Name width (but not an auto-fit one)."""
        if column == 0 and not self._fit_enabled():
            self._remember_name_width()

    def _header_icon(self, name: str) -> Any:
        return self.icons.action_icon(name, size=17)

    # -- theme ----------------------------------------------------------
    def _apply_theme(self) -> None:
        appearance = self.settings.get("appearance", default={}) or {}
        row_height = int(appearance.get("row_height", 26) or 26)
        icon_size = int(appearance.get("icon_size", 18) or 18)
        self.table.apply_theme(row_height, icon_size)
        self.table.setAlternatingRowColors(bool(appearance.get("alternating_rows", True)))
        self.table.setShowGrid(bool(appearance.get("grid_lines", False)))
        # the separators use a palette colour, so they follow a theme change
        self.table.refresh_separator_colour()
        self.header.hidden_button.setIcon(self._header_icon(
            "eye" if self.header.hidden_button.isChecked() else "eye_off"))
        # restore the width the user chose for the Name column
        saved = appearance.get("column_widths", {}) or {}
        column = saved.get("name")
        if column:
            try:
                self.table.set_name_column_width(int(column))
            except (TypeError, ValueError):
                pass
        if self._fit_enabled():
            self._fit_name_column()
        self._apply_column_visibility()
        self._update_status()

    def _apply_column_visibility(self) -> None:
        """Permissions / Owner can be switched off to save horizontal room."""
        self.table.setColumnHidden(4, not bool(
            self.settings.get("appearance", "show_permissions", True)))
        self.table.setColumnHidden(5, not bool(
            self.settings.get("appearance", "show_owner", False)))
        # whichever column is visible last absorbs the spare width, so values
        # line up with the right edge of the pane
        self.table.apply_last_column_stretch()

    def _fit_enabled(self) -> bool:
        return bool(self.settings.get("appearance", "auto_fit_name_column", False))

    def _fit_name_column(self) -> None:
        """Optionally widen Name to fit its contents (off by default)."""
        names = [e.name for e in self.model.visible_entries()]
        if not names:
            return
        self.table.set_name_column_width(self.table.width_for_names(names))

    def autofit_name_column(self) -> None:
        self._fit_name_column()

    def _remember_name_width(self) -> None:
        widths = dict(self.settings.get("appearance", "column_widths", {}) or {})
        widths["name"] = int(self.table.name_column_width())
        self.settings.set("appearance", "column_widths", widths)

    # -- backend --------------------------------------------------------
    def set_session(self, session: Optional[_session.BaseSession]) -> None:
        self.session = session

    def set_local(self, path: Optional[str] = None) -> None:
        target = path or _session.local_home()
        self.navigate(target)

    # -- directory listing ---------------------------------------------
    def current_remote_dir(self) -> str:
        if self.session is None:
            return self.path
        return self.session.cwd()

    def source_dir(self) -> str:
        """The directory that identifies where the listed items live."""
        if self.local:
            return self.path
        return self.current_remote_dir()

    def navigate(self, path: str, push_history: bool = True) -> bool:
        if self._busy:
            return False
        path = (path or "").strip()
        if not path:
            return False
        self._cancel_size_fetch()
        show_hidden = bool(self.settings.get("appearance", "show_hidden", True))
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        self._busy = True
        try:
            if self.local:
                expanded = os.path.abspath(os.path.expandvars(
                    os.path.expanduser(path)))
                entries = _session.local_listdir(expanded, show_hidden)
                resolved = expanded
            else:
                if self.session is None:
                    raise _session.SessionError("Not connected")
                resolved = self.session.chdir(path)
                entries = self.session.listdir()
        except _session.SessionError as exc:
            self.listing_failed.emit(self, exc.message)
            return False
        except Exception as exc:  # noqa: BLE001
            self.listing_failed.emit(self, _session.human_error(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
            self._busy = False

        self.path = resolved
        self.model.set_show_hidden(show_hidden)
        self.model.set_entries(entries, show_parent=not self.local)
        self.model.sort(0, Qt.AscendingOrder)
        self._apply_column_visibility()
        self.path_bar.set_path(resolved, push_history=push_history)
        if self._fit_enabled():
            self._fit_name_column()
        self._remember(resolved)
        self._update_status()
        self.directory_changed.emit(self, resolved)
        self.listing_ready.emit(self, entries)
        if not self.local:
            self._resolve_missing_sizes()
        return True

    # -- missing file sizes ---------------------------------------------
    def _resolve_missing_sizes(self) -> None:
        """Ask the server for sizes the listing left out (SFTP, plain LIST)."""
        missing = self.model.entries_without_size()
        if not missing or self.session is None:
            return
        if len(missing) > SIZE_LIMIT:
            missing = missing[:SIZE_LIMIT]
            self.log.emit("warn", "%s: only reading the first %d missing sizes"
                          % (self.title, SIZE_LIMIT))
        self._size_pending = dict((e.name, e) for e in missing)
        fetcher = SizeFetcher(self.session, list(self._size_pending.keys()), self)
        fetcher.batch_ready.connect(self._on_size_batch)
        self._size_fetcher = fetcher
        self.status.setText("Reading file sizes… 0/%d" % len(missing))
        fetcher.start()

    def fetch_missing_sizes(self) -> bool:
        """Manual trigger from the View menu. True when a pass was started."""
        if self.local:
            return False
        if self.model.entries_without_size():
            self._resolve_missing_sizes()
            return True
        self.status.setText("Every file size is already known")
        return False

    def _on_size_batch(self, fetcher: Any, done: int, total: int,
                       batch: List[Any]) -> None:
        if fetcher is not self._size_fetcher:
            return
        for name, info in batch:
            entry = self._size_pending.pop(name, None)
            if entry is None:
                continue
            if not info:
                # the server really does not know: show 0 instead of "…"
                if entry.size is None:
                    self.model.set_entry_size(entry, 0)
                continue
            self.model.set_entry_size(
                entry, info.get("size"), info.get("mtime"),
                info.get("permissions", ""))
        if self._size_pending:
            self.status.setText("Reading file sizes… %d/%d"
                                % (total - len(self._size_pending), total))
        else:
            self._finish_size_fetch()
        self._update_status()

    def _finish_size_fetch(self) -> None:
        unresolved = len(self._size_pending)
        title = self.title
        self._size_pending = {}
        self._size_fetcher = None
        if unresolved:
            self.log.emit("warn", "%s: %d file size(s) unavailable"
                          % (title, unresolved))
        self._update_status()

    def _cancel_size_fetch(self) -> None:
        """Drop the current pass; its thread finishes on its own."""
        fetcher = self._size_fetcher
        self._size_fetcher = None
        self._size_pending = {}
        if fetcher is not None:
            try:
                fetcher.stop()
            except RuntimeError:
                pass

    def refresh(self, force: bool = False) -> None:
        if not self.path or self._busy:
            return
        self.navigate(self.path, push_history=False)

    def navigate_up(self) -> None:
        if self.local:
            stripped = self.path.rstrip("\\/")
            parent = os.path.dirname(stripped)
            # a drive root has no parent: offer the drive picker instead of
            # silently doing nothing (a modal menu here would block callers)
            if not parent or parent == stripped or (
                    len(stripped) <= 2 and stripped.endswith(":")):
                self.show_drive_picker()
                return
            self.navigate(parent)
            return
        parent = posixpath.dirname(self.path.rstrip("/")) or "/"
        if parent != self.path:
            self.navigate(parent)

    def navigate_home(self) -> None:
        if self.local:
            start = str(self.settings.get("behavior", "local_start_dir", "") or "")
            self.navigate(start or (self.home_dir or _session.local_home()))
            return
        home = self.session.home() if self.session else None
        self.navigate(home or "/")

    def _remember(self, path: str) -> None:
        if path != (self._history[-1] if self._history else None):
            self._history.append(path)
            self._history_index = len(self._history) - 1
        self.path_bar.set_recent(self._history[-12:])

    # -- interactions ---------------------------------------------------
    def _on_double_click(self, index: Any) -> None:
        entry = self.model.entry_at(index.row())
        if entry is None:
            return
        if entry.is_parent:
            self.navigate_up()
            return
        self.activated.emit(self, entry)

    def _on_search(self, text: str) -> None:
        self.model.set_filter(text)
        self._update_status()

    def _on_toggle_hidden(self, checked: bool) -> None:
        self.settings.set("appearance", "show_hidden", bool(checked))
        self.header.hidden_button.setIcon(
            self._header_icon("eye" if checked else "eye_off"))
        self.model.set_show_hidden(bool(checked))
        self._update_status()

    def _update_status(self) -> None:
        total = self.model.rowCount()
        files = sum(1 for e in self.model.visible_entries() if not e.is_dir)
        rows = self.table.selected_rows()
        selected = len(rows)
        size = self.model.total_selected_size(rows)
        from .models import format_size
        parts = [T("%d items") % total, T("%d files") % files]
        if selected:
            parts.append(T("%d selected (%s)") % (selected, format_size(size)))
        elif self.model.visible_entries():
            total_size = sum(e.size_value() for e in self.model.visible_entries()
                             if not e.is_dir)
            parts.append(format_size(total_size))
        unknown = len(self.model.entries_without_size())
        if unknown:
            parts.append(T("%d size(s) pending") % unknown)
        self.status.setText("   ·   ".join(parts))
        if not self.local and self.session is not None:
            self.header.set_subtitle(self.session.describe())
        elif self.local:
            self.header.set_subtitle(T("This computer"))
        connected = self.session.connected if self.session is not None else self.local
        self.header.set_badge_color(
            self.theme.qcolor("success" if connected else "border_strong"))

    # -- selection helpers ---------------------------------------------
    def selected_entries(self) -> List[Entry]:
        entries = []
        for row in self.table.selected_rows():
            entry = self.model.entry_at(row)
            if entry is not None and not entry.is_parent:
                entries.append(entry)
        return entries

    def first_selected(self) -> Optional[Entry]:
        entries = self.selected_entries()
        return entries[0] if entries else None

    def select_names(self, names: List[str]) -> None:
        wanted = set(name.lower() for name in names)
        self.table.clearSelection()
        selection = self.table.selectionModel()
        for row, entry in enumerate(self.model.visible_entries()):
            if entry.name.lower() in wanted:
                selection.select(
                    self.model.index(row, 0),
                    selection.Select | selection.Rows)
        rows = self.table.selected_rows()
        if rows:
            self.table.scrollTo(self.model.index(rows[0], 0))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.table.setEnabled(not busy)
        self.path_bar.setEnabled(not busy)

    def focus_list(self) -> None:
        self.table.setFocus()

    # -- drives ---------------------------------------------------------
    def show_drive_picker(self) -> None:
        """Let the user pick another drive / folder to show locally."""
        if not self.local:
            return
        from PyQt5.QtWidgets import QFileDialog
        start = self.path if os.path.isdir(self.path) else _session.local_home()
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a drive or folder", start)
        if chosen:
            self.navigate(chosen)

    def drive_list(self) -> List[Any]:
        return _session.local_roots()
