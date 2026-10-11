"""Theme: colour palette ownership plus Qt stylesheet generation.

The theme emits :attr:`Theme.changed` whenever a colour changes, and the
stylesheets are rebuilt lazily so live editing in the settings dialog is
instant.  Importing :mod:`ftpclient.theme` does **not** need a QApplication
to exist.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Dict, List

from PyQt5.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPen,
                         QPixmap, QPolygonF)

if __name__ == "__main__" and not __package__:
    # Started directly: right-clicking this file in an IDE, or running
    # `python ftpclient/theme.py`.  Every module in this package uses relative
    # imports, which cannot work that way, and the resulting "attempted
    # relative import with no known parent package" says nothing useful.
    # Re-run the file as the module it is, from the project root.
    import os
    import runpy
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    sys.stderr.write("Starting theme.py directly; running it as "
                     "'python -m ftpclient.theme' instead.\n")
    runpy.run_module("ftpclient.theme", run_name="__main__", alter_sys=True)
    # A library module has no main block, so nothing above ran.  Say so rather
    # than exiting silently.  Start the application with run.py.
    sys.stderr.write("  (ftpclient.theme has no main entry point; "
                     "start the client with run.py)\n")
    raise SystemExit(0)
from . import config as _config

#: Filename suffixes that get the "text/code" icon.
CODE_EXTENSIONS: List[str] = [
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".java", ".go", ".rs", ".rb", ".php", ".pl",
    ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".sql", ".json", ".xml",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".html", ".htm", ".css",
    ".scss", ".less", ".vue", ".lua", ".r", ".m", ".swift", ".kt", ".vb",
]

IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
                    ".svg", ".tif", ".tiff", ".heic", ".psd", ".raw"]
ARCHIVE_EXTENSIONS = [".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2",
                      ".xz", ".iso", ".cab", ".jar", ".apk", ".deb", ".rpm"]
MEDIA_EXTENSIONS = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma",
                    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
                    ".m4v", ".mpg", ".mpeg", ".ts"]
DOC_EXTENSIONS = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".odt", ".ods", ".odp", ".rtf", ".epub", ".mobi"]
TEXT_EXTENSIONS = [".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".nfo",
                   ".srt", ".ass", ".tex", ".diff", ".patch"]


def quote_family(family: str) -> str:
    """Quote a font family for use inside a Qt stylesheet."""
    return '"%s"' % family.replace('"', "")


class Theme(QObject):
    """Holds the active palette and produces stylesheets from it."""

    changed = pyqtSignal()

    def __init__(self, settings: "_config.Settings", parent: QObject = None) -> None:
        super(Theme, self).__init__(parent)
        self._settings = settings
        self._palette: Dict[str, str] = {}
        self._asset_dir = ""
        self._check_icon = ""
        self.reload(notify=False)

    # -- palette --------------------------------------------------------
    def reload(self, notify: bool = True) -> None:
        self._palette = self._settings.palette
        for key, value in _config.DEFAULT_PALETTE.items():
            self._palette.setdefault(key, value)
        if notify:
            self.changed.emit()

    @property
    def palette(self) -> Dict[str, str]:
        return dict(self._palette)

    def color(self, key: str, fallback: str = "#000000") -> str:
        """Return the ``#rrggbb`` value for a palette key."""
        value = self._palette.get(key)
        if isinstance(value, str) and value.strip():
            return value
        return self._palette.get(fallback, fallback) if fallback else fallback

    def qcolor(self, key: str, fallback: str = "#000000") -> QColor:
        color = QColor(self.color(key, fallback))
        if not color.isValid():
            color = QColor(fallback)
        return color

    def shaded(self, key: str, toward: str, ratio: float) -> str:
        return _config.blend(self.color(key), self.color(toward), ratio)

    def set_color(self, key: str, value: str, notify: bool = True,
                  autosave: bool = True) -> None:
        palette = self._settings.palette
        palette[key] = value
        self._settings.set_palette(palette, autosave=autosave)
        self._palette = palette
        if notify:
            self.changed.emit()

    def apply_preset(self, name: str) -> None:
        self._palette = self._settings.apply_preset(name)
        self.changed.emit()

    def item_color(self, kind: str) -> str:
        """Colour used for a file-list item.

        ``folder`` / ``link`` have dedicated palette entries; everything else
        falls back to the ``file`` entry so the user only has to customise two
        colours.
        """
        if kind == "folder":
            return self.color("folder")
        if kind == "link":
            return self.color("link")
        return self.color("file")

    # -- stylesheet -----------------------------------------------------
    def stylesheet(self) -> str:
        values = dict(self._palette)
        # a few derived values the user does not have to think about
        values.setdefault("accent", _config.DEFAULT_PALETTE["accent"])
        values["check_icon"] = self.check_icon_path()
        values["arrow_down"] = self.arrow_icon_path("down")
        values["arrow_up"] = self.arrow_icon_path("up")
        values["arrow_down_accent"] = self.arrow_icon_path("down", "accent")
        values["arrow_up_accent"] = self.arrow_icon_path("up", "accent")
        values["arrow_down_muted"] = self.arrow_icon_path("down", "border_strong")
        values["arrow_up_muted"] = self.arrow_icon_path("up", "border_strong")
        values["header_line"] = self.shaded("border_strong", "text", 0.05)
        values["row_hover"] = values.get("surface_hover", "#F3EBD9")
        values["scroll_handle"] = self.shaded("border_strong", "text_muted", 0.25)
        values["scroll_handle_hover"] = self.shaded("border_strong", "text", 0.15)
        values["track"] = self.shaded("surface_sunken", "border", 0.35)
        values["menu_bg"] = self.shaded("surface", "window", 0.25)
        values["tooltip_bg"] = self.shaded("text", "window", 0.12)
        values["tooltip_text"] = values.get("surface", "#FFFCF5")
        values["header_grad_a"] = values.get("header", "#EFE8D8")
        values["header_grad_b"] = self.shaded("header", "border", 0.35)
        values["rail_bg"] = self.shaded("surface", "window", 0.55)
        sheet = _STYLESHEET
        for key, value in values.items():
            sheet = sheet.replace("{{%s}}" % key, str(value))
        # any leftover placeholder keeps the default palette value
        for key, value in _config.DEFAULT_PALETTE.items():
            sheet = sheet.replace("{{%s}}" % key, value)
        return sheet

    # -- generated assets ------------------------------------------------
    def _asset(self, name: str, builder: Any) -> str:
        """Render a small PNG once and return a stylesheet-ready path."""
        if not _has_qapp():
            return ""
        try:
            if not self._asset_dir:
                self._asset_dir = tempfile.mkdtemp(prefix="bluebird-")
            path = os.path.join(self._asset_dir, name + ".png")
            if not os.path.isfile(path):
                pixmap = builder()
                if pixmap is None or pixmap.isNull():
                    return ""
                pixmap.save(path, "PNG")
            return path.replace("\\", "/")
        except Exception:
            return ""

    def _arrow_pixmap(self, direction: str = "down",
                      color_key: str = "text_muted") -> QPixmap:
        """A small chevron used by spin boxes and combo boxes."""
        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(self.color(color_key, "#8A8072")))
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if direction == "up":
            points = [QPointF(3.8, 8.6), QPointF(7.0, 5.4), QPointF(10.2, 8.6)]
        elif direction == "right":
            points = [QPointF(5.4, 3.8), QPointF(8.6, 7.0), QPointF(5.4, 10.2)]
        elif direction == "left":
            points = [QPointF(8.6, 3.8), QPointF(5.4, 7.0), QPointF(8.6, 10.2)]
        else:
            points = [QPointF(3.8, 5.4), QPointF(7.0, 8.6), QPointF(10.2, 5.4)]
        painter.drawPolyline(QPolygonF(points))
        painter.end()
        return pixmap

    # -- checkmark asset -------------------------------------------------
    def check_icon_path(self) -> str:
        """Render (once) a small tick PNG used by ``QCheckBox``.

        Qt stylesheets cannot draw a tick, so we hand it a real image file
        whose colour matches the current accent.
        """
        if self._check_icon and os.path.isfile(self._check_icon):
            return self._check_icon.replace("\\", "/")
        return self._asset("check", self._check_pixmap)

    def _check_pixmap(self) -> QPixmap:
        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(self.color("text_inverse", "#FFFFFF")))
        pen.setWidthF(1.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(
            QPolygonF([QPointF(3.0, 7.4), QPointF(5.9, 10.4),
                       QPointF(11.0, 4.2)]))
        painter.end()
        return pixmap

    def arrow_icon_path(self, direction: str = "down",
                        color_key: str = "text_muted") -> str:
        """A ``url(...)`` token for a chevron, ready to drop into the QSS."""
        path = self._asset("arrow_%s_%s" % (direction, color_key),
                           lambda: self._arrow_pixmap(direction, color_key))
        return "url(%s)" % path if path else "none"

    def cleanup(self) -> None:
        if self._asset_dir and os.path.isdir(self._asset_dir):
            shutil.rmtree(self._asset_dir, ignore_errors=True)
        self._asset_dir = ""
        self._check_icon = ""

    # -- fonts ----------------------------------------------------------
    def base_font(self) -> QFont:
        family = self._settings.get("appearance", "font_family", "") or ""
        size = int(self._settings.get("appearance", "font_size", 0) or 0)
        if family:
            available = QFontDatabase().families() if _has_qapp() else []
            if not available or family in available:
                font = QFont(family)
            else:
                font = QFont()
        else:
            font = QFont()
        if size > 0:
            font.setPointSize(size)
        return font

    def mono_font(self) -> QFont:
        font = self.base_font()
        font.setFamily("Consolas")
        font.setStyleHint(QFont.Monospace)
        if not self._settings.get("appearance", "font_size", 0):
            font.setPointSize(max(9, font.pointSize()))
        return font

    def item_font(self, kind: str, current: QFont) -> QFont:
        """Return the font to use for a file-list item."""
        font = QFont(current)
        if kind == "folder":
            font.setBold(True)
        elif kind == "link":
            font.setItalic(True)
        return font

    def row_icon_size(self) -> int:
        return max(12, int(self._settings.get("appearance", "icon_size", 18) or 18))


def _has_qapp() -> bool:
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() is not None


class IconSpec(object):
    """How a file entry should be painted in a list."""

    __slots__ = ("name", "color_key", "kind")

    def __init__(self, name: str, color_key: str, kind: str) -> None:
        self.name = name
        self.color_key = color_key
        self.kind = kind


def icon_spec_for(entry: Any, theme: Theme) -> IconSpec:
    """Pick an icon + colour for a remote/local entry.

    Folders always use the folder colour; symlinks use the link colour;
    regular files keep the file colour (the default text colour).
    """
    if entry is None:
        return IconSpec("file", "file", "file")
    is_dir = bool(getattr(entry, "is_dir", False))
    is_link = bool(getattr(entry, "is_link", False))
    if is_dir:
        return IconSpec("folder", "folder", "folder")
    if is_link:
        return IconSpec("link", "link", "link")
    name = str(getattr(entry, "name", "") or "").lower()
    dot = name.rfind(".")
    extension = name[dot:] if dot > 0 else ""
    if extension in IMAGE_EXTENSIONS:
        return IconSpec("image", "file", "file")
    if extension in ARCHIVE_EXTENSIONS:
        return IconSpec("archive", "file", "file")
    if extension in MEDIA_EXTENSIONS:
        return IconSpec("media", "file", "file")
    if extension in DOC_EXTENSIONS:
        return IconSpec("doc", "file", "file")
    if extension in TEXT_EXTENSIONS:
        return IconSpec("text", "file", "file")
    if extension in CODE_EXTENSIONS:
        return IconSpec("code", "file", "file")
    if extension in (".exe", ".msi", ".com", ".app"):
        return IconSpec("exec", "file", "file")
    return IconSpec("file", "file", "file")


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
# Cream / milk-white surfaces, softly rounded corners, no harsh outlines.

_STYLESHEET = """
* {
    outline: none;
}
QWidget {
    background-color: {{window}};
    color: {{text}};
    font-size: 12px;
}
QWidget:disabled {
    color: {{text_muted}};
}
QMainWindow, QDialog {
    background-color: {{window}};
}
QToolTip {
    background-color: {{tooltip_bg}};
    color: {{tooltip_text}};
    border: 1px solid {{border_strong}};
    padding: 4px 6px;
    border-radius: 6px;
}

/* ---------------- frames / containers ---------------- */
QFrame#Card, QWidget#Card {
    background-color: {{surface}};
    border: 1px solid {{border}};
    border-radius: 10px;
}
QFrame#ToolBarFrame {
    background-color: {{sidebar}};
    border: none;
    border-bottom: 1px solid {{border}};
}
QFrame#StatusFrame {
    background-color: {{sidebar}};
    border: none;
    border-top: 1px solid {{border}};
}
QFrame#PathFrame {
    background-color: {{surface}};
    border-bottom: 1px solid {{gridline}};
}
QSplitter::handle {
    background-color: {{border}};
}
QSplitter::handle:horizontal { width: 4px; }
QSplitter::handle:vertical { height: 4px; }
QSplitter::handle:hover { background-color: {{accent}}; }
QStackedWidget { background-color: {{surface}}; }

/* ---------------- buttons ---------------- */
QPushButton {
    background-color: {{surface}};
    color: {{text}};
    border: 1px solid {{border_strong}};
    border-radius: 7px;
    padding: 5px 12px;
    min-height: 16px;
}
QPushButton:hover {
    background-color: {{surface_hover}};
    border-color: {{accent}};
}
QPushButton:pressed {
    background-color: {{accent_soft}};
    border-color: {{accent_pressed}};
}
QPushButton:disabled {
    background-color: {{surface_sunken}};
    color: {{text_muted}};
    border-color: {{border}};
}
QPushButton:default {
    border-color: {{accent}};
}
QPushButton#Primary {
    background-color: {{accent}};
    color: {{text_inverse}};
    border: 1px solid {{accent_pressed}};
    font-weight: 600;
}
QPushButton#Primary:hover { background-color: {{accent_hover}}; }
QPushButton#Primary:pressed { background-color: {{accent_pressed}}; }
QPushButton#Primary:disabled {
    background-color: {{border}};
    color: {{text_muted}};
    border-color: {{border_strong}};
}
QPushButton#Ghost {
    background-color: transparent;
    border: 1px solid transparent;
}
QPushButton#Ghost:hover {
    background-color: {{surface_hover}};
    border-color: {{border}};
}
QPushButton#Ghost:pressed { background-color: {{accent_soft}}; }
QPushButton#Tool {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px;
}
QPushButton#Tool:hover {
    background-color: {{surface_hover}};
    border-color: {{border}};
}
QPushButton#Tool:pressed, QPushButton#Tool:checked {
    background-color: {{accent_soft}};
    border-color: {{focus}};
}
QPushButton#Link {
    background: transparent;
    border: none;
    color: {{accent}};
    padding: 2px 4px;
}
QPushButton#Link:hover { color: {{accent_hover}}; text-decoration: underline; }

QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px 6px;
    color: {{text}};
}
QToolButton:hover {
    background-color: {{surface_hover}};
    border-color: {{border}};
}
QToolButton:pressed, QToolButton:checked {
    background-color: {{accent_soft}};
    border-color: {{focus}};
}
QToolButton::menu-indicator { image: none; }

/* ---------------- inputs ---------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit {
    background-color: {{surface}};
    color: {{text}};
    border: 1px solid {{border}};
    border-radius: 7px;
    padding: 4px 8px;
    selection-background-color: {{selection_bg}};
    selection-color: {{selection_text}};
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: {{focus}};
    background-color: {{surface}};
}
QLineEdit:disabled, QSpinBox:disabled {
    background-color: {{surface_sunken}};
    color: {{text_muted}};
}
QLineEdit#PathEdit {
    background-color: {{surface_sunken}};
    border-radius: 7px;
    padding: 5px 9px;
}
QLineEdit#PathEdit:focus {
    background-color: {{surface}};
    border-color: {{focus}};
}
QLineEdit#SearchEdit { padding-left: 8px; }

QComboBox {
    background-color: {{surface}};
    color: {{text}};
    border: 1px solid {{border}};
    border-radius: 7px;
    padding: 4px 8px;
    min-height: 16px;
}
QComboBox:hover { border-color: {{border_strong}}; }
QComboBox:focus { border-color: {{focus}}; }
QComboBox:on { border-color: {{focus}}; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 18px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: {{arrow_down}};
    width: 14px;
    height: 14px;
    margin-right: 4px;
}
QComboBox::down-arrow:on { image: {{arrow_down_accent}}; }
QComboBox QAbstractItemView {
    background-color: {{menu_bg}};
    border: 1px solid {{border_strong}};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {{accent_soft}};
    selection-color: {{text}};
    outline: none;
}

/* spin boxes need explicit arrow styling or Qt draws stray lines */
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 17px;
    margin: 1px 2px 0 0;
    border: none;
    border-top-right-radius: 6px;
    background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 17px;
    margin: 0 2px 1px 0;
    border: none;
    border-bottom-right-radius: 6px;
    background: transparent;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: {{surface_hover}};
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: {{arrow_up}};
    width: 13px; height: 13px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: {{arrow_down}};
    width: 13px; height: 13px;
}
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {
    border-bottom-color: {{accent}};
}
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {
    border-top-color: {{accent}};
}
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled {
    border-bottom-color: {{border}};
    border-top-color: {{border}};
}

QCheckBox, QRadioButton { spacing: 7px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 15px; height: 15px;
    border: 1px solid {{border_strong}};
    background-color: {{surface}};
}
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: {{accent}}; }
QCheckBox::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent_pressed}};
    image: url({{check_icon}});
}
QRadioButton::indicator:checked {
    background-color: {{accent}};
    border-color: {{accent_pressed}};
}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background-color: {{surface_sunken}};
}

QGroupBox {
    background-color: transparent;
    border: 1px solid {{border}};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 10px 8px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    color: {{text_muted}};
}

QLabel { background: transparent; }
QLabel#SectionTitle {
    color: {{text_muted}};
    font-weight: 600;
    font-size: 11px;
    letter-spacing: 1px;
}
QLabel#PaneTitle { font-weight: 700; font-size: 13px; }
QLabel#Hint { color: {{text_muted}}; }
QLabel#Heading { font-size: 17px; font-weight: 700; }
QLabel#Swatch {
    border: 1px solid {{border_strong}};
    border-radius: 6px;
}

/* ---------------- tabs ---------------- */
QTabWidget::pane {
    background-color: {{surface}};
    border: 1px solid {{border}};
    border-radius: 10px;
    top: -1px;
}
QTabBar { qproperty-drawBase: 0; background: transparent; }
QTabBar::tab {
    background-color: transparent;
    color: {{text_muted}};
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 6px 14px;
    margin-right: 3px;
}
QTabBar::tab:hover {
    background-color: {{surface_hover}};
    color: {{text}};
}
QTabBar::tab:selected {
    background-color: {{surface}};
    color: {{text}};
    border: 1px solid {{border}};
    border-bottom-color: {{surface}};
    font-weight: 600;
}
QTabBar::close-button {
    image: none;
    subcontrol-position: right;
}

/* ---------------- item views ---------------- */
QTableView, QTreeView, QListView {
    background-color: {{surface}};
    alternate-background-color: {{surface_alt}};
    color: {{text}};
    border: 1px solid {{border}};
    border-radius: 10px;
    gridline-color: {{gridline}};
    selection-background-color: {{selection_bg}};
    selection-color: {{selection_text}};
    outline: none;
}
QTableView::item, QTreeView::item, QListView::item {
    padding: 2px 4px;
    border: none;
}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {
    background-color: {{surface_hover}};
}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {
    background-color: {{selection_bg}};
    color: {{selection_text}};
}
QTableView::item:selected:!active, QTreeView::item:selected:!active {
    background-color: {{selection_bg}};
    color: {{selection_text}};
}
QHeaderView { background-color: {{surface}}; }
QHeaderView::section {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {{header_grad_a}}, stop:1 {{header_grad_b}});
    color: {{text_muted}};
    border: none;
    border-right: 1px solid {{gridline}};
    border-bottom: 1px solid {{border}};
    padding: 5px 8px;
    font-weight: 600;
}
QHeaderView::section:hover { color: {{text}}; }
QHeaderView::section:first { border-top-left-radius: 10px; }
QHeaderView::section:last { border-top-right-radius: 10px; border-right: none; }
QHeaderView::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {{accent}};
    width: 0; height: 0;
}
QHeaderView::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {{accent}};
    width: 0; height: 0;
}
QTableCornerButton::section {
    background-color: {{header}};
    border: none;
    border-bottom: 1px solid {{border}};
}

/* ---------------- scrollbars ---------------- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 3px 2px 3px 2px;
}
QScrollBar::handle:vertical {
    background-color: {{scroll_handle}};
    border-radius: 4px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover { background-color: {{scroll_handle_hover}}; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px 3px 2px 3px;
}
QScrollBar::handle:horizontal {
    background-color: {{scroll_handle}};
    border-radius: 4px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover { background-color: {{scroll_handle_hover}}; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------------- progress ---------------- */
QProgressBar {
    background-color: {{track}};
    border: none;
    border-radius: 6px;
    text-align: center;
    color: {{text}};
    min-height: 12px;
    font-size: 10px;
}
QProgressBar::chunk {
    background-color: {{progress}};
    border-radius: 6px;
}

/* ---------------- menus ---------------- */
QMenuBar {
    background-color: {{sidebar}};
    border-bottom: 1px solid {{border}};
}
QMenuBar::item {
    background: transparent;
    padding: 5px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected { background-color: {{surface_hover}}; }
QMenu {
    background-color: {{menu_bg}};
    border: 1px solid {{border_strong}};
    border-radius: 9px;
    padding: 5px;
}
QMenu::item {
    padding: 6px 26px 6px 22px;
    border-radius: 6px;
    color: {{text}};
}
QMenu::item:selected {
    background-color: {{accent_soft}};
    color: {{text}};
}
QMenu::item:disabled { color: {{text_muted}}; }
QMenu::separator {
    height: 1px;
    background-color: {{border}};
    margin: 5px 8px;
}
QMenu::icon { padding-left: 8px; }

QStatusBar {
    background-color: {{sidebar}};
    color: {{text_muted}};
    border-top: 1px solid {{border}};
}
QStatusBar::item { border: none; }

/* ---------------- dialog chrome ---------------- */
QDialogButtonBox { background: transparent; }
QListWidget, QTableWidget {
    background-color: {{surface}};
    border: 1px solid {{border}};
    border-radius: 10px;
}
QListWidget::item { padding: 5px 6px; border-radius: 6px; }
QListWidget::item:hover { background-color: {{surface_hover}}; }
QListWidget::item:selected {
    background-color: {{selection_bg}};
    color: {{selection_text}};
}
QSlider::groove:horizontal {
    background-color: {{track}};
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: {{accent}};
    width: 13px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover { background-color: {{accent_hover}}; }
QSlider::sub-page:horizontal { background-color: {{focus}}; border-radius: 2px; }

QToolTip, QMenu, QComboBox QComboBox QAbstractItemView { }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QMessageBox { background-color: {{window}}; }
QMessageBox QLabel { background: transparent; }
QPlainTextEdit#LogView {
    border: 1px solid {{border}};
    border-radius: 10px;
    background-color: {{surface}};
}
"""

__all__ = [
    "Theme", "IconSpec", "icon_spec_for", "quote_family",
    "CODE_EXTENSIONS", "IMAGE_EXTENSIONS", "ARCHIVE_EXTENSIONS",
    "MEDIA_EXTENSIONS", "DOC_EXTENSIONS", "TEXT_EXTENSIONS",
]
