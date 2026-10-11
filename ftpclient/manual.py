"""The in-application user manual window.

QtWebEngine renders the bundled HTML manual (the screenshots are embedded, so
it is fully self-contained).  If the web engine is unavailable - or the HTML
is missing - the caller can fall back to the PDF or the plain Markdown file.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (QAction, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QSizePolicy,
                             QToolBar, QVBoxLayout, QWidget)

from . import __appname__, __version__
from . import resources
from .i18n import T
from .retranslate import Retranslator

#: how far one zoom step moves the page
ZOOM_STEP = 0.1
ZOOM_MIN = 0.5
ZOOM_MAX = 2.5


#: Why the web engine is unavailable, when it is.  Kept so the reason can be
#: shown instead of the bare fact: a silent ImportError here once turned a
#: broken bundle into "the manual just opens in a browser instead", with nothing
#: anywhere saying why.
WEB_ENGINE_ERROR: Optional[str] = None


def web_engine_available() -> bool:
    """True when the bundled QtWebEngine can be imported and used.

    The import is the whole test: QtWebEngine refuses to load once a
    QApplication exists unless AA_ShareOpenGLContexts was set first (app.py
    does that), and it also fails if any of its DLLs or QML modules are
    missing, which is what a too-eager trim would cause.
    """
    global WEB_ENGINE_ERROR
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    except Exception as exc:                 # noqa: BLE001 - report, never raise
        WEB_ENGINE_ERROR = "%s: %s" % (type(exc).__name__, exc)
        return False
    WEB_ENGINE_ERROR = None
    return True


def manual_html() -> Optional[str]:
    return resources.find_resource(*resources.MANUAL_HTML)


def manual_pdf() -> Optional[str]:
    return resources.find_resource(*resources.MANUAL_PDF)


def manual_markdown() -> Optional[str]:
    return resources.find_resource(*resources.MANUAL_MD)


def open_with_system(path: str) -> bool:
    """Hand a file to the operating system's default application."""
    if not path or not os.path.exists(path):
        return False
    try:
        url = QUrl.fromLocalFile(path)
        return bool(QDesktopServices.openUrl(url))
    except Exception:
        return False


class ManualWindow(QMainWindow):
    """A read-only browser window showing the manual."""

    def __init__(self, parent: QWidget = None, page: str = "") -> None:
        super(ManualWindow, self).__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._zoom = 1.0
        self._retranslator = Retranslator()

        from PyQt5.QtWebEngineWidgets import QWebEngineView

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self.resize(1080, 820)

        settings = self.view.settings()
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings
            settings.setAttribute(
                QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            settings.setAttribute(
                QWebEngineSettings.JavascriptCanOpenWindows, False)
        except Exception:
            pass

        toolbar = QToolBar(T("Manual"), self)
        toolbar.setObjectName("ManualToolBar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)

        self.back_action = QAction(T("Back"), self)
        self.back_action.setShortcut(QKeySequence("Alt+Left"))
        self.back_action.triggered.connect(self.view.back)
        self.forward_action = QAction(T("Forward"), self)
        self.forward_action.setShortcut(QKeySequence("Alt+Right"))
        self.forward_action.triggered.connect(self.view.forward)
        self.home_action = QAction(T("Manual"), self)
        self.home_action.triggered.connect(self.go_home)
        self.zoom_in_action = QAction(T("Zoom in"), self)
        self.zoom_in_action.setShortcut(QKeySequence.ZoomIn)
        self.zoom_in_action.triggered.connect(lambda: self.zoom(+ZOOM_STEP))
        self.zoom_out_action = QAction(T("Zoom out"), self)
        self.zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        self.zoom_out_action.triggered.connect(lambda: self.zoom(-ZOOM_STEP))
        self.print_action = QAction(T("Save as PDF…"), self)
        self.print_action.triggered.connect(self.export_pdf)
        self.external_action = QAction(T("Open in the browser"), self)
        self.external_action.triggered.connect(self.open_external)
        self.close_action = QAction(T("Close"), self)
        self.close_action.setShortcut(QKeySequence.Close)
        self.close_action.triggered.connect(self.close)

        for action in (self.back_action, self.forward_action, self.home_action):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.zoom_out_action)
        toolbar.addAction(self.zoom_in_action)
        toolbar.addSeparator()
        toolbar.addAction(self.print_action)
        toolbar.addAction(self.external_action)
        toolbar.addAction(self.close_action)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

        self.path_label = QLabel(self)
        self.path_label.setObjectName("Hint")
        self.statusBar().addWidget(self.path_label, 1)

        self._retranslator.bind(self.retranslate)
        self.go_home(page)
        self.retranslate()

    # -- navigation -----------------------------------------------------
    def go_home(self, anchor: str = "") -> None:
        target = manual_html()
        if not target:
            self.view.setHtml(
                "<h3>%s</h3><p>%s</p>" % (T("Manual not found"),
                                          T("The manual file is missing from "
                                            "this installation.")))
            return
        url = QUrl.fromLocalFile(target)
        if anchor:
            url.setFragment(anchor)
        self.view.load(url)
        self.path_label.setText(target)

    def retranslate(self) -> None:
        try:
            self.setWindowTitle("%s — %s %s" % (T("User manual"),
                                                __appname__, __version__))
            self.toolbar.setWindowTitle(T("Manual"))
            self.back_action.setText(T("Back"))
            self.forward_action.setText(T("Forward"))
            self.home_action.setText(T("Manual"))
            self.zoom_in_action.setText(T("Zoom in"))
            self.zoom_out_action.setText(T("Zoom out"))
            self.print_action.setText(T("Save as PDF…"))
            self.external_action.setText(T("Open in the browser"))
            self.close_action.setText(T("Close"))
        except RuntimeError:
            pass

    # -- actions --------------------------------------------------------
    def zoom(self, delta: float) -> None:
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom + delta))
        try:
            self.view.setZoomFactor(self._zoom)
        except Exception:
            pass
        self.statusBar().showMessage("Zoom %.0f%%" % (self._zoom * 100), 1500)

    def export_pdf(self) -> None:
        """Re-render the manual to a PDF the user can keep or print."""
        from PyQt5.QtWidgets import QFileDialog
        default = os.path.join(
            os.path.expanduser("~"), "%s-%s.pdf" % (__appname__, __version__))
        path, _ = QFileDialog.getSaveFileName(
            self, T("Save as PDF…"), default, "PDF (*.pdf)")
        if not path:
            return
        self.statusBar().showMessage(T("Rendering the PDF…"))

        def finished(target: str, ok: bool) -> None:
            if ok:
                self.statusBar().showMessage(
                    T("Saved to %s") % target, 8000)
            else:
                self.statusBar().showMessage(T("Could not write the PDF"), 8000)

        try:
            self.view.page().pdfPrintingFinished.connect(finished)
            self.view.page().printToPdf(path)
        except Exception as exc:  # pragma: no cover - engine specific
            QMessageBox.warning(self, T("Save as PDF…"), str(exc))

    def open_external(self) -> None:
        target = manual_html()
        if target and open_with_system(target):
            return
        pdf = manual_pdf()
        if pdf and open_with_system(pdf):
            return
        QMessageBox.information(self, T("User manual"),
                                T("No manual file could be opened."))
