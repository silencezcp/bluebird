"""The main window: dual panes, transfer queue, log and all the wiring."""

from __future__ import annotations

import datetime
import os
import posixpath
import sys
from typing import Any, Dict, List, Optional, Tuple
from PyQt5.QtCore import QByteArray, QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QIcon, QKeySequence
from PyQt5.QtWidgets import (QAbstractItemView, QAction, QApplication,
                             QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                             QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QMenu, QPlainTextEdit, QPushButton,
                             QSizePolicy, QSplitter, QStatusBar, QTabWidget,
                             QTableView, QToolBar, QToolButton, QVBoxLayout,
                             QWidget)

from . import __appname__, __author__, __version__
from . import config as _config
from . import session as _session
from .dialogs import ConnectDialog, PreferencesDialog, SiteManagerDialog
from .i18n import T, i18n, localise_box
from .icons import IconFactory
from .menu import MainMenu
from .models import (ENTRY_ROLE, ITEM_ID_ROLE, Entry, FileListModel,
                     TransferItem, TransferModel, format_size, format_time)
from .panes import FilePane
from .retranslate import Retranslator
from .session import SessionError, human_error
from .theme import Theme
from .transfer import TransferManager, plan_downloads, plan_uploads
from .widgets import ColumnSeparatorDelegate, LogView, ProgressDelegate


