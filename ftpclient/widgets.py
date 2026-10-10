"""Reusable widgets: navigation bar, file table, log console, pane header."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import (QEvent, QMimeData, QModelIndex, QPoint, QSize,
                          Qt, QUrl, pyqtSignal)
from PyQt5.QtGui import QColor, QCursor, QDrag, QFont, QKeySequence
from PyQt5.QtWidgets import (QAbstractItemView, QAction, QComboBox,
                             QFileIconProvider, QFrame, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QMenu, QPlainTextEdit,
                             QSizePolicy, QStyle, QStyledItemDelegate,
                             QTableView, QToolButton, QVBoxLayout, QWidget)

from .models import ENTRY_ROLE, ITEM_ID_ROLE, FILE_COLUMNS

FILE_MIME = "application/x-nacreftp-files"

#: default width of the Name column (the user can drag it; it never stretches)
NAME_COLUMN_WIDTH = 260


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------

class ElidedLabel(QLabel):
    """A label that elides its text instead of forcing the window wider."""

    def __init__(self, text: str = "", parent: QWidget = None) -> None:
        super(ElidedLabel, self).__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text or ""
        super(ElidedLabel, self).setText(self._full_text)
        self.setToolTip(self._full_text)

    def full_text(self) -> str:
        return self._full_text

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        super(ElidedLabel, self).paintEvent(event)


class PathBar(QFrame):
    """Back / forward / up / home buttons plus an editable path field."""

    go = pyqtSignal(str)          # user asked for a path
    up = pyqtSignal()
    home = pyqtSignal()
    back = pyqtSignal()
    forward = pyqtSignal()
    refresh = pyqtSignal()

    def __init__(self, icon_for: Callable[..., Any], parent: QWidget = None,
                 show_drives: bool = False) -> None:
        super(PathBar, self).__init__(parent)
        self.setObjectName("PathFrame")
        self._icon_for = icon_for
        self._history: List[str] = []
        self._history_index = -1
        self._current = ""
        self._updating = False
        self._recent: List[str] = []
        self._drives: List[Tuple[str, str]] = []
        self._drive_provider: Optional[Callable[[], List[Tuple[str, str]]]] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        self.back_button = self._tool("arrow_left", "Back", self.back.emit)
        self.forward_button = self._tool("arrow_right", "Forward", self.forward.emit)
        self.up_button = self._tool("up", "Parent directory (Alt+Up)", self.up.emit)
        self.home_button = self._tool("home", "Home directory", self.home.emit)
        for button in (self.back_button, self.forward_button, self.up_button,
                       self.home_button):
            layout.addWidget(button)

        # a drives drop-down only makes sense for the local pane
        self.drives_button: Optional[QToolButton] = None
        if show_drives:
            self.drives_button = self._tool(
                "drive", "Switch drive / browse for a folder", self._show_drives)
            layout.addWidget(self.drives_button)

        self.edit = QLineEdit(self)
        self.edit.setObjectName("PathEdit")
        self.edit.setPlaceholderText("Path")
        self.edit.setClearButtonEnabled(False)
        self.edit.returnPressed.connect(self._emit_go)
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit, 1)

        self.recent_button = self._tool("bookmark", "Recent locations",
                                        self._show_recent)
        self.refresh_button = self._tool("refresh", "Refresh (F5)", self.refresh.emit)
        layout.addWidget(self.recent_button)
        layout.addWidget(self.refresh_button)

        self._set_enabled(False, False)
        self._tools = [
            (self.back_button, "Back"),
            (self.forward_button, "Forward"),
            (self.up_button, "Parent directory (Alt+Up)"),
            (self.home_button, "Home directory"),
            (self.recent_button, "Recent locations"),
            (self.refresh_button, "Refresh (F5)"),
        ]
        if self.drives_button is not None:
            self._tools.append(
                (self.drives_button, "Switch drive / browse for a folder"))
        self.retranslate()

    def retranslate(self) -> None:
        from .i18n import T
        for button, english in self._tools:
            try:
                button.setToolTip(T(english))
            except RuntimeError:
                continue
        try:
            self.edit.setPlaceholderText(T("Path"))
        except RuntimeError:
            pass

    # -- drives ---------------------------------------------------------
    def set_drive_provider(self, provider: Callable[[], List[Tuple[str, str]]]) -> None:
        self._drive_provider = provider

    def _show_drives(self) -> None:
        menu = QMenu(self)
        provider = self._drive_provider
        drives = provider() if provider is not None else []
        for label, path in drives:
            action = menu.addAction(self._icon_for("drive"), label)
            action.setData(path)
            action.triggered.connect(
                lambda _=False, value=path: self.go.emit(value))
        menu.addSeparator()
        from .i18n import T
        browse = menu.addAction(self._icon_for("folder_open"),
                                T("Browse for a folder…"))
        browse.triggered.connect(self._browse_for_folder)
        button = self.drives_button or self.recent_button
        menu.exec_(button.mapToGlobal(QPoint(0, button.height())))

    def _browse_for_folder(self) -> None:
        from PyQt5.QtWidgets import QFileDialog
        start = self._current if os.path.isdir(self._current) else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            self.go.emit(chosen)

    # -- construction helpers ------------------------------------------
    def _tool(self, icon: str, tip: str, slot: Callable[[], None]) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(self._icon_for(icon))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _=False: slot())
        return button

    def _set_enabled(self, can_back: bool, can_forward: bool) -> None:
        self.back_button.setEnabled(can_back)
        self.forward_button.setEnabled(can_forward)

    # -- API ------------------------------------------------------------
    def set_path(self, path: str, push_history: bool = True) -> None:
        self._updating = True
        self.edit.setText(path)
        self.edit.setCursorPosition(len(path))
        self._updating = False
        if path and path != self._current and push_history:
            self._history = self._history[:self._history_index + 1]
            self._history.append(path)
            self._history_index = len(self._history) - 1
        self._current = path
        self._set_enabled(self._history_index > 0,
                          self._history_index < len(self._history) - 1)
        self.edit.setToolTip(path)

    def path(self) -> str:
        return self.edit.text()

    def focus_editor(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    def set_placeholder(self, text: str) -> None:
        self.edit.setPlaceholderText(text)

    # -- history --------------------------------------------------------
    def go_back(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            self._jump_to(self._history[self._history_index])

    def go_forward(self) -> None:
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._jump_to(self._history[self._history_index])

    def _jump_to(self, path: str) -> None:
        self.set_path(path, push_history=False)
        self._set_enabled(self._history_index > 0,
                          self._history_index < len(self._history) - 1)
        self.go.emit(path)

    def set_recent(self, entries: List[str]) -> None:
        self._recent = list(entries)

    def _show_recent(self) -> None:
        recent = getattr(self, "_recent", None) or []
        menu = QMenu(self)
        for entry in recent[:20]:
            action = menu.addAction(entry)
            action.triggered.connect(
                lambda _=False, value=entry: self.go.emit(value))
        if not recent:
            empty = menu.addAction("(no recent locations)")
            empty.setEnabled(False)
        menu.exec_(self.recent_button.mapToGlobal(
            QPoint(0, self.recent_button.height())))

    # -- events ---------------------------------------------------------
    def _emit_go(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.go.emit(text)

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        if obj is self.edit and event.type() == QEvent.FocusIn:
            self.edit.selectAll()
        return super(PathBar, self).eventFilter(obj, event)


# ---------------------------------------------------------------------------
# File table
# ---------------------------------------------------------------------------

def draw_column_separators(painter: Any, option: Any, index: QModelIndex,
                           color: Any, margin: int = 0) -> None:
    """Draw thin vertical rules at the column boundaries of one cell.

    Qt's own grid lines are drawn uniformly and look heavy in a cream theme, so
    the separators are painted here instead: a 1 px rule on the right and, for
    the left-most column, on the left as well.  They are drawn on every row so
    the columns stay readable all the way down, not just under the header.

    ``margin`` insets the rule vertically (used by the transfers table so the
    progress column does not look boxed in).
    """
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QPen
    if color is None:
        return
    rect = option.rect
    if rect.width() <= 0 or rect.height() <= 0:
        return
    was_active = painter.isActive()
    if not was_active:
        painter.begin(option.widget)
    painter.save()
    pen = QPen(QColor(color))
    pen.setWidth(1)
    pen.setCosmetic(True)
    painter.setPen(pen)
    top = rect.top() + margin
    bottom = rect.bottom() - margin
    if bottom > top:
        x = rect.right()
        painter.drawLine(x, top, x, bottom)
        if index.column() == 0:
            painter.drawLine(rect.left(), top, rect.left(), bottom)
    painter.restore()
    if not was_active:
        painter.end()


class ColumnSeparatorDelegate(QStyledItemDelegate):
    """A default delegate that adds crisp vertical column separators."""

    def __init__(self, theme: Any, parent: QWidget = None,
                 color_key: str = "gridline", margin: int = 0) -> None:
        super(ColumnSeparatorDelegate, self).__init__(parent)
        self._theme = theme
        self._color_key = color_key
        self._margin = margin
        self._color = None

    def refresh_colour(self) -> None:
        self._color = self._theme.color(self._color_key, "border")

    def paint(self, painter: Any, option: Any, index: QModelIndex) -> None:
        super(ColumnSeparatorDelegate, self).paint(painter, option, index)
        if self._color is None:
            self.refresh_colour()
        draw_column_separators(painter, option, index, self._color,
                               self._margin)


class FileTableView(QTableView):
    """A flat file list with drag & drop and a right-click menu hook."""

    drop_files = pyqtSignal(str, list)     # source ("local"/"remote"), paths
    context_requested = pyqtSignal(QPoint)

    def __init__(self, side: str, parent: QWidget = None) -> None:
        super(FileTableView, self).__init__(parent)
        self.side = side
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_requested.emit)
        self.setIconSize(QSize(18, 18))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setCornerButtonEnabled(False)
        self._separators: Optional[ColumnSeparatorDelegate] = None

    def attach_column_separators(self, theme: Any) -> None:
        """Install the delegate that draws the vertical column separators."""
        self._separators = ColumnSeparatorDelegate(theme, self, "gridline", 1)
        self.setItemDelegate(self._separators)

    def refresh_separator_colour(self) -> None:
        if self._separators is not None:
            self._separators.refresh_colour()
            self.viewport().update()

    # -- sizing ---------------------------------------------------------
    def apply_theme(self, row_height: int, icon_size: int) -> None:
        self.verticalHeader().setDefaultSectionSize(max(18, int(row_height)))
        self.setIconSize(QSize(icon_size, icon_size))
        header = self.horizontalHeader()
        # The Name column keeps the width the user gave it — it is never
        # stretched by the pane resizing. Long names elide with "…" and the
        # full value is in the tooltip, exactly like FileZilla.
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        self.setColumnWidth(0, NAME_COLUMN_WIDTH)
        # Modified holds "2026-10-07 12:14:58"; it is right aligned, so it must
        # be wide enough for the full timestamp or the seconds get clipped
        widths = {1: 76, 2: 96, 3: 152, 4: 92, 5: 92}
        for column, width in widths.items():
            if column < len(FILE_COLUMNS):
                header.setSectionResizeMode(column, QHeaderView.Interactive)
                self.setColumnWidth(column, width)

    def set_name_column_width(self, width: int) -> None:
        self.setColumnWidth(0, max(60, int(width)))

    def apply_last_column_stretch(self) -> None:
        """Let the right-most *visible* column absorb the leftover width.

        Only the last one - the Name column keeps its fixed width. When the
        Permissions / Owner columns are shown they take the stretch instead,
        which is exactly how FileZilla lines its columns up.
        """
        header = self.horizontalHeader()
        last = -1
        for column in range(header.count()):
            if not self.isColumnHidden(column):
                last = column
        if last < 0:
            header.setStretchLastSection(False)
            return
        for column in range(header.count()):
            if column == last:
                continue
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(last, QHeaderView.Stretch)

    def name_column_width(self) -> int:
        return self.columnWidth(0)

    def width_for_names(self, names: List[str], padding: int = 46) -> int:
        """A pixel width that fits ``names`` without stretching the pane."""
        metrics = self.fontMetrics()
        widest = 0
        for name in names[:400]:
            widest = max(widest, metrics.horizontalAdvance(name or ""))
        return max(140, min(520, widest + padding))

    # -- selection helpers ---------------------------------------------
    def selected_rows(self) -> List[int]:
        rows = [index.row() for index in self.selectionModel().selectedRows()]
        return sorted(set(rows))

    # -- drag & drop ----------------------------------------------------
    def mimeTypes(self) -> List[str]:  # noqa: N802
        return [FILE_MIME, "text/uri-list"]

    def startDrag(self, supported_actions: Any) -> None:  # noqa: N802
        model = self.model()
        if model is None:
            return
        entries = [model.entry_at(row) for row in self.selected_rows()]
        entries = [e for e in entries if e is not None and not e.is_parent]
        if not entries:
            return
        mime = QMimeData()
        payload = ("%s\n" % self.side) + "\n".join(e.name for e in entries)
        mime.setData(FILE_MIME, payload.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction)

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802
        if event.mimeData().hasFormat(FILE_MIME):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        elif event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super(FileTableView, self).dragEnterEvent(event)

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802
        if event.mimeData().hasFormat(FILE_MIME) or event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super(FileTableView, self).dragMoveEvent(event)

    def dropEvent(self, event: Any) -> None:  # noqa: N802
        mime = event.mimeData()
        paths: List[str] = []
        if mime.hasFormat(FILE_MIME):
            text = bytes(mime.data(FILE_MIME)).decode("utf-8", "replace")
            lines = [line for line in text.splitlines() if line]
            if lines and lines[0] in ("local", "remote"):
                side = lines[0]
                paths = lines[1:]
            else:
                side = self.side
                paths = lines
            self.drop_files.emit(side, paths)
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    paths.append(url.toLocalFile())
            if paths:
                self.drop_files.emit("local", paths)
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return
        super(FileTableView, self).dropEvent(event)


# ---------------------------------------------------------------------------
# Log console
# ---------------------------------------------------------------------------

class LogView(QPlainTextEdit):
    """A read-only console with severity colouring."""

    def __init__(self, theme: Any, parent: QWidget = None) -> None:
        super(LogView, self).__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(4000)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._theme = theme
        theme.changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        font = self._theme.mono_font()
        font.setPointSize(max(8, font.pointSize() - 1))
        self.setFont(font)

    def append_line(self, level: str, message: str) -> None:
        import time as _time
        stamp = _time.strftime("%H:%M:%S")
        color = {
            "error": self._theme.color("danger"),
            "warn": self._theme.color("warning"),
            "success": self._theme.color("success"),
            "info": self._theme.color("accent"),
            "muted": self._theme.color("text_muted"),
        }.get(level, self._theme.color("text"))
        label = {"error": "ERROR", "warn": "WARN ", "success": "OK   ",
                 "info": "INFO ", "muted": "     "}.get(level, "     ")
        safe = (message or "").replace("&", "&amp;").replace("<", "&lt;") \
                              .replace(">", "&gt;")
        html = ('<span style="color:%s">%s</span> '
                '<span style="color:%s">%s</span>'
                % (self._theme.color("text_muted"), stamp, color,
                   "%s %s" % (label, safe)))
        self.appendHtml(html)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ---------------------------------------------------------------------------
# Pane header
# ---------------------------------------------------------------------------

class PaneHeader(QFrame):
    """Title row above a file list: name, quick toggles and a search box."""

    search_changed = pyqtSignal(str)
    toggle_hidden = pyqtSignal(bool)
    refresh = pyqtSignal()

    def __init__(self, title_key: str, icon_for: Callable[..., Any],
                 parent: QWidget = None) -> None:
        super(PaneHeader, self).__init__(parent)
        self.title_key = title_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)

        self.badge = QLabel(self)
        self.badge.setFixedSize(10, 10)
        layout.addWidget(self.badge)

        self.title = QLabel(self)
        self.title.setObjectName("PaneTitle")
        layout.addWidget(self.title)

        self.subtitle = ElidedLabel("", self)
        self.subtitle.setObjectName("Hint")
        layout.addWidget(self.subtitle, 1)

        self.hidden_button = QToolButton(self)
        self.hidden_button.setIcon(icon_for("eye"))
        self.hidden_button.setIconSize(QSize(17, 17))
        self.hidden_button.setCheckable(True)
        self.hidden_button.setChecked(True)
        self.hidden_button.setCursor(Qt.PointingHandCursor)
        self.hidden_button.toggled.connect(self._on_hidden)
        layout.addWidget(self.hidden_button)

        self.search = QLineEdit(self)
        self.search.setObjectName("SearchEdit")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(170)
        self.search.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self.search)
        self.retranslate()

    def _on_hidden(self, checked: bool) -> None:
        from .i18n import T
        self.hidden_button.setToolTip(
            T("Hide hidden files") if checked else T("Show hidden files"))
        self.toggle_hidden.emit(checked)

    def retranslate(self) -> None:
        from .i18n import T
        try:
            self.title.setText(T(self.title_key))
            self.search.setPlaceholderText(T("Filter…"))
            self.hidden_button.setToolTip(
                T("Hide hidden files") if self.hidden_button.isChecked()
                else T("Show hidden files"))
        except RuntimeError:
            pass

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def set_title_key(self, key: str) -> None:
        """Remember the English key so a language switch can restore it."""
        self.title_key = key
        from .i18n import T
        self.title.setText(T(key))

    def set_badge_color(self, color: QColor) -> None:
        self.badge.setStyleSheet(
            "background-color: %s; border-radius: 5px;" % color.name())


# ---------------------------------------------------------------------------
# Progress delegate for the transfer table
# ---------------------------------------------------------------------------

class ProgressDelegate(ColumnSeparatorDelegate):
    """Draws a slim rounded progress bar inside the Progress column.

    It also paints the column separators, so the Progress column lines up with
    the rest of the table.
    """

    def __init__(self, theme: Any, parent: QWidget = None) -> None:
        super(ProgressDelegate, self).__init__(theme, parent, "gridline", 2)
        self._theme = theme

    def paint(self, painter: Any, option: Any, index: QModelIndex) -> None:
        from PyQt5.QtGui import QPen
        model = index.model()
        item_id = index.data(ITEM_ID_ROLE)
        item = None
        if hasattr(model, "item_by_id") and item_id is not None:
            item = model.item_by_id(item_id)
        if item is None or item.status != "active":
            super(ProgressDelegate, self).paint(painter, option, index)
            self._paint_separator(painter, option, index)
            return
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawControl(QStyle.CE_ItemViewItem, option, painter,
                              option.widget)
        percent = item.progress_percent()
        rect = option.rect.adjusted(6, 0, -6, 0)
        height = 8
        top = rect.top() + (rect.height() - height) // 2
        track = self._theme.qcolor("track")
        fill = self._theme.qcolor("progress")
        painter.save()
        painter.setRenderHint(painter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect.left(), top, rect.width(), height,
                                height / 2.0, height / 2.0)
        width = int(rect.width() * percent / 100.0)
        if width > 0:
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.left(), top, width, height,
                                    height / 2.0, height / 2.0)
        painter.setPen(QPen(self._theme.qcolor("text_muted")))
        painter.drawText(option.rect, Qt.AlignRight | Qt.AlignVCenter,
                         "%d%%  " % percent)
        painter.restore()
        self._paint_separator(painter, option, index)

    def _paint_separator(self, painter: Any, option: Any,
                         index: QModelIndex) -> None:
        """Keep the column separators aligned with the other delegates."""
        if self._color is None:
            self.refresh_colour()
        draw_column_separators(painter, option, index, self._color,
                               self._margin)
