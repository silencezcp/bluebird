"""Dialogs: connect, site manager, preferences (with the colour editor)."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                             QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QFrame, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QScrollArea,
                             QSizePolicy, QSlider, QSpinBox, QStackedWidget,
                             QTableWidget, QTableWidgetItem, QTabWidget,
                             QToolButton, QVBoxLayout, QWidget)

from . import config as _config
from . import session as _session
from .i18n import LANGUAGE_NAMES, T, i18n
from .widgets import LogView, PathBar


# ---------------------------------------------------------------------------
# Connect dialog
# ---------------------------------------------------------------------------

class ConnectDialog(QDialog):
    """Collects the parameters for one connection."""

    def __init__(self, settings: Any, parent: QWidget = None,
                 values: Optional[Dict[str, Any]] = None,
                 icons: Any = None) -> None:
        super(ConnectDialog, self).__init__(parent)
        self.settings = settings
        self.icons = icons
        self._name_touched = False
        self._existing_section = ""
        self.setWindowTitle(T("Connect to server"))
        self.setMinimumWidth(500)
        values = dict(values or {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(T("Connect to a server"), self)
        heading.setObjectName("Heading")
        layout.addWidget(heading)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)

        # --- connection name ------------------------------------------
        name_row = QWidget(self)
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(4)
        self.name_edit = QLineEdit(name_row)
        self.name_edit.setPlaceholderText(T("Required — e.g. Production web server"))
        self.name_edit.textEdited.connect(self._on_name_edited)
        name_layout.addWidget(self.name_edit, 1)
        name_hint = QToolButton(name_row)
        if icons is not None:
            name_hint.setIcon(icons.action_icon("refresh", size=16))
        else:
            name_hint.setText("↺")
        name_hint.setToolTip(T("Restore the suggested name (user@host)"))
        name_hint.setCursor(Qt.PointingHandCursor)
        name_hint.setAutoRaise(True)
        name_hint.clicked.connect(self._reset_name)
        name_layout.addWidget(name_hint)
        self.name_label = QLabel(T("Connection name"), self)
        form.addRow(self.name_label, name_row)

        self.protocol = QComboBox(self)
        self.protocol.addItem(T("FTP - File Transfer Protocol"), "ftp")
        self.protocol.addItem(T("FTPS - FTP over explicit TLS"), "ftps")
        self.protocol.addItem(T("SFTP - SSH File Transfer Protocol"), "sftp")
        self.protocol.currentIndexChanged.connect(self._on_protocol)
        form.addRow(T("Protocol"), self.protocol)

        self.host = QLineEdit(self)
        self.host.setPlaceholderText("ftp.example.com or 192.168.1.10")
        self.host.textChanged.connect(self._refresh_default_name)
        form.addRow(T("Host"), self.host)

        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(21)
        self.port.valueChanged.connect(self._refresh_default_name)
        form.addRow(T("Port"), self.port)

        self.user = QLineEdit(self)
        self.user.setPlaceholderText("anonymous")
        self.user.textChanged.connect(self._refresh_default_name)
        form.addRow(T("User"), self.user)

        password_row = QWidget(self)
        password_layout = QHBoxLayout(password_row)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(4)
        self.password = QLineEdit(password_row)
        self.password.setEchoMode(QLineEdit.Password)
        self.password_toggle = QToolButton(password_row)
        self.password_toggle.setCheckable(True)
        self.password_toggle.setCursor(Qt.PointingHandCursor)
        self.password_toggle.setToolTip(T("Show password"))
        if icons is not None:
            self.password_toggle.setIcon(icons.action_icon("eye", size=17))
            self.password_toggle.setIconSize(QSize(17, 17))
        else:
            self.password_toggle.setText("Show")
        self.password_toggle.toggled.connect(self._toggle_password)
        password_layout.addWidget(self.password, 1)
        password_layout.addWidget(self.password_toggle)
        form.addRow(T("Password"), password_row)

        key_row = QWidget(self)
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(4)
        self.key_file = QLineEdit(key_row)
        self.key_file.setPlaceholderText(T("Optional OpenSSH private key"))
        browse = QPushButton("…", key_row)
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse_key)
        key_layout.addWidget(self.key_file, 1)
        key_layout.addWidget(browse)
        self.key_label = QLabel(T("Private key"), self)
        form.addRow(self.key_label, key_row)

        layout.addLayout(form)

        options = QGroupBox(T("Options"), self)
        options_layout = QVBoxLayout(options)
        self.anonymous = QCheckBox(T("Log in anonymously"), options)
        self.anonymous.toggled.connect(self._on_anonymous)
        self.save_site = QCheckBox(T("Save this connection to config.ini"), options)
        self.save_site.setChecked(True)
        self.save_site.setToolTip(T(
            "Connections are stored in the local config.ini so you can "
            "reconnect with one click"))
        options_layout.addWidget(self.anonymous)
        options_layout.addWidget(self.save_site)
        layout.addWidget(options)

        from .config import default_config_path
        self.storage_hint = QLabel(T("Saved to %s") % default_config_path(), self)
        self.storage_hint.setObjectName("Hint")
        self.storage_hint.setWordWrap(True)
        layout.addWidget(self.storage_hint)

        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
                                   self)
        buttons.button(QDialogButtonBox.Ok).setText(T("Connect"))
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_values(values)
        self._on_protocol()
        self.host.setFocus()

    # -- helpers --------------------------------------------------------
    def _on_name_edited(self, _text: str) -> None:
        self._name_touched = True

    def _reset_name(self) -> None:
        self._name_touched = False
        self.name_edit.setText(self._suggested_name())
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _suggested_name(self) -> str:
        from .config import default_connection_name
        return default_connection_name({
            "user": self.user.text().strip() or "anonymous",
            "host": self.host.text().strip() or "server",
            "port": int(self.port.value()),
            "protocol": self.protocol.currentData(),
        })

    def _refresh_default_name(self) -> None:
        """Keep the suggested name in step until the user types their own."""
        if self._name_touched:
            return
        self.name_edit.setText(self._suggested_name())

    def _apply_values(self, values: Dict[str, Any]) -> None:
        protocol = str(values.get("protocol", "ftp") or "ftp").lower()
        index = self.protocol.findData(protocol)
        if index >= 0:
            self.protocol.setCurrentIndex(index)
        self.host.setText(str(values.get("host", "") or ""))
        default_port = _session.default_port(protocol)
        self.port.setValue(int(values.get("port", default_port) or default_port))
        self.user.setText(str(values.get("user", "") or ""))
        self.password.setText(str(values.get("password", "") or ""))
        self.key_file.setText(str(values.get("key_filename", "") or ""))
        self.save_site.setChecked(True)
        existing = str(values.get("name", "") or "").strip()
        if existing:
            self._name_touched = True
            self.name_edit.setText(existing)
        else:
            self._name_touched = False
            self.name_edit.setText(self._suggested_name())
        # remember which stored connection this dialog is editing
        self._existing_section = str(values.get("section", "") or "")

    def _on_protocol(self) -> None:
        protocol = self.protocol.currentData()
        sftp = protocol == "sftp"
        self.key_file.setVisible(sftp)
        self.key_label.setVisible(sftp)
        default_port = _session.default_port(protocol)
        if self.port.value() in (21, 22):
            self.port.setValue(default_port)
        self.password.setPlaceholderText(
            "Optional when using a key" if sftp else "")
        self._on_anonymous(self.anonymous.isChecked())

    def _on_anonymous(self, checked: bool) -> None:
        if checked:
            self.user.setText("anonymous")
            self.user.setEnabled(False)
            self.password.setEnabled(False)
        else:
            self.user.setEnabled(True)
            self.password.setEnabled(True)

    def _toggle_password(self, checked: bool) -> None:
        self.password.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.password_toggle.setToolTip(
            "Hide password" if checked else "Show password")
        if self.icons is not None:
            self.password_toggle.setIcon(
                self.icons.action_icon("eye_off" if checked else "eye", size=17))

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, T("Select private key"), os.path.expanduser("~"),
            "Key files (*.pem *.key id_rsa id_ed25519 id_ecdsa);;All files (*)")
        if path:
            self.key_file.setText(path)

    def _fail(self, message: str) -> None:
        self.error.setText(message)
        self.error.setStyleSheet(
            "color: %s;" % _config.DEFAULT_PALETTE["danger"])
        self.error.setVisible(True)

    # -- results --------------------------------------------------------
    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self._fail(T("Please give this connection a name — it is how the "
                         "connection is stored and listed."))
            self.name_edit.setFocus()
            return
        if not self.host.text().strip():
            self._fail(T("Please enter a host name."))
            self.host.setFocus()
            return
        self.error.setVisible(False)
        super(ConnectDialog, self).accept()

    def config(self) -> Dict[str, Any]:
        protocol = self.protocol.currentData()
        return {
            "name": self.name_edit.text().strip() or self._suggested_name(),
            "section": self._existing_section,
            "protocol": protocol,
            "host": self.host.text().strip(),
            "port": int(self.port.value()),
            "user": self.user.text().strip(),
            "password": self.password.text(),
            "key_filename": self.key_file.text().strip(),
            "passive": bool(self.settings.get("sessions", "passive", True)),
            "timeout": float(self.settings.get("sessions", "timeout", 30) or 30),
            "keepalive": float(self.settings.get("sessions", "keepalive", 30) or 30),
            "verify_host_key": bool(
                self.settings.get("sessions", "verify_host_key", False)),
            "encoding": str(self.settings.get("sessions", "encoding", "utf-8")),
            "preserve_timestamps": bool(
                self.settings.get("transfers", "preserve_timestamps", False)),
        }

    def site(self) -> Dict[str, Any]:
        """The record written into ``config.ini``."""
        return self.config()


# ---------------------------------------------------------------------------
# Site manager
# ---------------------------------------------------------------------------

class SiteManagerDialog(QDialog):
    """Lists, renames and deletes the connections stored in ``config.ini``."""

    def __init__(self, settings: Any, parent: QWidget = None) -> None:
        super(SiteManagerDialog, self).__init__(parent)
        self.settings = settings
        self.setWindowTitle(T("Site manager — saved connections"))
        self.resize(620, 420)
        self.selected_site: Optional[Dict[str, Any]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel(T("Saved connections"), self)
        heading.setObjectName("Heading")
        layout.addWidget(heading)

        from .config import default_config_path
        self.path_hint = QLabel(T("Stored in %s") % default_config_path(), self)
        self.path_hint.setObjectName("Hint")
        self.path_hint.setWordWrap(True)
        layout.addWidget(self.path_hint)

        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.connect_button = QPushButton(T("Connect"), self)
        self.connect_button.setObjectName("Primary")
        self.rename_button = QPushButton(T("Rename…"), self)
        self.delete_button = QPushButton(T("Delete"), self)
        self.close_button = QPushButton(T("Close"), self)
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.connect_button.clicked.connect(self.accept)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.close_button.clicked.connect(self.reject)
        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        entries = self.settings.sites()
        for site in entries:
            protocol = str(site.get("protocol", "ftp")).upper()
            label = "%s      %s  %s@%s:%s" % (
                site.get("name", "?"), protocol, site.get("user") or "anonymous",
                site.get("host", ""), site.get("port", ""))
            item = QListWidgetItem(label, self.list)
            item.setData(Qt.UserRole, site)
            tip = [T("Name: %s") % site.get("name", "?"),
                   T("Protocol: %s") % protocol,
                   T("Host: %s") % site.get("host", ""),
                   T("Port: %s") % site.get("port", ""),
                   T("User: %s") % (site.get("user") or "anonymous"),
                   T("Password: %s") % (T("saved") if site.get("password") else T("not saved"))]
            if site.get("key_filename"):
                tip.append(T("Key: %s") % site["key_filename"])
            item.setToolTip("\n".join(tip))
            if site.get("key_filename"):
                item.setIcon(self.style().standardIcon(
                    self.style().SP_DriveNetIcon))
        if self.list.count():
            self.list.setCurrentRow(0)
        self.rename_button.setEnabled(bool(entries))
        self.delete_button.setEnabled(bool(entries))

    def _current(self) -> Optional[Dict[str, Any]]:
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _rename(self) -> None:
        site = self._current()
        if site is None:
            return
        old = str(site.get("name", ""))
        new_name, ok = QInputDialog.getText(
            self, T("Rename connection"), T("Connection name:"), text=old)
        if not ok or not new_name.strip() or new_name.strip() == old:
            return
        if not self.settings.connections.rename(old, new_name.strip()):
            QMessageBox.warning(self, T("Rename connection"),
                                T("Could not rename “%s”.") % old)
            return
        self._reload()

    def _delete(self) -> None:
        site = self._current()
        if site is None:
            return
        answer = QMessageBox.question(
            self, T("Delete connection"),
            T("Remove “%s” from config.ini?") % site.get("name", ""),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.settings.delete_site(str(site.get("name", "")))
            self._reload()

    def accept(self) -> None:
        site = self._current()
        if site is None:
            QMessageBox.information(self, T("Site manager"),
                                    T("Select a saved connection first."))
            return
        self.selected_site = site
        super(SiteManagerDialog, self).accept()


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class ColorTable(QTableWidget):
    """Two-column colour editor with live preview."""

    def __init__(self, parent: QWidget = None) -> None:
        super(ColorTable, self).__init__(0, 3, parent)
        self.setHorizontalHeaderLabels(["Element", "Colour", ""])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setIconSize(QSize(18, 18))
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.setColumnWidth(1, 110)
        self.setColumnWidth(2, 42)
        self.verticalHeader().setDefaultSectionSize(30)


class PreferencesDialog(QDialog):
    """Appearance (including every colour), transfers and connection settings."""

    palette_preview = pyqtSignal(dict)
    preferences_applied = pyqtSignal()

    def __init__(self, settings: Any, theme: Any, icons: Any,
                 parent: QWidget = None) -> None:
        super(PreferencesDialog, self).__init__(parent)
        self.settings = settings
        self.theme = theme
        self.icons = icons
        self.setWindowTitle(T("Preferences"))
        self.resize(820, 620)
        self._original_palette = settings.palette
        self._palette = settings.palette
        self._loading = False
        #: set when the user switched language; the caller reopens the dialog
        self._language_changed = False
        self._reopen_at = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.nav = QListWidget(self)
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget(self)
        body.addWidget(self.nav)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        self._add_page(T("General"), self._build_general())
        self._add_page(T("Appearance"), self._build_appearance())
        self._add_page(T("Colours"), self._build_colors())
        self._add_page(T("Transfers"), self._build_transfers())
        self._add_page(T("Connection"), self._build_connection())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply,
            self)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_settings)
        outer.addWidget(buttons)

        self._load_values()

    # -- page scaffolding ----------------------------------------------
    def _add_page(self, title: str, widget: QWidget) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        self.stack.addWidget(scroll)
        self.nav.addItem(QListWidgetItem(title, self.nav))

    def _page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 10, 4)
        layout.setSpacing(12)
        return page

    @staticmethod
    def _form() -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        return form

    # -- General --------------------------------------------------------
    def _build_general(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        language = QGroupBox(T("Language"), page)
        language_form = self._form()
        self.language_combo = QComboBox(language)
        for code, label in LANGUAGE_NAMES:
            self.language_combo.addItem(label, code)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        language_form.addRow(T("Interface language"), self.language_combo)
        language_note = QLabel(T("Takes effect immediately, no restart needed."),
                               language)
        language_note.setObjectName("Hint")
        language_note.setWordWrap(True)
        language_form.addRow("", language_note)
        language.setLayout(language_form)
        layout.addWidget(language)

        behavior = QGroupBox(T("Behaviour"), page)
        form = self._form()
        self.double_click = QComboBox(behavior)
        self.double_click.addItem(T("Open the folder / transfer the file"), "open")
        self.double_click.addItem(T("Always transfer"), "transfer")
        form.addRow(T("Double click"), self.double_click)

        self.confirm_delete = QCheckBox(T("Ask before deleting files"), behavior)
        form.addRow("", self.confirm_delete)
        self.confirm_overwrite = QCheckBox(T("Ask before overwriting files"), behavior)
        form.addRow("", self.confirm_overwrite)
        self.remember_dirs = QCheckBox(T("Reopen the last used directories"), behavior)
        form.addRow("", self.remember_dirs)
        behavior.setLayout(form)
        layout.addWidget(behavior)

        startup = QGroupBox(T("Startup"), page)
        startup_form = self._form()
        self.start_dir = QLineEdit(startup)
        browse = QPushButton(T("Browse…"), startup)
        browse.clicked.connect(self._browse_start_dir)
        row = QWidget(startup)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self.start_dir, 1)
        row_layout.addWidget(browse)
        startup_form.addRow(T("Local folder"), row)

        self.log_lines = QSpinBox(startup)
        self.log_lines.setRange(100, 20000)
        self.log_lines.setSingleStep(100)
        startup_form.addRow(T("Log lines kept"), self.log_lines)
        startup.setLayout(startup_form)
        layout.addWidget(startup)
        layout.addStretch(1)
        return page

    def _on_language_changed(self) -> None:
        """Apply the new language straight away, then rebuild this dialog."""
        if self._loading:
            return
        code = self.language_combo.currentData()
        page_index = self.stack.currentIndex()
        if code == i18n.language:
            return
        self.settings.set("appearance", "language", code)
        self.palette_preview.emit(dict(self._palette))
        from . import i18n as _i18n
        _i18n.set_language(code)
        _i18n.apply_locale()
        # the labels of an already-built dialog cannot all follow, so reopen
        self._reopen_at = page_index
        self._language_changed = True
        self.accept()

    def _browse_start_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose the local start folder", self.start_dir.text() or
            os.path.expanduser("~"))
        if path:
            self.start_dir.setText(path)

    # -- Appearance -----------------------------------------------------
    def _build_appearance(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        presets = QGroupBox(T("Theme preset"), page)
        preset_layout = QVBoxLayout(presets)
        self.preset_combo = QComboBox(presets)
        for name in _config.PRESETS:
            self.preset_combo.addItem(name, name)
        preset_layout.addWidget(self.preset_combo)
        self.preset_button = QPushButton(T("Apply preset"), presets)
        self.preset_button.clicked.connect(self._apply_preset)
        preset_layout.addWidget(self.preset_button)
        hint = QLabel(T("Presets replace the whole palette; tweak individual "
                        "colours on the Colours page."), presets)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        preset_layout.addWidget(hint)
        layout.addWidget(presets)

        fonts = QGroupBox(T("Fonts and sizes"), page)
        form = self._form()
        self.font_family = QComboBox(fonts)
        self.font_family.addItem(T("(platform default)"), "")
        for family in QFontDatabase().families():
            self.font_family.addItem(family, family)
        self.font_family.setEditable(False)
        form.addRow(T("Interface font"), self.font_family)

        self.font_size = QSpinBox(fonts)
        self.font_size.setRange(0, 24)
        self.font_size.setSpecialValueText("default")
        form.addRow(T("Font size"), self.font_size)

        self.row_height = QSlider(Qt.Horizontal, fonts)
        self.row_height.setRange(18, 48)
        form.addRow(T("Row height"), self.row_height)

        self.icon_size = QSlider(Qt.Horizontal, fonts)
        self.icon_size.setRange(12, 32)
        form.addRow(T("Icon size"), self.icon_size)

        self.alternating = QCheckBox(T("Alternating row colours"), fonts)
        form.addRow("", self.alternating)
        self.grid_lines = QCheckBox(T("Show grid lines"), fonts)
        form.addRow("", self.grid_lines)
        fonts.setLayout(form)
        layout.addWidget(fonts)
        layout.addStretch(1)
        return page

    def _apply_preset(self) -> None:
        name = self.preset_combo.currentData()
        preset = _config.PRESETS.get(name)
        palette = dict(_config.DEFAULT_PALETTE)
        if preset:
            palette.update(preset)
        self._palette = palette
        self._populate_colors()
        self.palette_preview.emit(dict(self._palette))

    # -- Colours --------------------------------------------------------
    def _build_colors(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        top = QHBoxLayout()
        self.color_search = QLineEdit(page)
        self.color_search.setPlaceholderText(T("Search colours…"))
        self.color_search.textChanged.connect(self._filter_colors)
        top.addWidget(self.color_search, 1)
        reset_button = QPushButton(T("Reset all"), page)
        reset_button.clicked.connect(self._reset_colors)
        top.addWidget(reset_button)
        layout.addLayout(top)

        self.color_table = ColorTable(page)
        self.color_table.itemSelectionChanged.connect(self._on_color_selected)
        layout.addWidget(self.color_table, 1)

        editor = QGroupBox(T("Selected colour"), page)
        editor_layout = QHBoxLayout(editor)
        self.color_swatch = QLabel(editor)
        self.color_swatch.setObjectName("Swatch")
        self.color_swatch.setFixedSize(46, 28)
        editor_layout.addWidget(self.color_swatch)
        self.color_hex = QLineEdit(editor)
        self.color_hex.setMaxLength(7)
        self.color_hex.setFixedWidth(100)
        self.color_hex.editingFinished.connect(self._on_hex_edited)
        editor_layout.addWidget(self.color_hex)
        pick = QPushButton(T("Pick…"), editor)
        pick.clicked.connect(self._pick_color)
        editor_layout.addWidget(pick)
        self.color_reset_one = QPushButton(T("Reset"), editor)
        self.color_reset_one.clicked.connect(self._reset_selected_color)
        editor_layout.addWidget(self.color_reset_one)
        editor_layout.addStretch(1)
        layout.addWidget(editor)

        self.color_warning = QLabel("", page)
        self.color_warning.setWordWrap(True)
        layout.addWidget(self.color_warning)

        rules = QLabel(T(
            "Folders default to blue and files keep the normal text colour. "
            "Pick any values you like — but keep them clearly different so the "
            "two are easy to tell apart at a glance."), page)
        rules.setObjectName("Hint")
        rules.setWordWrap(True)
        layout.addWidget(rules)
        return page

    def _populate_colors(self) -> None:
        self._loading = True
        table = self.color_table
        table.setRowCount(0)
        rows: List[Tuple[str, str]] = []
        for group, items in _config.COLOR_GROUPS:
            for key, label in items:
                rows.append((key, "%s · %s" % (group, label)))
        for key, label in _config.DEFAULT_PALETTE.items():
            if not any(key == existing for existing, _ in rows):
                rows.append((key, key))
        for key, label in rows:
            row = table.rowCount()
            table.insertRow(row)
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.UserRole, key)
            table.setItem(row, 0, name_item)
            value = self._palette.get(key, _config.DEFAULT_PALETTE.get(key, "#000000"))
            value_item = QTableWidgetItem(value.upper())
            value_item.setForeground(QColor(value))
            table.setItem(row, 1, value_item)
            swatch = QTableWidgetItem()
            swatch.setIcon(self._swatch_icon(value))
            table.setItem(row, 2, swatch)
        self._loading = False
        if table.rowCount():
            table.selectRow(0)
        self._sync_editor()
        self._validate_colors()

    def _swatch_icon(self, value: str) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(QColor(value))
        painter = QPainter(pixmap)
        painter.setPen(QColor(self.theme.color("border_strong")))
        painter.drawRect(0, 0, 17, 17)
        painter.end()
        return QIcon(pixmap)

    def _sync_editor(self) -> None:
        """Mirror the selected row into the hex field and the big swatch."""
        key = self._current_color_key()
        if key is None:
            return
        value = self._palette.get(key, "#000000")
        self.color_hex.setText(value.upper())
        self.color_swatch.setStyleSheet(
            "background-color: %s; border: 1px solid %s; border-radius: 6px;"
            % (value, self.theme.color("border_strong")))

    def _filter_colors(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for row in range(self.color_table.rowCount()):
            item = self.color_table.item(row, 0)
            visible = not needle or needle in (item.text().lower() if item else "")
            self.color_table.setRowHidden(row, not visible)

    def _current_color_key(self) -> Optional[str]:
        row = self.color_table.currentRow()
        if row < 0:
            return None
        item = self.color_table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_color_selected(self) -> None:
        self._sync_editor()

    def _set_color(self, key: str, value: str) -> None:
        color = QColor(value)
        if not color.isValid():
            return
        normalised = color.name().upper()
        self._palette[key] = normalised
        for row in range(self.color_table.rowCount()):
            item = self.color_table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == key:
                value_item = self.color_table.item(row, 1)
                if value_item is not None:
                    value_item.setText(normalised)
                    value_item.setForeground(QColor(normalised))
                swatch = self.color_table.item(row, 2)
                if swatch is not None:
                    swatch.setIcon(self._swatch_icon(normalised))
                break
        self._sync_editor()
        self.palette_preview.emit(dict(self._palette))
        self._validate_colors()

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super(PreferencesDialog, self).showEvent(event)
        # the first row is selected while the table is still hidden, so make
        # sure the swatch and hex field agree with it once we are visible
        self._sync_editor()

    def _pick_color(self) -> None:
        key = self._current_color_key()
        if key is None:
            return
        initial = QColor(self._palette.get(key, "#000000"))
        color = QColorDialog.getColor(initial, self, "Choose colour")
        if color.isValid():
            self._set_color(key, color.name())

    def _on_hex_edited(self) -> None:
        key = self._current_color_key()
        if key is None:
            return
        text = self.color_hex.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        color = QColor(text)
        if color.isValid():
            self._set_color(key, color.name())
        else:
            self.color_hex.setText(self._palette.get(key, "#000000").upper())

    def _reset_selected_color(self) -> None:
        key = self._current_color_key()
        if key is None:
            return
        default = _config.DEFAULT_PALETTE.get(key)
        if default:
            self._set_color(key, default)

    def _reset_colors(self) -> None:
        self._palette = dict(_config.DEFAULT_PALETTE)
        self._populate_colors()
        self.palette_preview.emit(dict(self._palette))

    def _validate_colors(self) -> None:
        """Folders and files must stay visually distinct."""
        folder = self._palette.get("folder", "#000000")
        file_color = self._palette.get("file", "#000000")
        link = self._palette.get("link", "#000000")
        surface = self._palette.get("surface", "#FFFFFF")
        messages: List[str] = []
        if _config.color_distance(folder, file_color) < 90:
            messages.append(
                "⚠ Folder and file colours are very close — folders will be "
                "hard to pick out.")
        if _config.color_distance(surface, file_color) < 90:
            messages.append("⚠ File colour has too little contrast against the "
                            "panel background.")
        if _config.color_distance(surface, folder) < 70:
            messages.append("⚠ Folder colour has too little contrast against "
                            "the panel background.")
        if _config.color_distance(folder, link) < 80:
            messages.append("⚠ Folder and symbolic-link colours look alike.")
        self.color_warning.setText("\n".join(messages))
        self.color_warning.setStyleSheet(
            "color: %s;" % self._palette.get("warning", "#C08A2E")
            if messages else "color: transparent;")

    # -- Transfers ------------------------------------------------------
    def _build_transfers(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        box = QGroupBox(T("Queue"), page)
        form = self._form()
        self.concurrency = QSpinBox(box)
        self.concurrency.setRange(1, 4)
        form.addRow(T("Simultaneous transfers"), self.concurrency)
        self.retries = QSpinBox(box)
        self.retries.setRange(0, 10)
        form.addRow(T("Automatic retries"), self.retries)
        self.preserve_timestamps = QCheckBox(T("Keep the original modification time"),
                                             box)
        form.addRow("", self.preserve_timestamps)
        box.setLayout(form)
        layout.addWidget(box)

        notification = QGroupBox(T("Notification"), page)
        notification_layout = QVBoxLayout(notification)
        self.notify_finished = QCheckBox(
            T("Show a popup when a transfer finishes"), notification)
        self.refresh_after_transfer = QCheckBox(
            T("Refresh the pane when a transfer finishes"), notification)
        notification_layout.addWidget(self.notify_finished)
        notification_layout.addWidget(self.refresh_after_transfer)
        layout.addWidget(notification)

        mode = QGroupBox(T("Transfer mode"), page)
        mode_layout = QVBoxLayout(mode)
        hint = QLabel(T("Extensions always sent as text (ASCII) or always sent "
                        "byte-for-byte (binary). Space separated."), mode)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        mode_layout.addWidget(hint)
        self.ascii_ext = QLineEdit(mode)
        mode_layout.addWidget(QLabel(T("ASCII extensions"), mode))
        mode_layout.addWidget(self.ascii_ext)
        self.binary_ext = QLineEdit(mode)
        mode_layout.addWidget(QLabel(T("Binary extensions"), mode))
        mode_layout.addWidget(self.binary_ext)
        layout.addWidget(mode)
        layout.addStretch(1)
        return page

    # -- Connection -----------------------------------------------------
    def _build_connection(self) -> QWidget:
        page = self._page()
        layout = page.layout()

        box = QGroupBox(T("Network"), page)
        form = self._form()
        self.timeout = QSpinBox(box)
        self.timeout.setRange(5, 600)
        self.timeout.setSuffix(" s")
        form.addRow(T("Connection timeout"), self.timeout)
        self.keepalive = QSpinBox(box)
        self.keepalive.setRange(0, 600)
        self.keepalive.setSuffix(" s")
        self.keepalive.setSpecialValueText("off")
        form.addRow(T("Keep-alive interval"), self.keepalive)
        self.passive = QCheckBox(T("Use passive mode (FTP/FTPS)"), box)
        form.addRow("", self.passive)
        self.verify_keys = QCheckBox(
            "Strictly verify SSH host keys (SFTP)", box)
        form.addRow("", self.verify_keys)
        self.encoding = QLineEdit(box)
        form.addRow(T("FTP encoding"), self.encoding)
        box.setLayout(form)
        layout.addWidget(box)

        note = QLabel(T(
            "Strict host-key verification refuses unknown servers. Leave it off "
            "for the first connection, then enable it once the key is known."),
            page)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    # -- load / save ----------------------------------------------------
    def _load_values(self) -> None:
        self._loading = True
        appearance = self.settings.get("appearance", default={}) or {}
        behavior = self.settings.get("behavior", default={}) or {}
        transfers = self.settings.get("transfers", default={}) or {}
        sessions = self.settings.get("sessions", default={}) or {}

        language_index = self.language_combo.findData(i18n.language)
        self.language_combo.setCurrentIndex(max(0, language_index))

        index = self.double_click.findData(behavior.get("double_click_action", "open"))
        self.double_click.setCurrentIndex(max(0, index))
        self.confirm_delete.setChecked(bool(behavior.get("confirm_delete", True)))
        self.confirm_overwrite.setChecked(bool(behavior.get("confirm_overwrite", True)))
        self.remember_dirs.setChecked(bool(behavior.get("remember_last_dirs", True)))
        self.start_dir.setText(str(behavior.get("local_start_dir", "") or ""))
        self.log_lines.setValue(int(behavior.get("log_lines", 2000) or 2000))

        family = str(appearance.get("font_family", "") or "")
        family_index = self.font_family.findData(family)
        self.font_family.setCurrentIndex(max(0, family_index))
        self.font_size.setValue(int(appearance.get("font_size", 0) or 0))
        self.row_height.setValue(int(appearance.get("row_height", 26) or 26))
        self.icon_size.setValue(int(appearance.get("icon_size", 18) or 18))
        self.alternating.setChecked(bool(appearance.get("alternating_rows", True)))
        self.grid_lines.setChecked(bool(appearance.get("grid_lines", False)))

        self.concurrency.setValue(int(transfers.get("concurrency", 2) or 2))
        self.retries.setValue(int(transfers.get("retries", 2) or 0))
        self.preserve_timestamps.setChecked(
            bool(transfers.get("preserve_timestamps", False)))
        self.notify_finished.setChecked(
            bool(transfers.get("notify_finished", True)))
        self.refresh_after_transfer.setChecked(
            bool(transfers.get("refresh_after_transfer", True)))
        self.ascii_ext.setText(str(transfers.get("ascii_extensions", "")))
        self.binary_ext.setText(str(transfers.get("binary_extensions", "")))

        self.timeout.setValue(int(sessions.get("timeout", 30) or 30))
        self.keepalive.setValue(int(sessions.get("keepalive", 30) or 30))
        self.passive.setChecked(bool(sessions.get("passive", True)))
        self.verify_keys.setChecked(bool(sessions.get("verify_host_key", False)))
        self.encoding.setText(str(sessions.get("encoding", "utf-8")))

        self._populate_colors()
        self._loading = False

    def apply_settings(self) -> None:
        """Write every page back to the settings file."""
        self.settings.update("behavior", {
            "double_click_action": self.double_click.currentData(),
            "confirm_delete": self.confirm_delete.isChecked(),
            "confirm_overwrite": self.confirm_overwrite.isChecked(),
            "remember_last_dirs": self.remember_dirs.isChecked(),
            "local_start_dir": self.start_dir.text().strip(),
            "log_lines": int(self.log_lines.value()),
        }, autosave=False)
        self.settings.update("appearance", {
            "font_family": self.font_family.currentData() or "",
            "font_size": int(self.font_size.value()),
            "row_height": int(self.row_height.value()),
            "icon_size": int(self.icon_size.value()),
            "alternating_rows": self.alternating.isChecked(),
            "grid_lines": self.grid_lines.isChecked(),
        }, autosave=False)
        self.settings.update("transfers", {
            "concurrency": int(self.concurrency.value()),
            "retries": int(self.retries.value()),
            "preserve_timestamps": self.preserve_timestamps.isChecked(),
            "notify_finished": self.notify_finished.isChecked(),
            "refresh_after_transfer": self.refresh_after_transfer.isChecked(),
            "ascii_extensions": self.ascii_ext.text().strip(),
            "binary_extensions": self.binary_ext.text().strip(),
        }, autosave=False)
        self.settings.update("sessions", {
            "timeout": int(self.timeout.value()),
            "keepalive": int(self.keepalive.value()),
            "passive": self.passive.isChecked(),
            "verify_host_key": self.verify_keys.isChecked(),
            "encoding": self.encoding.text().strip() or "utf-8",
        }, autosave=False)
        self.settings.set_palette(self._palette, autosave=False)
        self.settings.save()
        self._original_palette = dict(self._palette)
        self.preferences_applied.emit()

    def accept(self) -> None:
        self.apply_settings()
        super(PreferencesDialog, self).accept()

    def reject(self) -> None:
        self.palette_preview.emit(dict(self._original_palette))
        super(PreferencesDialog, self).reject()
