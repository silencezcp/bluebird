"""Menus and toolbar construction for the main window."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction, QMenu, QToolBar, QWidget

from .i18n import T
from .retranslate import Retranslator


def make_action(parent: QWidget, text: str, slot: Callable[..., Any] = None,
                shortcut: str = "", icon: Any = None, tip: str = "",
                checkable: bool = False, checked: bool = False) -> QAction:
    action = QAction(T(text), parent)
    if icon is not None:
        action.setIcon(icon)
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    if tip:
        action.setToolTip(T(tip))
        action.setStatusTip(T(tip))
    else:
        action.setStatusTip(T(text))
    action.setCheckable(checkable)
    if checkable:
        action.setChecked(checked)
    action.setData(text)          # the English key, for retranslation
    if slot is not None:
        action.triggered.connect(slot)
    return action


class MainMenu(object):
    """Builds the menu bar and keeps references to every action."""

    #: (action key, English text, English tooltip)
    TOOLBAR_ITEMS: List[Tuple[str, str, str]] = [
        ("connect", "Connect", "Connect to a server"),
        ("disconnect", "Disconnect", "Close the connection"),
        ("refresh_both", "Refresh", "Refresh both panes"),
        ("show_hidden", "Show hidden files", "Show or hide hidden files"),
        ("upload", "Upload", "Upload the local selection"),
        ("download", "Download", "Download the remote selection"),
        ("pause_queue", "Pause queue", "Pause or resume the transfer queue"),
        ("preferences", "Preferences", "Open the preferences"),
    ]

    def __init__(self, window: Any, handlers: Dict[str, Callable[..., Any]],
                 icons: Any) -> None:
        self.window = window
        self.handlers = handlers
        self.icons = icons
        self.actions: Dict[str, QAction] = {}
        self.menus: List[Any] = []
        self.retranslator = Retranslator()
        self._build()
        self.retranslator.bind(self.retranslate)

    # -- helpers --------------------------------------------------------
    def icon(self, name: str, size: int = 20) -> Any:
        return self.icons.action_icon(name, size=size)

    def act(self, key: str, text: str, shortcut: str = "", icon: str = "",
            tip: str = "", checkable: bool = False, checked: bool = False) -> QAction:
        action = make_action(
            self.window, text, self.handlers.get(key), shortcut,
            self.icon(icon) if icon else None, tip or text,
            checkable=checkable, checked=checked)
        self.actions[key] = action
        return action

    # -- construction ---------------------------------------------------
    def _build(self) -> None:
        bar = self.window.menuBar()

        file_menu = bar.addMenu(T("&File"))
        self.menus.append((file_menu, "&File"))
        file_menu.addAction(self.act(
            "site_manager", "&Site manager…", "Ctrl+Shift+S", "sites",
            "Manage saved connections"))
        file_menu.addAction(self.act(
            "connect", "&Connect…", "Ctrl+N", "connect"))
        self.recent_menu = file_menu.addMenu(T("Recent connections"))
        self._recent_label = "Recent connections"
        file_menu.addSeparator()
        file_menu.addAction(self.act("open_log_file", "Save &log…", "", "save"))
        file_menu.addSeparator()
        file_menu.addAction(self.act("quit", "E&xit", "Ctrl+Q", "close"))

        server_menu = bar.addMenu(T("&Server"))
        self.menus.append((server_menu, "&Server"))
        server_menu.addAction(self.act("disconnect", "&Disconnect", "Ctrl+D",
                                       "disconnect"))
        server_menu.addAction(self.act("refresh_both", "&Refresh", "F5", "refresh"))
        server_menu.addSeparator()
        server_menu.addAction(self.act("remote_mkdir", "Create &directory…",
                                       "F7", "new_folder"))
        server_menu.addAction(self.act("remote_rename", "&Rename…", "F2",
                                       "rename"))
        server_menu.addAction(self.act("remote_delete", "&Delete", "Del",
                                       "delete"))

        transfer_menu = bar.addMenu(T("&Transfer"))
        self.menus.append((transfer_menu, "&Transfer"))
        transfer_menu.addAction(self.act("upload", "&Upload →", "Ctrl+U",
                                         "upload"))
        transfer_menu.addAction(self.act("download", "← &Download", "Ctrl+W",
                                         "download"))
        transfer_menu.addSeparator()
        transfer_menu.addAction(self.act("pause_queue", "&Pause queue",
                                         "Ctrl+P", "pause", checkable=True))
        transfer_menu.addAction(self.act("retry_failed", "Re&try failed", "",
                                         "refresh"))
        transfer_menu.addAction(self.act("clear_queue", "Clear &finished", "",
                                         "clear"))
        transfer_menu.addSeparator()
        transfer_menu.addAction(self.act("goto_queue", "Show the &queue",
                                         "Ctrl+L", "queue"))

        view_menu = bar.addMenu(T("&View"))
        self.menus.append((view_menu, "&View"))
        view_menu.addAction(self.act("show_hidden", "Show &hidden files",
                                     "Ctrl+H", "eye", checkable=True,
                                     checked=True))
        view_menu.addAction(self.act("autofit_names", "Auto-fit the &name column",
                                     "", "filter", checkable=True,
                                     checked=False))
        view_menu.addSeparator()
        view_menu.addAction(self.act("show_permissions", "Show &permissions",
                                     "", "properties", checkable=True,
                                     checked=False))
        view_menu.addAction(self.act("show_owner", "Show file &owner",
                                     "", "properties", checkable=True,
                                     checked=False))
        view_menu.addSeparator()
        view_menu.addAction(self.act("fetch_sizes", "Fetch missing file si&zes",
                                     "", "properties"))
        view_menu.addAction(self.act("refresh_local", "Refresh &local pane",
                                     "", "refresh"))
        view_menu.addAction(self.act("refresh_remote", "Refresh &remote pane",
                                     "", "refresh"))
        view_menu.addSeparator()
        view_menu.addAction(self.act("preferences", "&Preferences…", "Ctrl+,",
                                     "settings"))
        view_menu.addSeparator()
        view_menu.addAction(self.act("swap_panes", "&Swap panes", "Ctrl+Shift+X",
                                     "sync"))

        tools_menu = bar.addMenu(T("&Tools"))
        self.menus.append((tools_menu, "&Tools"))
        tools_menu.addAction(self.act("edit_remote", "&Edit remote file…", "",
                                      "edit"))
        tools_menu.addAction(self.act("copy_url", "Copy the remote &path", "",
                                      "bookmark"))
        tools_menu.addSeparator()
        tools_menu.addAction(self.act("clear_log", "Clear the &log", "", "clear"))

        help_menu = bar.addMenu(T("&Help"))
        self.menus.append((help_menu, "&Help"))
        help_menu.addAction(self.act("manual", "&User manual", "F1", "info"))
        help_menu.addAction(self.act("manual_pdf", "Open the manual as &PDF",
                                     "", "bookmark"))
        help_menu.addAction(self.act("manual_folder", "Open the &documentation "
                                                      "folder", "", "new_folder"))
        help_menu.addSeparator()
        help_menu.addAction(self.act("log_folder", "Open the &log folder",
                                     "", "log"))
        help_menu.addAction(self.act("shortcuts", "&Keyboard shortcuts",
                                     "Shift+F1", "log"))
        help_menu.addSeparator()
        help_menu.addAction(self.act("about", "&About", "", "info"))

    # -- toolbar --------------------------------------------------------
    def build_toolbar(self) -> QToolBar:
        toolbar = QToolBar(T("Main"), self.window)
        toolbar.setObjectName("MainToolBar")
        toolbar.setMovable(False)
        # icons only, with the label in the tooltip: keeps the bar compact so
        # the connection fields always have room
        toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(22, 22))
        for key, text, tip in self.TOOLBAR_ITEMS:
            toolbar.addAction(self.actions[key])
            if key in ("disconnect", "show_hidden", "pause_queue"):
                toolbar.addSeparator()
        self.toolbar = toolbar
        self._refresh_tooltips()
        return toolbar

    def _refresh_tooltips(self) -> None:
        for key, text, tip in self.TOOLBAR_ITEMS:
            action = self.actions.get(key)
            if action is None:
                continue
            shortcut = action.shortcut().toString()
            label = T(text)
            action.setToolTip("%s  —  %s" % (label, shortcut or T("no shortcut")))
            action.setStatusTip(T(tip))

    # -- retranslation ---------------------------------------------------
    def retranslate(self) -> None:
        for menu, english in self.menus:
            try:
                menu.setTitle(T(english))
            except RuntimeError:
                continue
        for key, action in self.actions.items():
            english = action.data()
            if isinstance(english, str) and english:
                action.setText(T(english))
        if getattr(self, "toolbar", None) is not None:
            try:
                self.toolbar.setWindowTitle(T("Main"))
            except RuntimeError:
                pass
        self._refresh_tooltips()