class TextViewerDialog(QDialog):
    """A simple text viewer / editor for remote files."""

    def __init__(self, name: str, text: str, theme: Theme,
                 parent: QWidget = None, editable: bool = True) -> None:
        super(TextViewerDialog, self).__init__(parent)
        self.setWindowTitle("Edit — %s" % name)
        self.resize(760, 560)
        self.theme = theme
        self.editable = editable
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.editor = QPlainTextEdit(self)
        self.editor.setPlainText(text)
        self.editor.setFont(theme.mono_font())
        self.editor.setReadOnly(not editable)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(self)
        if editable:
            apply_button = buttons.addButton("Save && close",
                                             QDialogButtonBox.AcceptRole)
            apply_button.setObjectName("Primary")
            buttons.addButton(QDialogButtonBox.Cancel)
            buttons.rejected.connect(self.reject)
            buttons.accepted.connect(self.accept)
        else:
            buttons.addButton(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.editor.toPlainText()


class TransferQueuePanel(QWidget):
    """The transfer queue table plus its little toolbar."""

    def __init__(self, manager: TransferManager, theme: Theme, icons: IconFactory,
                 parent: QWidget = None) -> None:
        super(TransferQueuePanel, self).__init__(parent)
        self.manager = manager
        self.theme = theme
        self.icons = icons
        self._retranslator = Retranslator()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setContentsMargins(4, 4, 4, 0)
        self.pause_button = self._button("pause", "Pause the queue",
                                         self._toggle_pause, checkable=True)
        self.retry_button = self._button("refresh", "Retry failed transfers",
                                         self._retry)
        self.remove_button = self._button("delete", "Remove the selected items",
                                          self._remove)
        self.clear_button = self._button("clear", "Remove finished transfers",
                                         self._clear)
        bar.addWidget(self.pause_button)
        bar.addWidget(self.retry_button)
        bar.addWidget(self.remove_button)
        bar.addWidget(self.clear_button)
        bar.addStretch(1)
        self.summary = QLabel("", self)
        self.summary.setObjectName("Hint")
        bar.addWidget(self.summary)
        layout.addLayout(bar)

        self.model = TransferModel(theme, self)
        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setItemDelegateForColumn(
            4, ProgressDelegate(theme, self.table))
        # the remaining columns get the plain separator delegate so the column
        # rules are continuous from the header to the last row
        self._separators = ColumnSeparatorDelegate(theme, self.table,
                                                   "gridline", 2)
        for column in (0, 1, 2, 3, 5, 6):
            self.table.setItemDelegateForColumn(column, self._separators)
        header = self.table.horizontalHeader()
        # Time is narrow and fixed: "HH:MM:SS" never needs more than ~64 px
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column, width in ((0, 68), (2, 100), (3, 90), (4, 130), (5, 100),
                              (6, 170)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)
        self._retranslator.bind(self.retranslate)
        self.retranslate()

    def _button(self, icon: str, tip: str, slot: Any,
                checkable: bool = False) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(self.icons.action_icon(icon, size=18))
        button.setProperty("tkey", tip)
        button.setToolTip(T(tip))
        button.setCheckable(checkable)
        button.setAutoRaise(True)
        button.clicked.connect(slot)
        return button

    def retranslate(self) -> None:
        """Keep every button label in the active language."""
        from .i18n import T as translate
        pairs = ((self.pause_button,
                  "Resume the queue" if self.manager.paused else "Pause the queue"),
                 (self.retry_button, "Retry failed transfers"),
                 (self.remove_button, "Remove the selected items"),
                 (self.clear_button, "Remove finished transfers"))
        for button, english in pairs:
            try:
                button.setToolTip(T(english))
            except RuntimeError:
                continue
        self.model.retranslate()
        self.summary.setText(self.manager.summary() if self.manager.items
                             else T("Queue is empty"))

    # -- actions --------------------------------------------------------
    def _toggle_pause(self, checked: bool) -> None:
        if checked:
            self.manager.pause()
            self.pause_button.setIcon(self.icons.action_icon("play", size=18))
            self.pause_button.setToolTip("Resume the queue")
        else:
            self.manager.resume()
            self.pause_button.setIcon(self.icons.action_icon("pause", size=18))
            self.pause_button.setToolTip("Pause the queue")

    def _retry(self) -> None:
        rows = self._selected_ids()
        self.manager.retry(rows or None)

    def _remove(self) -> None:
        rows = self._selected_ids()
        if rows:
            self.manager.remove(rows)

    def _clear(self) -> None:
        self.manager.clear_finished()

    def _selected_ids(self) -> List[int]:
        ids: List[int] = []
        for index in self.table.selectionModel().selectedRows():
            value = index.data(ITEM_ID_ROLE)
            if value is not None:
                ids.append(int(value))
        return ids

    def _on_double_click(self, index: Any) -> None:
        uid = index.data(ITEM_ID_ROLE)
        if uid is None:
            return
        item = self.manager.item_by_id(int(uid))
        if item is None:
            return
        if item.status == "error":
            QMessageBox.warning(self, "Transfer failed",
                                "%s\n\n%s" % (item.source, item.message))
        else:
            folder = os.path.dirname(item.target)
            if os.path.isdir(folder):
                os.startfile(folder) if os.name == "nt" else None

    def _context_menu(self, point: Any) -> None:
        from .i18n import T as translate
        ids = self._selected_ids()
        menu = QMenu(self)
        menu.addAction(self.icons.action_icon("play", size=18), T("Retry"),
                       lambda: self.manager.retry(ids or None))
        menu.addAction(self.icons.action_icon("pause", size=18),
                       T("Pause/Resume the queue"),
                       lambda: self.pause_button.click())
        menu.addSeparator()
        menu.addAction(self.icons.action_icon("delete", size=18),
                       T("Remove from list"),
                       lambda: self.manager.remove(ids))
        menu.addAction(self.icons.action_icon("clear", size=18),
                       T("Clear finished"), self.manager.clear_finished)
        menu.exec_(self.table.viewport().mapToGlobal(point))

    # -- refresh --------------------------------------------------------
    def sync(self) -> None:
        from .i18n import T as translate
        self.summary.setText(self.manager.summary() if self.manager.items
                             else T("Queue is empty"))
        self.pause_button.setChecked(self.manager.paused)


class MainWindow(QMainWindow):
    """Everything the user sees."""

    def __init__(self, settings: _config.Settings, theme: Theme,
                 icons: IconFactory) -> None:
        super(MainWindow, self).__init__()
        self.settings = settings
        self.theme = theme
        self.icons = icons

        self.session: Optional[_session.BaseSession] = None
        self.connection_config: Dict[str, Any] = {}
        self.connection_name = ""
        self._last_error = ""
        self._closing = False
        self._failed_remote: List[str] = []
        self._failed_local: List[str] = []
        self._retranslator = Retranslator()
        #: the in-app manual window, created on first use
        self._manual_window: Optional[Any] = None
        #: uids that settled in the current batch; they share one dialog
        self._finished_uids: List[int] = []
        self._flush_scheduled = False
        #: "Yes to all" applies to the current batch only, then resets
        self._overwrite_all = False
        #: the test suite runs windowless, so it can mute the status dialogs
        self._quiet_dialogs = bool(
            os.environ.get("BLUEBIRD_QUIET_DIALOGS", ""))
        #: the last connection error, kept for the tests and the status line
        self._last_connection_error = ""
        # a member timer (not a bare singleShot) so it can be cancelled when
        # the window closes or a test wants a deterministic flush
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(400)
        self._flush_timer.timeout.connect(self._flush_transfer_results)

        self.setWindowTitle(self._product_title())
        self.setWindowIcon(self._window_icon())

        self.local_pane = FilePane("local", "Local site", theme, icons, settings, self)
        self.remote_pane = FilePane("remote", "Remote site", theme, icons, settings, self)

        self.manager = TransferManager(_session.create_session({}), settings, self)
        self.manager.item_added.connect(self._on_transfer_item)
        self.manager.item_updated.connect(self._on_transfer_update)
        self.manager.item_finished.connect(self._on_item_finished)
        self.manager.queue_changed.connect(self._on_queue_changed)
        self.manager.stats_changed.connect(self._refresh_status)
        self.manager.log.connect(self.log)
        self.manager.all_finished.connect(self._on_all_finished)

        self._build_ui()
        self._wire_panes()

        self.menu = MainMenu(self, self._handlers(), icons)
        self.addToolBar(self.menu.build_toolbar())
        self._refresh_recent_menu()
        self._sync_view_menu()
        self._apply_theme()

        theme.changed.connect(self._apply_theme)
        self._retranslator.bind(self.retranslate)
        self._restore_state()
        self._start_local()

    def retranslate(self) -> None:
        """Re-apply every visible string for the active language."""
        try:
            self._retranslate_connection_bar()
            self.menu.retranslate()
            self.local_pane.retranslate()
            self.remote_pane.retranslate()
            self.queue_panel.retranslate()
            self.bottom_tabs.setTabText(0, "  %s  " % T("Transfers"))
            self.bottom_tabs.setTabText(1, "  %s  " % T("Log"))
            self._refresh_recent_menu()
            self._sync_view_menu()
            # the product name is 青鸟 in Chinese, BlueBird in English
            self._refresh_status()
        except RuntimeError:
            pass

    def _product_title(self) -> str:
        from . import display_name
        return display_name()

    def changeEvent(self, event: Any) -> None:  # noqa: N802
        """Qt sends LanguageChange when the application language flips."""
        if event.type() == QEvent.LanguageChange:
            self.retranslate()
        super(MainWindow, self).changeEvent(event)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _window_icon(self) -> QIcon:
        """The application icon: a cloud over a three-node network."""
        try:
            from . import appicon
            return appicon.icon()
        except Exception:
            # never let the icon stop the window from opening
            icon = QIcon()
            for size in (16, 24, 32, 48, 64):
                icon.addPixmap(self.icons.file_icon(
                    "folder", self.theme.color("folder"), "folder",
                    size=size).pixmap(size, size))
            return icon

    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.connection_bar = self._build_connection_bar()
        outer.addWidget(self.connection_bar)

        self.site_splitter = QSplitter(Qt.Horizontal, central)
        self.site_splitter.setChildrenCollapsible(False)
        self.site_splitter.addWidget(self.local_pane)
        self.site_splitter.addWidget(self.remote_pane)
        self.site_splitter.setSizes([600, 600])

        self.center_splitter = QSplitter(Qt.Vertical, central)
        self.center_splitter.setChildrenCollapsible(False)
        center = QWidget(self.center_splitter)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(6, 6, 6, 0)
        center_layout.addWidget(self.site_splitter)
        self.center_splitter.addWidget(center)

        bottom = QWidget(self.center_splitter)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(6, 0, 6, 6)
        self.bottom_tabs = QTabWidget(bottom)
        self.bottom_tabs.setDocumentMode(True)

        self.queue_panel = TransferQueuePanel(self.manager, self.theme, self.icons,
                                              self.bottom_tabs)
        self.log_view = LogView(self.theme, self.bottom_tabs)
        self.bottom_tabs.addTab(self.queue_panel, "  %s  " % T("Transfers"))
        self.bottom_tabs.addTab(self.log_view, "  Log  ")
        bottom_layout.addWidget(self.bottom_tabs)
        self.center_splitter.addWidget(bottom)
        self.center_splitter.setSizes([620, 240])
        outer.addWidget(self.center_splitter, 1)
        self.setCentralWidget(central)

        self.status = QStatusBar(self)
        self.status.setSizeGripEnabled(True)
        self.setStatusBar(self.status)
        self.status_connection = QLabel("Not connected", self)
        self.status_queue = QLabel("", self)
        self.status_selection = QLabel("", self)
        self.status.addWidget(self.status_connection, 1)
        self.status.addPermanentWidget(self.status_selection)
        self.status.addPermanentWidget(self.status_queue)

    def _build_connection_bar(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("ToolBarFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(7)

        label = QLabel(T("Server"), frame)
        label.setObjectName("SectionTitle")
        self.connection_label = label
        layout.addWidget(label)

        self.name_edit = QLineEdit(frame)
        self.name_edit.setPlaceholderText(T("Connection name"))
        self.name_edit.setMinimumWidth(120)
        self.name_edit.setToolTip(T("Name this connection is saved under "
                                    "(config.ini)"))
        self.name_edit.returnPressed.connect(self.connect_to_server)
        layout.addWidget(self.name_edit, 2)

        self.protocol_combo = QComboBox(frame)
        self.protocol_combo.addItem(T("FTP"), "ftp")
        self.protocol_combo.addItem(T("FTPS"), "ftps")
        self.protocol_combo.addItem(T("SFTP"), "sftp")
        self.protocol_combo.setFixedWidth(84)
        self.protocol_combo.currentIndexChanged.connect(self._on_protocol_changed)
        layout.addWidget(self.protocol_combo)

        self.host_edit = QLineEdit(frame)
        self.host_edit.setPlaceholderText(T("Host — e.g. ftp.example.com"))
        self.host_edit.setMinimumWidth(200)
        self.host_edit.returnPressed.connect(self.connect_to_server)
        layout.addWidget(self.host_edit, 3)

        self.port_edit = QLineEdit(frame)
        self.port_edit.setFixedWidth(62)
        self.port_edit.setPlaceholderText("21")
        self.port_edit.returnPressed.connect(self.connect_to_server)
        layout.addWidget(self.port_edit)

        self.user_edit = QLineEdit(frame)
        self.user_edit.setPlaceholderText(T("User"))
        self.user_edit.setMinimumWidth(110)
        self.user_edit.returnPressed.connect(self.connect_to_server)
        layout.addWidget(self.user_edit, 2)

        self.password_edit = QLineEdit(frame)
        self.password_edit.setPlaceholderText(T("Password"))
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setMinimumWidth(110)
        self.password_edit.returnPressed.connect(self.connect_to_server)
        layout.addWidget(self.password_edit, 2)

        self.connect_button = QPushButton(T("Connect"), frame)
        self.connect_button.setObjectName("Primary")
        self.connect_button.setIcon(self.icons.action_icon("connect", size=16))
        self.connect_button.clicked.connect(self.connect_to_server)
        layout.addWidget(self.connect_button)

        self.disconnect_button = QPushButton(T("Disconnect"), frame)
        self.disconnect_button.setIcon(
            self.icons.action_icon("disconnect", size=16))
        self.disconnect_button.clicked.connect(self.disconnect_server)
        self.disconnect_button.setEnabled(False)
        layout.addWidget(self.disconnect_button)

        self.sites_button = QToolButton(frame)
        self.sites_button.setIcon(self.icons.action_icon("sites", size=18))
        self.sites_button.setToolTip(T("Site manager"))
        self.sites_button.setAutoRaise(True)
        self.sites_button.clicked.connect(self.open_site_manager)
        layout.addWidget(self.sites_button)

        return frame

    def _retranslate_connection_bar(self) -> None:
        from .i18n import T as translate
        widgets = (
            (self.connection_label, "setText", "Server"),
            (self.connect_button, "setText", "Connect"),
            (self.disconnect_button, "setText", "Disconnect"),
        )
        for widget, _method, english in widgets:
            try:
                widget.setText(T(english))
            except RuntimeError:
                continue
        placeholders = ((self.name_edit, "Connection name"),
                        (self.host_edit, "Host — e.g. ftp.example.com"),
                        (self.user_edit, "User"),
                        (self.password_edit, "Password"))
        for widget, english in placeholders:
            try:
                widget.setPlaceholderText(T(english))
            except RuntimeError:
                continue
        try:
            self.sites_button.setToolTip(T("Site manager"))
            self.name_edit.setToolTip(
                T("Name this connection is saved under (config.ini)"))
        except RuntimeError:
            pass
        # the protocol names are translated in place, keeping their data
        for index, english in enumerate(("FTP", "FTPS", "SFTP")):
            if index < self.protocol_combo.count():
                self.protocol_combo.setItemText(index, T(english))

    def _wire_panes(self) -> None:
        for pane in (self.local_pane, self.remote_pane):
            pane.activated.connect(self._on_activated)
            pane.context_requested.connect(self._on_context_menu)
            pane.files_dropped.connect(self._on_files_dropped)
            pane.listing_failed.connect(self._on_listing_failed)
            pane.log.connect(self.log)
        self.remote_pane.listing_ready.connect(self._on_remote_listing)
        self.local_pane.listing_ready.connect(self._on_local_listing)

    # ------------------------------------------------------------------
    # theme
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        appearance = self.settings.get("appearance", default={}) or {}
        self.setFont(self.theme.base_font())
        for pane in (self.local_pane, self.remote_pane):
            pane._apply_theme()
            pane.path_bar.back_button.setIcon(self.icons.action_icon("arrow_left", size=18))
            pane.path_bar.forward_button.setIcon(self.icons.action_icon("arrow_right", size=18))
            pane.path_bar.up_button.setIcon(self.icons.action_icon("up", size=18))
            pane.path_bar.home_button.setIcon(self.icons.action_icon("home", size=18))
            pane.path_bar.refresh_button.setIcon(self.icons.action_icon("refresh", size=18))
            pane.path_bar.recent_button.setIcon(self.icons.action_icon("bookmark", size=18))
            pane.header.hidden_button.setIcon(self.icons.action_icon(
                "eye" if pane.header.hidden_button.isChecked() else "eye_off",
                size=17))
        self.connect_button.setIcon(self.icons.action_icon("connect", size=16))
        self.disconnect_button.setIcon(self.icons.action_icon("disconnect", size=16))
        self.sites_button.setIcon(self.icons.action_icon("sites", size=18))
        if hasattr(self, "menu"):
            for key, action in self.menu.actions.items():
                # icons were built from the palette; rebuild them in place
                action.setIcon(self._action_icon_for(key))
        self.queue_panel.pause_button.setIcon(self.icons.action_icon(
            "play" if self.manager.paused else "pause", size=18))
        self.queue_panel.retry_button.setIcon(self.icons.action_icon("refresh", size=18))
        self.queue_panel.remove_button.setIcon(self.icons.action_icon("delete", size=18))
        self.queue_panel.clear_button.setIcon(self.icons.action_icon("clear", size=18))
        self.setWindowIcon(self._window_icon())
        self._refresh_status()

    _ACTION_ICONS = {
        "site_manager": "sites", "connect": "connect", "open_log_file": "save",
        "quit": "close", "disconnect": "disconnect", "refresh_both": "refresh",
        "remote_mkdir": "new_folder", "remote_rename": "rename",
        "remote_delete": "delete", "upload": "upload", "download": "download",
        "pause_queue": "pause", "retry_failed": "refresh",
        "clear_queue": "clear", "goto_queue": "queue", "show_hidden": "eye",
        "autofit_names": "filter",
        "refresh_local": "refresh", "refresh_remote": "refresh",
        "preferences": "settings", "swap_panes": "sync", "edit_remote": "edit",
        "copy_url": "bookmark", "clear_log": "clear", "shortcuts": "info",
        "about": "info",
    }

    def _action_icon_for(self, key: str) -> QIcon:
        name = self._ACTION_ICONS.get(key)
        if not name:
            return QIcon()
        return self.icons.action_icon(name, size=20)

    def _refresh_status(self) -> None:
        if self.session is not None and self.session.connected:
            label = self.connection_name or self.name_edit.text().strip()
            self.status_connection.setText(T("Connected to %s%s") % (
                (T("“%s” — ") % label) if label else "", self.session.describe()))
            # a compact title keeps the connection bar from being squeezed
            self.setWindowTitle("%s  [%s]" % (self._product_title(),
                                              label or T("connected")))
        else:
            self.status_connection.setText(T("Not connected"))
            self.setWindowTitle(self._product_title())
        queue_text = self.manager.summary() if self.manager.items else ""
        active = self.manager.active()
        if active:
            speed = sum(i.speed for i in self.manager.items if i.status == "active")
            queue_text = "%s   路   %s/s" % (queue_text, format_size(int(speed)))
        self.status_queue.setText(queue_text)
        self.queue_panel.sync()

    # ------------------------------------------------------------------
    # startup helpers
    # ------------------------------------------------------------------
    def _start_local(self) -> None:
        behavior = self.settings.get("behavior", default={}) or {}
        start = ""
        if behavior.get("remember_last_dirs"):
            start = str(behavior.get("last_local_dir", "") or "")
        if not start or not os.path.isdir(start):
            start = str(behavior.get("local_start_dir", "") or "")
        if not start or not os.path.isdir(start):
            start = _session.local_home()
        self.local_pane.navigate(start)
        self.log("info", "Local pane ready: %s" % start)

    def _restore_state(self) -> None:
        window = self.settings.get("window", default={}) or {}
        geometry = window.get("geometry", "")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(geometry.encode("ascii")))
            except Exception:
                pass
        else:
            self.resize(1240, 800)
        for name, splitter in (("splitter_main", self.center_splitter),
                               ("splitter_site", self.site_splitter)):
            sizes = window.get(name, [])
            if isinstance(sizes, list) and len(sizes) == splitter.count():
                try:
                    splitter.setSizes([int(v) for v in sizes])
                except (TypeError, ValueError):
                    pass
        self.bottom_tabs.setCurrentIndex(int(window.get("active_tab", 0) or 0))
        show_hidden = bool(self.settings.get("appearance", "show_hidden", True))
        auto_fit = bool(self.settings.get("appearance", "auto_fit_name_column",
                                          False))
        if hasattr(self, "menu"):
            self.menu.actions["show_hidden"].setChecked(show_hidden)
            self.menu.actions["autofit_names"].setChecked(auto_fit)
        for pane in (self.local_pane, self.remote_pane):
            pane.header.hidden_button.setChecked(show_hidden)
            if auto_fit:
                pane.autofit_name_column()

    def _save_state(self) -> None:
        geometry = bytes(self.saveGeometry().toHex()).decode("ascii")
        self.settings.update("window", {
            "geometry": geometry,
            "splitter_main": self.center_splitter.sizes(),
            "splitter_site": self.site_splitter.sizes(),
            "active_tab": self.bottom_tabs.currentIndex(),
        }, autosave=False)
        behavior: Dict[str, Any] = {}
        if self.settings.get("behavior", "remember_last_dirs", True):
            behavior["last_local_dir"] = self.local_pane.path
            if self.session is not None and self.session.connected:
                behavior["last_remote_dir"] = self.remote_pane.path
        if behavior:
            self.settings.update("behavior", behavior, autosave=False)
        self.settings.save()
        self._remember_connection_dirs()

    def _remember_connection_dirs(self) -> None:
        """Store the last directories per saved connection in config.ini."""
        name = self.connection_name or self.name_edit.text().strip()
        if not name or not self.settings.get("behavior", "remember_last_dirs", True):
            return
        remote_dir = self.remote_pane.path if (
            self.session is not None and self.session.connected) else ""
        try:
            self.settings.connections.remember_dirs(
                name, self.local_pane.path, remote_dir)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # logging
    # ------------------------------------------------------------------
    def log(self, level: str, message: str) -> None:
        self.log_view.append_line(level, message)

    # ------------------------------------------------------------------
    # connections
    # ------------------------------------------------------------------
    def _protocol(self) -> str:
        data = self.protocol_combo.currentData()
        return str(data or "ftp")

    def _default_port(self) -> int:
        return _session.default_port(self._protocol())

    def _on_protocol_changed(self) -> None:
        if self.port_edit.text().strip() in ("", "21", "22"):
            self.port_edit.setText(str(self._default_port()))

    def _report_connection_success(self, config: Dict[str, Any]) -> None:
        """Confirm a completed connection with a short popup."""
        if self.session is None:
            return
        host = config.get("host", "?")
        port = config.get("port")
        target = "%s:%s" % (host, port) if port else str(host)
        protocol = str(config.get("protocol", "ftp")).upper()
        user = config.get("user") or "anonymous"
        try:
            folder = self.remote_pane.path or "/"
        except Exception:
            folder = "/"
        self._show_status_box(
            QMessageBox.Information, T("Connected"),
            T("Connected to %s.") % target,
            "%s · %s@%s" % (protocol, user, target),
            "%s: %s\n%s: %s\n%s: %s"
            % (T("Folder"), folder, T("User"), user, T("Protocol"), protocol))

    def connect_to_server(self) -> None:
        config = self._config_from_bar()
        if not config.get("host"):
            self.open_connect_dialog()
            return
        if not config.get("name"):
            config["name"] = _config.default_connection_name(config)
            self.name_edit.setText(config["name"])
        self._connect(config)
        self._report_connection_success(config)

    def open_connect_dialog(self, values: Optional[Dict[str, Any]] = None) -> None:
        dialog = ConnectDialog(self.settings, self, values or self._config_from_bar(),
                               self.icons)
        if dialog.exec_() != QDialog.Accepted:
            return
        config = dialog.config()
        self._config_to_bar(config)
        self._connect(config, save=dialog.save_site.isChecked())

    def _config_from_bar(self) -> Dict[str, Any]:
        host = self.host_edit.text().strip()
        port_text = self.port_edit.text().strip()
        try:
            port = int(port_text) if port_text else self._default_port()
        except ValueError:
            port = self._default_port()
        behavior = self.settings.get("sessions", default={}) or {}
        return {
            "name": self.name_edit.text().strip(),
            "protocol": self._protocol(),
            "host": host,
            "port": port,
            "user": self.user_edit.text().strip(),
            "password": self.password_edit.text(),
            "passive": bool(behavior.get("passive", True)),
            "timeout": float(behavior.get("timeout", 30) or 30),
            "keepalive": float(behavior.get("keepalive", 30) or 30),
            "verify_host_key": bool(behavior.get("verify_host_key", False)),
            "encoding": str(behavior.get("encoding", "utf-8")),
            "preserve_timestamps": bool(
                self.settings.get("transfers", "preserve_timestamps", False)),
        }

    def _config_to_bar(self, config: Dict[str, Any]) -> None:
        index = self.protocol_combo.findData(config.get("protocol", "ftp"))
        if index >= 0:
            self.protocol_combo.setCurrentIndex(index)
        name = str(config.get("name", "") or "")
        if not name:
            name = _config.default_connection_name(config)
        self.name_edit.setText(name)
        self.host_edit.setText(str(config.get("host", "")))
        self.port_edit.setText(str(config.get("port", self._default_port())))
        self.user_edit.setText(str(config.get("user", "")))
        self.password_edit.setText(str(config.get("password", "")))

    def _show_status_box(self, icon: Any, title: str, text: str,
                         informative: str = "", details: str = "") -> Any:
        """Show a small modal status dialog and return it.

        Kept in one place so the three connection/listing reports look alike,
        and so the test suite has a single seam to observe them through.
        """
        if self._quiet_dialogs:
            return None
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(text)
        if informative:
            box.setInformativeText(informative)
        if details:
            box.setDetailedText(details)
        box.setStandardButtons(QMessageBox.Ok)
        localise_box(box)
        box.exec_()
        return box

    def _report_connection_failure(self, config: Dict[str, Any],
                                   message: str) -> None:
        """Tell the user, loudly, that a connection attempt failed.

        A silent failure is the worst outcome: the button seemed to do
        nothing.  The dialog carries the details so the exact server reply can
        be copied, and the log keeps the full history.
        """
        host = config.get("host", "?")
        port = config.get("port")
        target = "%s:%s" % (host, port) if port else str(host)
        self._last_connection_error = message
        self._show_status_box(
            QMessageBox.Critical, T("Connection failed"),
            T("Could not connect to %s.") % target, message,
            "%s\n%s: %s\n%s: %s\n%s: %s"
            % (T("The server reported:"), T("Host"), target,
               T("Protocol"), str(config.get("protocol", "ftp")).upper(),
               T("User"), config.get("user") or "anonymous"))

    def _abandon_session(self, session: Any, config: Dict[str, Any],
                         message: str) -> None:
        """Drop a session that logged in but cannot be used."""
        self.log("error", "Connection unusable: %s" % message)
        try:
            session.disconnect()
        except Exception:
            pass
        self.session = None
        self.remote_pane.set_session(None)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self._refresh_status()
        self._report_connection_failure(config, message)

    def _connect(self, config: Dict[str, Any], save: bool = True) -> None:
        if self.session is not None:
            self.disconnect_server(silent=True)
        if not config.get("name"):
            config["name"] = _config.default_connection_name(config)
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        self.status_connection.setText("Connecting to %s…" % config.get("host"))
        try:
            session = _session.create_session(config)
            session.connect()
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            message = human_error(exc)
            self.log("error", "Connection failed: %s" % message)
            self._refresh_status()
            self._report_connection_failure(config, message)
            return

        # A successful login is not yet a usable session: the first directory
        # listing is what really proves it.  Doing it here means a failure is
        # reported by the connection dialog instead of vanishing into the log.
        start = str(config.get("remote_dir")
                    or self.settings.get("behavior", "last_remote_dir", "/")
                    or "/")
        try:
            session.chdir(start)
        except Exception as exc:  # noqa: BLE001
            message = human_error(exc)
            if start != "/":
                # the remembered directory may be gone; the account itself can
                # still be fine, so fall back to the root before giving up
                try:
                    session.chdir("/")
                    start = "/"
                    self.log("warn", "Could not open %s, using / instead: %s"
                             % (start, message))
                except Exception:
                    QApplication.restoreOverrideCursor()
                    self._abandon_session(session, config, message)
                    return
            else:
                QApplication.restoreOverrideCursor()
                self._abandon_session(session, config, message)
                return

        QApplication.restoreOverrideCursor()
        self.session = session
        self.connection_config = config
        self.manager.session = session
        self.remote_pane.set_session(session)
        self.remote_pane.header.set_title("Remote site")
        banner = session.banner.strip() if session.banner else ""
        if banner:
            self.log("success", "Connected to %s — %s" % (session.describe(), banner))
        else:
            self.log("success", "Connected to %s (%s)"
                     % (session.describe(), session.protocol_label))
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)

        # every successful connection is remembered, named, in config.ini
        if save:
            self._store_connection(config)
        self.settings.push_recent("saved://%s" % config.get("name", ""))
        self._refresh_recent_menu()

        if not self.remote_pane.navigate(start) and start != "/":
            self.remote_pane.navigate("/")
        self._refresh_status()

    def _store_connection(self, config: Dict[str, Any]) -> None:
        """Write (or update) this connection in the local config.ini."""
        try:
            section = self.settings.connections.upsert(config)
        except Exception as exc:  # noqa: BLE001 - never block a session
            self.log("warn", "Could not save the connection: %s" % exc)
            return
        stored = self.settings.connections.get(section) or {}
        config["name"] = str(stored.get("name") or config.get("name") or section)
        config["section"] = section
        self.connection_name = config["name"]
        self.name_edit.setText(self.connection_name)
        self.log("info", "Connection saved to config.ini as “%s”"
                 % self.connection_name)
        self._refresh_status()

    def disconnect_server(self, silent: bool = False) -> None:
        if self.session is not None:
            self.manager.cancel_all()
            try:
                self.session.disconnect()
            except Exception:
                pass
            self.log("info", "Disconnected from %s" % self.session.describe())
        self.session = None
        self.remote_pane.set_session(None)
        self.remote_pane.model.clear()
        self.remote_pane.path = ""
        self.remote_pane.path_bar.set_path("", push_history=False)
        self.remote_pane.header.set_subtitle("Not connected")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self._refresh_status()
        if not silent:
            self.status.showMessage("Disconnected", 4000)

    def open_site_manager(self) -> None:
        dialog = SiteManagerDialog(self.settings, self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_site:
            site = dict(dialog.selected_site)
            self._config_to_bar(site)
            self._connect(site)
            self._report_connection_success(site)

    def _refresh_recent_menu(self) -> None:
        if not hasattr(self, "menu"):
            return
        menu = self.menu.recent_menu
        menu.clear()
        saved = self.settings.sites()
        if saved:
            header = menu.addAction("Saved connections (config.ini)")
            header.setEnabled(False)
            for site in saved:
                label = "%s  —  %s@%s" % (site.get("name", "?"),
                                          site.get("user") or "anonymous",
                                          site.get("host", ""))
                action = menu.addAction(label)
                action.setIcon(self.icons.action_icon(
                    "sync" if site.get("protocol") == "sftp" else "connect",
                    size=16))
                action.triggered.connect(
                    lambda _=False, value=dict(site): self._connect_saved(value))
            menu.addSeparator()
        recent = self.settings.recent()
        if recent:
            header = menu.addAction("Recently used")
            header.setEnabled(False)
            for entry in recent[:12]:
                name = entry[8:] if entry.startswith("saved://") else entry
                action = menu.addAction(name)
                action.triggered.connect(
                    lambda _=False, value=entry: self._connect_recent(value))
        if not saved and not recent:
            action = menu.addAction("(nothing yet)")
            action.setEnabled(False)

    def _connect_saved(self, site: Dict[str, Any]) -> None:
        """Reconnect straight from config.ini, password included."""
        self._config_to_bar(site)
        self._connect(site)
        self._report_connection_success(site)

    def _connect_recent(self, entry: str) -> None:
        if entry.startswith("saved://"):
            site = self.settings.connections.get(entry[8:])
            if site is None:
                QMessageBox.information(
                    self, "Connection",
                    "“%s” is no longer in config.ini." % entry[8:])
                return
            self._connect_saved(site)
            return
        try:
            scheme_part, rest = entry.split("://", 1)
            user_part, host_part = rest.split("@", 1)
            host, port = host_part.rsplit(":", 1)
        except ValueError:
            return
        self._config_to_bar({
            "protocol": scheme_part, "host": host, "port": int(port or 21),
            "user": "" if user_part == "anonymous" else user_part,
        })
        self.open_connect_dialog()

    # ------------------------------------------------------------------
    # pane events
    # ------------------------------------------------------------------
    def _on_local_listing(self, pane: FilePane, entries: List[Entry]) -> None:
        self.status.showMessage("%s — %d items" % (pane.path, len(entries)), 2500)

    def _on_remote_listing(self, pane: FilePane, entries: List[Entry]) -> None:
        self.log("muted", "Listed %s (%d items)" % (pane.path, len(entries)))
        failed = self._failed_remote
        if failed:
            self._failed_remote = []
            self.remote_pane.select_names(failed)

    def _on_listing_failed(self, pane: FilePane, message: str) -> None:
        """A directory could not be listed - show it, do not just log it.

        This used to write to the log and a status message, and the status
        message was immediately overwritten by the refresh that follows a
        connection, so a failure looked like nothing happening at all.
        """
        self.log("error", "%s pane: %s" % (pane.title, message))
        self.status.showMessage(message, 6000)
        title = T("Cannot open the folder")
        if not pane.local:
            title = T("Remote folder unavailable")
        self._show_status_box(
            QMessageBox.Warning, title,
            T("Could not open “%s”.") % (pane.path or T("folder")), message,
            "%s: %s" % (T("Folder"), pane.path or "-"))

    def _on_activated(self, pane: FilePane, entry: Entry) -> None:
        if entry.is_dir:
            if pane.local:
                pane.navigate(os.path.join(pane.path, entry.name))
            else:
                target = posixpath.join(pane.source_dir(), entry.name)
                pane.navigate(target)
            return
        if pane.local:
            self.upload_selection()
        else:
            action = str(self.settings.get("behavior", "double_click_action", "open"))
            if action == "transfer":
                self.download_selection()
            else:
                self.download_selection()

    def _on_files_dropped(self, pane: FilePane, source: str, names: List[str]) -> None:
        if pane is self.remote_pane and source == "local":
            self.upload_names(names)
        elif pane is self.local_pane and source == "remote":
            self.download_names(names)
        elif pane.local and source == "remote":
            self.download_names(names)
        elif not pane.local and source == "local":
            self.upload_names(names)

    # ------------------------------------------------------------------
    # context menu
    # ------------------------------------------------------------------
    def _on_context_menu(self, pane: FilePane, point: Any) -> None:
        menu = self.build_context_menu(pane)
        if menu.actions():
            menu.exec_(pane.table.viewport().mapToGlobal(point))

    def build_context_menu(self, pane: FilePane) -> QMenu:
        """Build (but do not show) the right-click menu for a pane.

        Kept separate from :meth:`_on_context_menu` so the menu can be
        inspected - and translated - without opening a modal popup.
        """
        menu = QMenu(self)
        entries = pane.selected_entries()

        if pane.local:
            if entries:
                menu.addAction(self.icons.action_icon("upload", size=18),
                               T("Upload to the server"), self.upload_selection)
            menu.addAction(self.icons.action_icon("new_folder", size=18),
                           T("Create folder…"), self.local_mkdir)
            menu.addAction(self.icons.action_icon("refresh", size=18),
                           T("Refresh"), pane.refresh)
            if entries:
                menu.addSeparator()
                menu.addAction(self.icons.action_icon("rename", size=18),
                               T("Rename…"), self.local_rename)
                menu.addAction(self.icons.action_icon("delete", size=18),
                               T("Delete"), self.local_delete)
                menu.addSeparator()
                menu.addAction(T("Properties"), self.show_properties)
        else:
            if entries:
                menu.addAction(self.icons.action_icon("download", size=18),
                               T("Download to the local folder"),
                               self.download_selection)
            if self.session is not None and self.session.connected:
                menu.addAction(self.icons.action_icon("new_folder", size=18),
                               T("Create directory…"), self.remote_mkdir)
                menu.addAction(self.icons.action_icon("new_file", size=18),
                               T("Create empty file…"), self.remote_new_file)
                menu.addAction(self.icons.action_icon("refresh", size=18),
                               T("Refresh"), pane.refresh)
                if entries:
                    menu.addSeparator()
                    menu.addAction(self.icons.action_icon("edit", size=18),
                                   T("Edit"), self.edit_remote_file)
                    menu.addAction(self.icons.action_icon("rename", size=18),
                                   T("Rename…"), self.remote_rename)
                    menu.addAction(self.icons.action_icon("delete", size=18),
                                   T("Delete"), self.remote_delete)
                    if len(entries) == 1 and entries[0].is_dir:
                        menu.addAction(self.icons.action_icon("sync", size=18),
                                       T("Calculate folder size"),
                                       self.remote_folder_size)
                    menu.addSeparator()
                    menu.addAction(T("Permissions…"), self.remote_chmod)
                    menu.addAction(T("Properties"), self.show_properties)
        return menu

    # ------------------------------------------------------------------
    # helpers to resolve the "other" pane
    # ------------------------------------------------------------------
    def _transfer_target_dir(self) -> str:
        return self.remote_pane.source_dir() or "/"

    def _remote_join(self, name: str) -> str:
        base = (self.remote_pane.source_dir() or "").rstrip("/")
        return ("%s/%s" % (base, name)) if base else name

    # ------------------------------------------------------------------
    # transfers
    # ------------------------------------------------------------------
    def upload_selection(self) -> None:
        entries = self.local_pane.selected_entries()
        if not entries:
            self.status.showMessage("Select something to upload first", 4000)
            return
        self.upload_names([e.name for e in entries])

    def upload_names(self, names: List[str]) -> None:
        """Queue names relative to the local pane, or absolute paths."""
        if self.session is None or not self.session.connected:
            QMessageBox.information(self, "Not connected",
                                    "Connect to a server before uploading.")
            return
        if not names:
            return
        local_dir = self.local_pane.path
        paths: List[str] = []
        for name in names:
            # a drop from Windows Explorer already carries an absolute path
            candidate = name if os.path.isabs(name) else os.path.join(local_dir, name)
            if os.path.exists(candidate):
                paths.append(candidate)
        if not paths:
            return
        try:
            items = plan_uploads(paths, self._transfer_target_dir())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Upload", human_error(exc))
            return
        items = [i for i in items if self._confirm_overwrite_upload(i)]
        if not items:
            return
        self._overwrite_all = False
        self.manager.enqueue(items)
        total = sum(int(i.size or 0) for i in items)
        self.log("info", "Queued %d item(s) for upload (%s)"
                 % (len(items), format_size(total)))
        self.bottom_tabs.setCurrentIndex(0)
        self._refresh_status()

    def download_selection(self) -> None:
        entries = self.remote_pane.selected_entries()
        if not entries:
            self.status.showMessage("Select something to download first", 4000)
            return
        self.download_names([e.name for e in entries])

    def download_names(self, names: List[str]) -> None:
        if self.session is None or not self.session.connected:
            QMessageBox.information(self, "Not connected",
                                    "Connect to a server before downloading.")
            return
        available = {e.name: e for e in self.remote_pane.model.visible_entries()}
        entries = [available[name] for name in names if name in available]
        if not entries:
            return
        remote_dir = self.remote_pane.source_dir()
        local_dir = self.local_pane.path
        try:
            items = plan_downloads(self.session, remote_dir, entries, local_dir)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Download", human_error(exc))
            return
        items = [i for i in items if self._confirm_overwrite_download(i)]
        if not items:
            return
        self._overwrite_all = False
        self.manager.enqueue(items)
        total = sum(int(i.size or 0) for i in items)
        self.log("info", "Queued %d item(s) for download (%s)"
                 % (len(items), format_size(total)))
        self.bottom_tabs.setCurrentIndex(0)
        self._refresh_status()

    def _confirm_overwrite_upload(self, item: TransferItem) -> bool:
        if item.is_dir:
            return True
        if not self.settings.get("behavior", "confirm_overwrite", True):
            return True
        if self._overwrite_all:
            return True
        remote = self._remote_join(item.display_name)
        try:
            exists = remote in [e.name for e in self.session.listdir()]
        except Exception:
            exists = False
        if not exists:
            return True
        answer = QMessageBox.question(
            self, T("Overwrite?"),
            "%s\n\n%s" % (T("“%s” already exists on the server.") % remote,
                          T("Overwrite it?")),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
            QMessageBox.Yes)
        if answer == QMessageBox.YesToAll:
            # applies to the rest of THIS batch only: switching the preference
            # off for good would silently overwrite later on
            self._overwrite_all = True
            self.status.showMessage(T("Overwriting without asking for the rest "
                                      "of this batch"), 5000)
            return True
        return answer == QMessageBox.Yes

    def _confirm_overwrite_download(self, item: TransferItem) -> bool:
        if item.is_dir:
            try:
                _session.ensure_local_dir(item.target)
            except SessionError as exc:
                self.log("error", str(exc))
                return False
            return True
        if not os.path.exists(item.target):
            return True
        if not self.settings.get("behavior", "confirm_overwrite", True):
            return True
        if self._overwrite_all:
            return True
        answer = QMessageBox.question(
            self, T("Overwrite?"),
            "%s\n\n%s" % (T("“%s” already exists locally.") % item.target,
                          T("Overwrite it?")),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll,
            QMessageBox.Yes)
        if answer == QMessageBox.YesToAll:
            self._overwrite_all = True
            self.status.showMessage(T("Overwriting without asking for the rest "
                                      "of this batch"), 5000)
            return True
        return answer == QMessageBox.Yes

    # -- queue callbacks ------------------------------------------------
    def _on_transfer_item(self, uid: int) -> None:
        item = self.manager.item_by_id(uid)
        if item is None:
            return
        self.queue_panel.model.add_items([item])
        self._refresh_status()

    def _on_transfer_update(self, uid: int) -> None:
        item = self.manager.item_by_id(uid)
        if item is None:
            return
        model = self.queue_panel.model
        row = model.row_of(item)
        if row < 0:
            model.add_items([item])
            row = model.row_of(item)
        if row >= 0:
            model.dataChanged.emit(model.index(row, 0),
                                   model.index(row, model.columnCount() - 1))
        self._refresh_status()

    def _on_queue_changed(self) -> None:
        model = self.queue_panel.model
        wanted = self.manager.items
        current = model.items()
        if [i.uid for i in wanted] != [i.uid for i in current]:
            model.beginResetModel()
            model._items = list(wanted)
            model.endResetModel()
        self.queue_panel.sync()
        self._refresh_status()

    def _on_all_finished(self) -> None:
        done = self.manager.done()
        failed = self.manager.failed()
        if failed:
            self.log("warn", "Queue finished: %d completed, %d failed"
                     % (done, failed))
            self.status.showMessage("Transfers finished — %d failed" % failed, 8000)
        else:
            self.log("success", "All transfers completed (%d)" % done)
            self.status.showMessage("All transfers completed", 6000)
        self._refresh_status()

    # ------------------------------------------------------------------
    # completion notification + pane refresh
    # ------------------------------------------------------------------
    def _on_item_finished(self, uid: int) -> None:
        """Collect settled transfers so a batch shares one dialog."""
        if uid not in self._finished_uids:
            self._finished_uids.append(uid)
        if self._flush_scheduled:
            return
        self._flush_scheduled = True
        # give the queue a moment to empty so a multi-file transfer reports
        # once instead of popping a dialog per file
        self._flush_timer.start()

    def _flush_transfer_results(self) -> None:
        self._flush_scheduled = False
        self._flush_timer.stop()
        uids = self._finished_uids
        self._finished_uids = []
        if not uids:
            return

        items: List[TransferItem] = []
        for uid in uids:
            item = self.manager.item_by_id(uid)
            if item is not None:
                items.append(item)
        if not items:
            return

        # Keep collecting while the queue is still busy: showing a modal dialog
        # now would block the next transfer from being reported, so a folder of
        # 200 files would pop 200 dialogs one after another.
        if self.manager.pending() > 0:
            for item in items:
                if item.uid not in self._finished_uids:
                    self._finished_uids.append(item.uid)
            self._flush_scheduled = True
            self._flush_timer.start()
            return

        self._refresh_after_transfer(items)
        if not self.settings.get("transfers", "notify_finished", True):
            return

        succeeded = [i for i in items if i.status == "done"]
        failed = [i for i in items if i.status == "error"]
        cancelled = [i for i in items if i.status in ("cancel", "skipped")]
        counts = (len(succeeded), len(failed), len(cancelled))

        if len(items) == 1:
            self._show_single_result(items[0])
        else:
            self._show_batch_result(items, counts)
        self._refresh_status()

    def _show_single_result(self, item: TransferItem) -> None:
        """One file: a focused dialog naming the file and where it went.

        QMessageBox lays itself out around the text it is given and refuses to
        be widened reliably, so the short facts stay visible and the long
        paths go into the expandable details panel.
        """
        download = item.kind == "download"
        folder = os.path.dirname(item.target)
        if item.status == "done":
            title = T("Download complete") if download else T("Upload complete")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle(title)
            box.setText(item.display_name)
            box.setInformativeText(title)
            box.setDetailedText("%s\n%s" % (T("Destination folder:"), folder))
            box.setStandardButtons(QMessageBox.Ok)
            localise_box(box)
            box.exec_()
            return

        if item.status in ("cancel", "skipped"):
            return
        title = (T("Download finished with errors") if download
                 else T("Upload finished with errors"))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(item.display_name)
        box.setInformativeText(item.message or title)
        box.setDetailedText("%s\n-> %s" % (item.source, item.target))
        box.setStandardButtons(QMessageBox.Ok)
        localise_box(box)
        box.exec_()

    def _show_batch_result(self, items: List[TransferItem],
                           counts: Tuple[int, int, int]) -> None:
        """Several files: one summary dialog with the failures listed."""
        succeeded, failed, cancelled = counts
        if failed:
            icon = QMessageBox.Warning
            title = T("Transfer finished with errors")
        elif cancelled and not succeeded:
            icon = QMessageBox.Information
            title = T("Transfer cancelled")
        else:
            icon = QMessageBox.Information
            title = T("Transfer complete")

        # a compact one-liner: QMessageBox sizes itself to its text and cannot
        # be widened reliably, so a wrapped "Success 4 / Failed 2" would read
        # worse than this
        summary = T("%d ok / %d failed") % (succeeded, failed)
        if cancelled:
            summary = T("%d ok / %d failed / %d cancelled") % (
                succeeded, failed, cancelled)

        problems = [i for i in items if i.status == "error"]
        details = [T("Succeeded: %d") % succeeded]
        if failed:
            details.append(T("Failed: %d") % failed)
        if cancelled:
            details.append(T("Cancelled: %d") % cancelled)
        if problems:
            details.append("")
            details.append(T("Details:"))
            for item in problems[:12]:
                details.append("%s\n    %s" % (item.display_name, item.message))
            if len(problems) > 12:
                details.append(T("and %d more") % (len(problems) - 12))

        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(summary)
        box.setDetailedText("\n".join(details))
        box.setStandardButtons(QMessageBox.Ok)
        localise_box(box)
        box.exec_()

    def _refresh_after_transfer(self, items: List[TransferItem]) -> None:
        """Show the new files right away in whichever pane they landed in."""
        if not self.settings.get("transfers", "refresh_after_transfer", True):
            return
        local_dirs = set()
        remote_dirs = set()
        for item in items:
            if item.kind == "download":
                folder = os.path.dirname(item.target)
                if folder:
                    local_dirs.add(os.path.normcase(os.path.abspath(folder)))
            else:
                target = item.target.rstrip("/")
                directory = target if item.is_dir else posixpath.dirname(target)
                if directory:
                    remote_dirs.add(directory.rstrip("/") or "/")
        current_local = os.path.normcase(os.path.abspath(self.local_pane.path))
        if current_local in local_dirs:
            self.local_pane.refresh(force=True)
        if remote_dirs and self.session is not None and self.session.connected:
            current_remote = (self.remote_pane.path or "").rstrip("/") or "/"
            if current_remote in remote_dirs:
                self.remote_pane.refresh(force=True)

    def _set_transfer_option(self, key: str, checked: bool) -> None:
        self.settings.set("transfers", key, bool(checked))

    # ------------------------------------------------------------------
    # transfer menu handlers
    # ------------------------------------------------------------------
    def toggle_pause_queue(self, checked: bool = False) -> None:
        if self.manager.paused:
            self.manager.resume()
        else:
            self.manager.pause()
        if hasattr(self, "menu"):
            self.menu.actions["pause_queue"].setChecked(self.manager.paused)
        self.queue_panel.pause_button.setChecked(self.manager.paused)
        self.queue_panel.pause_button.setIcon(self.icons.action_icon(
            "play" if self.manager.paused else "pause", size=18))
        self._refresh_status()

    def retry_failed(self) -> None:
        self.manager.retry()
        self.log("info", "Retrying failed transfers")

    def clear_finished_transfers(self) -> None:
        self.manager.clear_finished()
        self._refresh_status()

    def show_queue(self) -> None:
        self.bottom_tabs.setCurrentIndex(0)

    def show_log(self) -> None:
        self.bottom_tabs.setCurrentIndex(1)

    # ------------------------------------------------------------------
    # file operations
    # ------------------------------------------------------------------
    def local_mkdir(self) -> None:
        name, ok = QInputDialog.getText(self, T("Create folder"),
                                        T("Folder name:"))
        if not ok or not name.strip():
            return
        path = os.path.join(self.local_pane.path, name.strip())
        try:
            os.makedirs(path)
        except OSError as exc:
            QMessageBox.warning(self, "Create folder", human_error(exc))
            return
        self.local_pane.refresh()
        self.local_pane.select_names([name.strip()])
        self.log("success", "Created %s" % path)

    def local_rename(self) -> None:
        entry = self.local_pane.first_selected()
        if entry is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename", T("New name:"),
                                            text=entry.name)
        if not ok or not new_name.strip() or new_name == entry.name:
            return
        source = os.path.join(self.local_pane.path, entry.name)
        target = os.path.join(self.local_pane.path, new_name.strip())
        try:
            os.rename(source, target)
        except OSError as exc:
            QMessageBox.warning(self, "Rename", human_error(exc))
            return
        self.local_pane.refresh()
        self.local_pane.select_names([new_name.strip()])

    def local_delete(self) -> None:
        entries = self.local_pane.selected_entries()
        if not entries:
            return
        if self.settings.get("behavior", "confirm_delete", True):
            answer = QMessageBox.question(
                self, "Delete",
                T("Delete %d item(s) from this computer?") % len(entries)
                + "\n\n" + "\n".join(e.name for e in entries[:10]),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        import shutil
        errors = []
        for entry in entries:
            path = os.path.join(self.local_pane.path, entry.name)
            try:
                if entry.is_dir and not entry.is_link:
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except OSError as exc:
                errors.append("%s: %s" % (entry.name, human_error(exc)))
        self.local_pane.refresh()
        if errors:
            QMessageBox.warning(self, "Delete", "\n".join(errors))
        else:
            self.log("success", "Deleted %d local item(s)" % len(entries))

    def _require_session(self) -> bool:
        if self.session is None or not self.session.connected:
            QMessageBox.information(self, "Not connected",
                                    T("Connect to a server first."))
            return False
        return True

    def remote_mkdir(self) -> None:
        if not self._require_session():
            return
        name, ok = QInputDialog.getText(self, T("Create directory"),
                                        T("Directory name:"))
        if not ok or not name.strip():
            return
        try:
            self.session.mkdir(name.strip())
        except SessionError as exc:
            QMessageBox.warning(self, "Create directory", exc.message)
            return
        self.remote_pane.refresh()
        self.remote_pane.select_names([name.strip()])
        self.log("success", "Created %s" % self._remote_join(name.strip()))

    def remote_new_file(self) -> None:
        if not self._require_session():
            return
        name, ok = QInputDialog.getText(self, T("Create file"), T("File name:"))
        if not ok or not name.strip():
            return
        try:
            self.session.write_text(name.strip(), "")
        except SessionError as exc:
            QMessageBox.warning(self, "Create file", exc.message)
            return
        self.remote_pane.refresh()
        self.remote_pane.select_names([name.strip()])

    def remote_rename(self) -> None:
        if not self._require_session():
            return
        entry = self.remote_pane.first_selected()
        if entry is None:
            return
        new_name, ok = QInputDialog.getText(self, "Rename", T("New name:"),
                                            text=entry.name)
        if not ok or not new_name.strip() or new_name == entry.name:
            return
        try:
            self.session.rename(entry.name, new_name.strip())
        except SessionError as exc:
            QMessageBox.warning(self, "Rename", exc.message)
            return
        self._failed_remote = [new_name.strip()]
        self.remote_pane.refresh()

    def remote_delete(self) -> None:
        if not self._require_session():
            return
        entries = self.remote_pane.selected_entries()
        if not entries:
            return
        if self.settings.get("behavior", "confirm_delete", True):
            answer = QMessageBox.question(
                self, "Delete",
                T("Delete %d item(s) on the server?") % len(entries)
                + "\n\n" + "\n".join(e.name for e in entries[:10]),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        errors = []
        for entry in entries:
            try:
                self.session.delete_recursive(entry.name, entry.is_dir)
            except SessionError as exc:
                errors.append("%s: %s" % (entry.name, exc.message))
        self.remote_pane.refresh()
        if errors:
            QMessageBox.warning(self, "Delete", "\n".join(errors))
        else:
            self.log("success", "Deleted %d remote item(s)" % len(entries))

    @staticmethod
    def _mode_hint(entry: Entry) -> str:
        if entry.mode:
            return "%o" % (entry.mode & 0o7777)
        return "755" if entry.is_dir else "644"

    def remote_chmod(self) -> None:
        if not self._require_session():
            return
        entry = self.remote_pane.first_selected()
        if entry is None:
            return
        text, ok = QInputDialog.getText(
            self, T("Permissions"),
            T("Octal mode for “%s”:") % entry.name,
            text=self._mode_hint(entry))
        if not ok or not text.strip():
            return
        try:
            mode = int(text.strip(), 8)
        except ValueError:
            QMessageBox.warning(self, "Permissions",
                                T("Enter an octal mode, for example 644 or 755."))
            return
        try:
            self.session.chmod(entry.name, mode)
        except SessionError as exc:
            QMessageBox.warning(self, "Permissions", exc.message)
            return
        self.remote_pane.refresh()
        self.log("success", "Set mode %o on %s" % (mode, entry.name))

    def remote_folder_size(self) -> None:
        if not self._require_session():
            return
        entry = self.remote_pane.first_selected()
        if entry is None or not entry.is_dir:
            return
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        total = 0
        count = 0
        stack = [entry.name]
        try:
            while stack:
                current = stack.pop()
                for child in self.session.listdir(current):
                    if child.is_dir and not child.is_link:
                        stack.append("%s/%s" % (current.rstrip("/"), child.name))
                    else:
                        total += child.size_value()
                        count += 1
        except SessionError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Folder size", exc.message)
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "Folder size",
            T("%s contains %d file(s), %s in total.")
            % (entry.name, count, format_size(total)))

    def edit_remote_file(self) -> None:
        if not self._require_session():
            return
        entry = self.remote_pane.first_selected()
        if entry is None or entry.is_dir:
            return
        if entry.size and entry.size > 4 * 1024 * 1024:
            answer = QMessageBox.question(
                self, "Edit",
                T("“%s” is %s. Opening it in the editor may be slow."
                  "\n\nContinue?") % (entry.name, format_size(entry.size)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            text = self.session.read_text(entry.name)
        except SessionError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Edit", exc.message)
            return
        QApplication.restoreOverrideCursor()
        dialog = TextViewerDialog(entry.name, text, self.theme, self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                self.session.write_text(entry.name, dialog.text())
            except SessionError as exc:
                QMessageBox.warning(self, "Save", exc.message)
                return
            self.log("success", "Saved %s" % entry.name)
            self.remote_pane.refresh()

    def show_properties(self) -> None:
        pane = self.local_pane if self.local_pane.table.hasFocus() \
            else self.remote_pane
        entries = pane.selected_entries()
        if not entries:
            pane = self.remote_pane if pane is self.local_pane else self.local_pane
            entries = pane.selected_entries()
        if not entries:
            return
        entry = entries[0]
        if pane.local:
            path = os.path.join(pane.path, entry.name)
        else:
            path = self._remote_join(entry.name)
        lines = [
            T("Name: %s") % entry.name,
            T("Path: %s") % path,
            T("Type: %s") % entry.type_label(),
            T("Size: %s") % format_size(entry.size),
            T("Modified: %s") % (format_time(entry.mtime) or T("unknown")),
            T("Permissions: %s") % (entry.permissions or T("unknown")),
            T("Owner: %s") % (entry.owner or T("unknown")),
        ]
        if entry.link_target:
            lines.append(T("Link target: %s") % entry.link_target)
        QMessageBox.information(self, "Properties", "\n".join(lines))

    def copy_remote_path(self) -> None:
        if self.remote_pane.path:
            QApplication.clipboard().setText(self.remote_pane.path)
            self.status.showMessage(T("Remote path copied"), 3000)

    def swap_panes(self) -> None:
        """Exchange the two panes left-for-left, keeping their own widths.

        Only reversing the splitter widths is a no-op when both panes are the
        same size, which is the default - so the widgets themselves are moved.
        """
        splitter = self.site_splitter
        if splitter.count() < 2:
            return
        left, right = splitter.widget(0), splitter.widget(1)
        left_width, right_width = splitter.sizes()
        left.setParent(None)
        right.setParent(None)
        # re-insert in the opposite order, carrying each pane's width with it
        splitter.insertWidget(0, right)
        splitter.insertWidget(1, left)
        splitter.setSizes([right_width, left_width])
        splitter.widget(0).setFocus()
        self.status.showMessage(T("Panes swapped"), 2500)

    def clear_log(self) -> None:
        self.log_view.clear()

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", "bluebird-log.txt", "Text files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.log_view.toPlainText())
        except OSError as exc:
            QMessageBox.warning(self, "Save log", human_error(exc))
            return
        self.status.showMessage(T("Log saved to %s") % path, 5000)

    def show_shortcuts(self) -> None:
        rows = [
            ("Ctrl+N", "Connect to a server"),
            ("Ctrl+D", "Disconnect"),
            ("Ctrl+Shift+S", "Site manager"),
            ("F5", "Refresh both panes"),
            ("F2", "Rename the selected item"),
            ("F7", "Create a directory"),
            ("Del", "Delete the selection"),
            ("Ctrl+U", "Upload the local selection"),
            ("Ctrl+W", "Download the remote selection"),
            ("Ctrl+P", "Pause or resume the queue"),
            ("Ctrl+L", "Show the transfer queue"),
            ("Ctrl+H", "Show or hide hidden files"),
            ("Ctrl+,", "Preferences"),
            ("Ctrl+Shift+X", "Swap the two panes"),
            ("Alt+Up", "Go to the parent directory"),
            ("Backspace", "Go back in the path history"),
            ("Ctrl+Q", "Quit"),
        ]
        width = max(len(keys) for keys, _ in rows)
        text = "\n".join("%-*s  %s" % (width, keys, T(desc))
                          for keys, desc in rows)
        QMessageBox.information(self, "Keyboard shortcuts", text)

    # ------------------------------------------------------------------
    # help
    # ------------------------------------------------------------------
    def open_manual(self) -> None:
        """Open the bundled user manual (in-app window, browser fallback)."""
        from .manual import ManualWindow, manual_html, open_with_system, \
            web_engine_available
        if manual_html() is None:
            QMessageBox.information(
                self, "User manual",
                T("The manual file was not found in this installation."))
            return
        if web_engine_available():
            if self._manual_window is None:
                self._manual_window = ManualWindow(self)
            self._manual_window.show()
            self._manual_window.raise_()
            self._manual_window.activateWindow()
            return
        # no web engine: hand the HTML to the system browser
        if not open_with_system(manual_html()):
            self.open_manual_pdf()

    def open_manual_pdf(self) -> None:
        from .manual import (manual_html, manual_markdown, manual_pdf,
                             open_with_system)
        target = manual_pdf()
        if target and open_with_system(target):
            return
        fallback = manual_markdown()
        if fallback and open_with_system(fallback):
            return
        html = manual_html()
        if html and open_with_system(html):
            return
        QMessageBox.information(self, "User manual",
                                T("No manual file could be opened."))

    def open_docs_folder(self) -> None:
        """Reveal the folder that holds the manual and screenshots."""
        from .manual import open_with_system
        from .resources import resource_root
        folder = os.path.join(resource_root(), "docs")
        if not os.path.isdir(folder):
            folder = resource_root()
        if not open_with_system(folder):
            QMessageBox.information(self, "Documentation",
                                    T("Could not open %s") % folder)

    def show_about(self) -> None:
        from . import __appname_cn__
        name = self._product_title()
        QMessageBox.about(
            self, T("About %s") % name,
            "<h3>%s %s</h3>"
            "<p style='color:#5C6B7A'>%s</p>"
            "<p>%s</p>"
            "<p>%s</p>"
            "<p style='color:#8A8072'>%s<br>Python %s</p>"
            % (name, __version__,
               # the Chinese name is the product name, not a translation of it
               "%s \u2014 %s" % (__appname_cn__,
                                 T("the blue bird that carries letters"))
               if name.startswith(__appname_cn__) else
               T("BlueBird is the bird that carried letters"),
               T("A cream-themed FTP / FTPS / SFTP client built with PyQt5, "
                 "PyQtWebEngine and paramiko."),
               T("Every colour is yours to change: open "
                 "View \u2014 Preferences \u2014 Colours."),
               T("Author: %s") % __author__,
               sys.version.split()[0]))

    # ------------------------------------------------------------------
    # handlers table for the menu
    # ------------------------------------------------------------------
    def _handlers(self) -> Dict[str, Any]:
        return {
            "connect": self.open_connect_dialog,
            "site_manager": self.open_site_manager,
            "disconnect": self.disconnect_server,
            "refresh_both": self.refresh_both,
            "refresh_local": lambda: self.local_pane.refresh(force=True),
            "refresh_remote": lambda: self.remote_pane.refresh(force=True),
            "remote_mkdir": self.remote_mkdir,
            "remote_rename": self.remote_rename,
            "remote_delete": self.remote_delete,
            "upload": self.upload_selection,
            "download": self.download_selection,
            "pause_queue": self.toggle_pause_queue,
            "retry_failed": self.retry_failed,
            "clear_queue": self.clear_finished_transfers,
            "goto_queue": self.show_queue,
            "show_hidden": self.set_show_hidden,
            "autofit_names": self.set_auto_fit_names,
            "show_permissions": lambda checked: self.set_column_visible(
                "permissions", checked),
            "show_owner": lambda checked: self.set_column_visible(
                "owner", checked),
            "fetch_sizes": self.fetch_missing_sizes,
            "preferences": self.open_preferences,
            "swap_panes": self.swap_panes,
            "edit_remote": self.edit_remote_file,
            "copy_url": self.copy_remote_path,
            "clear_log": self.clear_log,
            "open_log_file": self.save_log,
            "manual": self.open_manual,
            "manual_pdf": self.open_manual_pdf,
            "manual_folder": self.open_docs_folder,
            "shortcuts": self.show_shortcuts,
            "about": self.show_about,
            "quit": self.close,
        }

    def refresh_both(self) -> None:
        self.local_pane.refresh(force=True)
        if self.session is not None and self.session.connected:
            self.remote_pane.refresh(force=True)

    def set_show_hidden(self, checked: bool) -> None:
        self.settings.set("appearance", "show_hidden", bool(checked))
        for pane in (self.local_pane, self.remote_pane):
            pane.header.hidden_button.setChecked(bool(checked))
            pane.model.set_show_hidden(bool(checked))
            pane._update_status()

    def set_column_visible(self, which: str, checked: bool) -> None:
        """Show or hide the Permissions / Owner columns."""
        key = "show_permissions" if which == "permissions" else "show_owner"
        self.settings.set("appearance", key, bool(checked))
        for pane in (self.local_pane, self.remote_pane):
            pane._apply_column_visibility()

    def set_auto_fit_names(self, checked: bool) -> None:
        """Name columns stay at a fixed width unless this is switched on."""
        self.settings.set("appearance", "auto_fit_name_column", bool(checked))
        for pane in (self.local_pane, self.remote_pane):
            if checked:
                pane.autofit_name_column()
            else:
                saved = self.settings.get("appearance", "column_widths", {}) or {}
                try:
                    pane.table.set_name_column_width(int(saved.get("name", 260)))
                except (TypeError, ValueError):
                    pane.table.set_name_column_width(260)
        self.status.showMessage(
            T("Name column: %s") % (T("auto-fit to contents") if checked
                                    else T("fixed width")), 4000)

    def _sync_view_menu(self) -> None:
        if not hasattr(self, "menu"):
            return
        self.menu.actions["show_hidden"].setChecked(
            bool(self.settings.get("appearance", "show_hidden", True)))
        self.menu.actions["autofit_names"].setChecked(
            bool(self.settings.get("appearance", "auto_fit_name_column", False)))
        self.menu.actions["show_permissions"].setChecked(
            bool(self.settings.get("appearance", "show_permissions", False)))
        self.menu.actions["show_owner"].setChecked(
            bool(self.settings.get("appearance", "show_owner", False)))

    def fetch_missing_sizes(self) -> None:
        """Ask the server for any file sizes the listing did not include."""
        if self.session is None or not self.session.connected:
            QMessageBox.information(self, "Not connected",
                                    T("Connect to a server first."))
            return
        pending = self.remote_pane.model.entries_without_size()
        if not pending:
            self.status.showMessage(T("Every file size is already known"), 4000)
            return
        self.log("info", "Reading %d missing file size(s)..." % len(pending))
        self.remote_pane.fetch_missing_sizes()

    def open_preferences(self, start_page: int = 0) -> None:
        dialog = PreferencesDialog(self.settings, self.theme, self.icons, self)
        dialog.palette_preview.connect(self._preview_palette)
        dialog.preferences_applied.connect(self._on_preferences_applied)
        if start_page:
            dialog.nav.setCurrentRow(start_page)
        dialog.exec_()
        if getattr(dialog, "_language_changed", False):
            self.retranslate()
            self.open_preferences(getattr(dialog, "_reopen_at", 0))

    def _preview_palette(self, palette: Dict[str, str]) -> None:
        self.theme._palette = dict(palette)
        self.theme.changed.emit()

    def _on_preferences_applied(self) -> None:
        self.theme.reload(notify=True)
        self.manager.log.emit("info", "Preferences saved")

    # ------------------------------------------------------------------
    # window events
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() == Qt.Key_Backspace:
            pane = self._focused_pane()
            if pane is not None and not pane.local:
                pane.path_bar.go_back()
                return
        super(MainWindow, self).keyPressEvent(event)

    def _focused_pane(self) -> Optional[FilePane]:
        widget = QApplication.focusWidget()
        while widget is not None:
            if widget is self.local_pane:
                return self.local_pane
            if widget is self.remote_pane:
                return self.remote_pane
            widget = widget.parentWidget()
        return None

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        pending = self.manager.active() + sum(
            1 for i in self.manager.items if i.status in ("queued", "starting"))
        if pending:
            answer = QMessageBox.question(
                self, "Quit",
                T("%d transfer(s) are still pending.") % pending
                + "\n\n" + T("Quit anyway?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self._closing = True
        self._flush_timer.stop()
        self._finished_uids = []
        self._save_state()
        self.local_pane._cancel_size_fetch()
        self.remote_pane._cancel_size_fetch()
        self.manager.shutdown()
        if self.session is not None:
            try:
                self.session.disconnect()
            except Exception:
                pass
        self.theme.cleanup()
        event.accept()
