"""Application bootstrap: ``python -m ftpclient`` / ``run.py``.

High-DPI friendly, single-instance-free and completely stateless apart from
the JSON settings file.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import List, Optional

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QMessageBox

from . import __appname__, __orgname__, __version__
from . import config as _config
from .i18n import i18n


def _enable_high_dpi() -> None:
    """Opt in to Qt's high-DPI scaling before the QApplication exists."""
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # QtWebEngine (used by the in-app manual) refuses to start unless the
    # OpenGL contexts are shared, and this must be set before QApplication
    if hasattr(Qt, "AA_ShareOpenGLContexts"):
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)


def _install_excepthook(app: QApplication) -> None:
    """Never let an unhandled exception kill the session silently."""

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        sys.stderr.write(text)
        try:
            QMessageBox.critical(
                None, "%s — unexpected error" % __appname__,
                "Something went wrong:\n\n%s" % (exc_value,))
        except Exception:
            pass

    sys.excepthook = hook


def build_application(argv: Optional[List[str]] = None) -> QApplication:
    _enable_high_dpi()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(__appname__)
    app.setApplicationDisplayName(__appname__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(__orgname__)
    app.setStyle("Fusion")
    # the window/taskbar icon is drawn at runtime, so no asset has to ship
    try:
        from . import appicon
        app.setWindowIcon(appicon.icon())
    except Exception:
        pass
    _install_excepthook(app)
    return app


def _known_options() -> set:
    """Flags that belong to Qt/webengine, not to a connection target."""
    names = {"-stylesheet", "-style", "-graphicsystem", "-platform",
             "-platformpluginpath", "-plugin", "-qmljsdebugger", "-reverse",
             "-session", "-display", "-geometry", "-font", "-name",
             "-title", "-widgetcount", "-nograb", "-dograb", "-sync",
             "-remote-debugging-port", "-disable-gpu", "-no-sandbox"}
    return names


def connection_arguments(argv: Optional[List[str]] = None) -> List[str]:
    """Pick out the connection targets from a raw command line.

    A packaged build is launched from Explorer, but a user may still pass a
    URL, and Qt itself adds ``-style``/``-platform`` style switches, so raw
    ``sys.argv`` is filtered rather than taken verbatim.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    known = _known_options()
    result: List[str] = []
    skip_next = False
    for index, item in enumerate(raw):
        if skip_next:
            skip_next = False
            continue
        if item.startswith("-"):
            # "-flag value" style: skip the value too
            if item in known and index + 1 < len(raw) and not raw[index + 1].startswith("-"):
                skip_next = True
            continue
        result.append(item)
    return result


def _command_line_flags(argv: Optional[List[str]] = None) -> List[str]:
    raw = list(sys.argv[1:] if argv is None else argv)
    return [item.lower() for item in raw if item.startswith("-")]


def startup_log_path() -> str:
    """Where ``--log`` writes: beside the exe, never inside the bundle."""
    from .resources import is_frozen, resource_root
    base = os.path.dirname(sys.executable) if is_frozen() else resource_root()
    return os.path.join(base, "smartftp-startup.log")


def run_selftest() -> int:
    """Build the application, load the manual, then exit.

    Packaged builds have no console, so this is how a frozen executable is
    verified: ``SmartFTP.exe --selftest --log``.
    """
    from .resources import is_frozen, resource_root
    from . import __appname__, __version__

    app = build_application([])

    report = [
        "%s %s" % (__appname__, __version__),
        "python      : %s" % sys.version.split()[0],
        "frozen      : %s" % is_frozen(),
        "resource    : %s" % resource_root(),
    ]
    failures = []
    try:
        from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        report.append("Qt          : %s (PyQt %s)"
                      % (QT_VERSION_STR, PYQT_VERSION_STR))
    except Exception as exc:                      # pragma: no cover
        failures.append("Qt version: %s" % exc)

    from . import config as _config
    from .i18n import T, apply_locale, set_language
    from .icons import IconFactory
    from .main import MainWindow
    from .manual import manual_html, manual_pdf, web_engine_available
    from .theme import Theme

    status = {}
    try:
        settings = _config.Settings()
        report.append("settings    : %s" % settings.path)
        report.append("connections : %s" % settings.connections.path)
    except Exception as exc:
        failures.append("settings: %s" % exc)
        settings = _config.Settings.__new__(_config.Settings)

    try:
        status["manual html"] = manual_html() or "MISSING"
        status["manual pdf"] = manual_pdf() or "MISSING"
        status["web engine"] = web_engine_available()
        for key, value in status.items():
            report.append("%-11s : %s" % (key, value))
        if status["manual html"] == "MISSING":
            failures.append("the manual HTML is not in the bundle")
    except Exception as exc:
        failures.append("manual: %s" % exc)

    # SSH key support: a bare "import nacl.signing" inside paramiko means the
    # whole ed25519 module fails to load when PyNaCl is not bundled, and then
    # ssh-ed25519 keys (private *and* host keys) stop working silently.
    try:
        import nacl
        import nacl.signing
        report.append("pynacl      : %s" % getattr(nacl, "__version__", "?"))
    except Exception as exc:
        failures.append("PyNaCl is missing, so ssh-ed25519 keys will not "
                        "work: %s" % (exc,))

    try:
        import io as _io
        import paramiko
        from paramiko.ed25519key import Ed25519Key
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey)
        _pem = Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption())
        _key = Ed25519Key.from_private_key(_io.StringIO(_pem.decode()))
        _key.sign_ssh_data(b"smart-selftest")
        report.append("ed25519     : sign ok (%s, %d bits)"
                      % (_key.get_name(), _key.get_bits()))
    except Exception as exc:
        failures.append("ed25519 signing: %s" % (exc,))

    try:
        import bcrypt
        report.append("bcrypt      : %s"
                      % getattr(bcrypt, "__version__", "present"))
    except Exception as exc:
        failures.append("bcrypt is missing, so passphrase-protected keys "
                        "cannot be read: %s" % (exc,))

    try:
        set_language("zh", notify=False)
        apply_locale()
        theme = Theme(settings)
        icons = IconFactory(theme)
        window = MainWindow(settings, theme, icons)
        report.append("window      : built (%d panes, %d menu actions)"
                      % (2, len(window.menu.actions)))
        report.append("translated  : %s" % T("Connect"))
        entries = window.local_pane.model.rowCount()
        report.append("local pane  : %d entries" % entries)

        # render the manual for real: this is the part that needs the trimmed
        # QtWebEngine runtime to still be complete
        if web_engine_available():
            from PyQt5.QtCore import QEventLoop, QTimer, QUrl
            window.open_manual()
            manual_window = window._manual_window
            if manual_window is None:
                failures.append("the manual window was not created")
            else:
                loop = QEventLoop()
                state = {"ok": False}
                manual_window.view.loadFinished.connect(
                    lambda ok: (state.update({"ok": bool(ok)}), loop.quit()))
                QTimer.singleShot(30000, loop.quit)
                loop.exec_()
                if state["ok"]:
                    report.append("manual page : rendered")
                else:
                    failures.append("the manual page did not finish loading")
                manual_window.close()
        window.manager.shutdown()
        theme.cleanup()
        window.close()
    except Exception as exc:
        failures.append("main window: %s" % (exc,))

    lines = list(report)
    lines.append("")
    if failures:
        lines.append("FAILED:")
        for item in failures:
            lines.append("  - %s" % item)
    else:
        lines.append("SELFTEST OK")
    text = "\n".join(lines)

    print(text)
    try:
        with open(startup_log_path(), "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass
    app.quit()
    return 1 if failures else 0


def run(argv: Optional[List[str]] = None) -> int:
    from .i18n import (apply_locale, install_message_box_translation,
                       set_language)
    from .icons import IconFactory
    from .main import MainWindow
    from .theme import Theme

    flags = _command_line_flags(argv)
    if "--selftest" in flags:
        return run_selftest()
    if "--version" in flags:
        print("%s %s" % (__appname__, __version__))
        return 0

    app = build_application(argv)
    settings = _config.Settings()

    # the interface language is part of the settings, so apply it before any
    # widget is built (a saved language survives restarts)
    install_message_box_translation()
    set_language(str(settings.get("appearance", "language", "") or ""),
                 notify=False)
    apply_locale()

    theme = Theme(settings)
    icons = IconFactory(theme)

    window = MainWindow(settings, theme, icons)
    app.setStyleSheet(theme.stylesheet())
    theme.changed.connect(lambda: app.setStyleSheet(theme.stylesheet()))
    app.setFont(theme.base_font())

    def on_language_changed() -> None:
        """Broadcast the change so every window retranslates itself."""
        apply_locale()
        for widget in app.topLevelWidgets():
            app.sendEvent(widget, QEvent(QEvent.LanguageChange))

    i18n.changed.connect(on_language_changed)

    # allow ``SmartFTP.exe sftp://user@host:22`` style arguments
    args = connection_arguments(argv)
    if args:
        _connect_from_argument(window, args[0])

    window.show()
    if "--log" in flags:
        try:
            with open(startup_log_path(), "w", encoding="utf-8") as handle:
                handle.write("started pid=%d\nresource=%s\n"
                             % (os.getpid(),
                                __import__("ftpclient.resources",
                                           fromlist=["resource_root"]
                                           ).resource_root()))
        except OSError:
            pass
    return app.exec_()


def _connect_from_argument(window: Any, target: str) -> None:
    """Accept ``proto://user@host:port`` or a bare ``host``."""
    from urllib.parse import urlparse
    text = target.strip()
    if "://" not in text:
        text = "ftp://" + text
    try:
        parsed = urlparse(text)
    except Exception:
        return
    if not parsed.hostname:
        return
    config = {
        "name": parsed.username or parsed.hostname or "connection",
        "protocol": parsed.scheme if parsed.scheme in ("ftp", "ftps", "sftp") else "ftp",
        "host": parsed.hostname,
        "port": parsed.port or (22 if parsed.scheme == "sftp" else 21),
        "user": parsed.username or "",
        "password": parsed.password or "",
    }
    if parsed.path and parsed.path not in ("", "/"):
        config["remote_dir"] = parsed.path
    window._config_to_bar(config)
    window.open_connect_dialog(config)


__all__ = ["run", "build_application", "connection_arguments"]
