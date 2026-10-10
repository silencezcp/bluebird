#!/usr/bin/env python
"""Render the real window to PNG files so the look can be reviewed.

    D:\\DSH_Workspaces\\Ftp\\python.exe tools\\screenshot.py [output_dir]

The window is shown for real (so system fonts are used) but it is moved off
the visible desktop area and closed again, so nothing pops up over your work.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEvent, QEventLoop, Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMenu  # noqa: E402

from ftpclient import config as C  # noqa: E402
from ftpclient import session as S  # noqa: E402
from ftpclient.app import build_application  # noqa: E402
from ftpclient.icons import IconFactory  # noqa: E402
from ftpclient.main import MainWindow  # noqa: E402
from ftpclient.models import TransferItem  # noqa: E402
from ftpclient.theme import Theme  # noqa: E402
from ftpclient.transfer import plan_downloads  # noqa: E402
from tests.ftpserver import TestFTPServer, make_tree  # noqa: E402


def pump(app, seconds=0.6):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 30)
        time.sleep(0.01)


def shot(widget, path):
    widget.repaint()
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.save(path, "PNG")
    print("wrote %s  (%dx%d)" % (path, pixmap.width(), pixmap.height()))


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots")
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    workdir = tempfile.mkdtemp(prefix="smart-shot-")
    settings_path = os.path.join(workdir, "settings.json")
    os.environ["BLUEBIRD_SETTINGS"] = settings_path

    app = build_application([])

    # --- a local tree the left pane can show ---------------------------
    local_root = os.path.join(workdir, "Local")
    os.makedirs(os.path.join(local_root, "Projects", "smart"), exist_ok=True)
    os.makedirs(os.path.join(local_root, "Pictures"), exist_ok=True)
    for name, size in (("report-2026.pdf", 240_000), ("notes.txt", 1_240),
                       ("archive.zip", 5_600_000), ("budget.xlsx", 88_400),
                       ("logo.png", 46_000), ("server.log", 320_000),
                       ("index.html", 4_200), ("data.csv", 15_000)):
        with open(os.path.join(local_root, name), "wb") as handle:
            handle.write(b"x" * min(size, 4096))
    with open(os.path.join(local_root, "Projects", "smart", "main.py"), "w") as h:
        h.write("print('hi')\n")
    with open(os.path.join(local_root, ".env"), "w") as h:
        h.write("SECRET=1\n")

    # --- a real FTP server the right pane can talk to ------------------
    server_root = os.path.join(workdir, "Remote")
    os.makedirs(server_root)
    make_tree(server_root)
    for name, size in (("release-notes.md", 3_100), ("backup.tar.gz", 12_400_000),
                       ("photo.jpg", 1_900_000), ("config.json", 820),
                       ("video.mp4", 45_000_000)):
        with open(os.path.join(server_root, name), "wb") as handle:
            handle.write(b"y" * min(size, 4096))
    server = TestFTPServer(server_root)
    host, port = server.start()

    settings = C.Settings(settings_path)
    theme = Theme(settings)
    icons = IconFactory(theme)

    window = MainWindow(settings, theme, icons)
    app.setStyleSheet(theme.stylesheet())
    window.resize(1400, 900)
    window.move(-4000, -4000)      # off the visible desktop
    window.show()
    pump(app, 0.6)

    window.local_pane.navigate(local_root)

    config = {"protocol": "ftp", "host": host, "port": port,
              "user": "tester", "password": "secret", "timeout": 15,
              "name": "Production web server"}
    session = S.create_session(config)
    session.connect()
    window.session = session
    window.remote_pane.set_session(session)
    window.manager.session = session
    window._config_to_bar(config)
    window.host_edit.setText("ftp.example.com")
    window.user_edit.setText("tester")
    window.connect_button.setEnabled(False)
    window.disconnect_button.setEnabled(True)
    window.remote_pane.navigate("/")
    window._store_connection(dict(config))
    window.log("success", "Connected to FTP://tester@ftp.example.com:21")
    window.log("info", "Listed / (9 items)")

    # seed the queue with a mix of finished, active and failed rows
    download_dir = os.path.join(local_root, "Downloads")
    os.makedirs(download_dir, exist_ok=True)
    entries = [e for e in window.remote_pane.model.visible_entries()
               if e.name in ("readme.txt", "data.bin", "docs")]
    items = plan_downloads(session, "/", entries, download_dir)
    window.manager.enqueue(items)
    deadline = time.time() + 15
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 40)
        if window.manager.pending() == 0:
            break
        time.sleep(0.02)

    fake_active = TransferItem("upload", os.path.join(local_root, "archive.zip"),
                               "/incoming/archive.zip", size=5_600_000)
    fake_active.status = "active"
    fake_active.transferred = 3_400_000
    fake_active.speed = 812_000.0
    fake_failed = TransferItem("download", "/mnt/missing/ghost.iso",
                               os.path.join(download_dir, "ghost.iso"), size=900)
    fake_failed.status = "error"
    fake_failed.message = "Server refused the command (550 No such file)"
    window.manager.enqueue([fake_active, fake_failed])
    window._on_transfer_update(fake_active.uid)
    window._on_transfer_update(fake_failed.uid)
    window.queue_panel.table.selectRow(0)
    window.remote_pane.table.selectRow(1)
    window.local_pane.table.selectRow(2)
    pump(app, 0.8)

    shot(window, os.path.join(outdir, "01-main-cream.png"))

    # the same window in English (the interface is bilingual)
    from ftpclient import i18n as _i18n
    _i18n.set_language("en")
    _i18n.apply_locale()
    for top in app.topLevelWidgets():
        app.sendEvent(top, QEvent(QEvent.LanguageChange))
    pump(app, 0.6)
    window.resize(1400, 900)
    pump(app, 0.4)
    shot(window, os.path.join(outdir, "13-main-english.png"))
    _i18n.set_language("zh")
    _i18n.apply_locale()
    for top in app.topLevelWidgets():
        app.sendEvent(top, QEvent(QEvent.LanguageChange))
    pump(app, 0.6)

    # drive picker for the local pane: build the same menu the button builds,
    # show it non-modally so it can be captured, then close it again
    from ftpclient.widgets import PathBar
    bar = window.local_pane.path_bar
    menu = QMenu(window)
    for label, path in window.local_pane.drive_list():
        action = menu.addAction(label)
        action.setData(path)
    menu.addSeparator()
    menu.addAction("Browse for a folder…")
    menu.move(window.x() + 40, window.y() + 260)
    menu.show()
    pump(app, 0.5)
    shot(menu, os.path.join(outdir, "08-drive-picker.png"))
    menu.close()
    pump(app, 0.3)

    # transfers tab
    window.bottom_tabs.setCurrentIndex(0)
    pump(app, 0.4)
    shot(window, os.path.join(outdir, "02-transfer-queue.png"))

    # dark preset
    theme.apply_preset("Linen (dark)")
    app.setStyleSheet(theme.stylesheet())
    pump(app, 0.6)
    shot(window, os.path.join(outdir, "03-linen-dark.png"))
    theme.apply_preset("BlueBird (cream)")
    app.setStyleSheet(theme.stylesheet())
    pump(app, 0.3)

    # custom colouring: orange folders, teal files
    theme.set_color("folder", "#D98032")
    theme.set_color("folder_dark", "#B5651F")
    theme.set_color("file", "#2F6F6A")
    app.setStyleSheet(theme.stylesheet())
    pump(app, 0.5)
    shot(window, os.path.join(outdir, "04-custom-colours.png"))
    theme.apply_preset("BlueBird (cream)")
    app.setStyleSheet(theme.stylesheet())
    pump(app, 0.3)

    # preferences → colours page
    from ftpclient.dialogs import PreferencesDialog
    prefs = PreferencesDialog(settings, theme, icons, window)
    prefs.resize(920, 660)
    prefs.nav.setCurrentRow(2)
    prefs.show()
    prefs.color_search.setText("folder")
    pump(app, 0.6)
    shot(prefs, os.path.join(outdir, "05-preferences-colours.png"))
    prefs.nav.setCurrentRow(1)
    prefs.color_search.clear()
    pump(app, 0.4)
    shot(prefs, os.path.join(outdir, "06-preferences-appearance.png"))
    prefs.close()

    # connect dialog
    from ftpclient.dialogs import ConnectDialog
    dialog = ConnectDialog(settings, window, {
        "protocol": "sftp", "host": "sftp.example.com", "port": 22,
        "user": "deploy", "password": "hunter2",
        "name": "Deploy target"}, icons)
    dialog.resize(540, 580)
    dialog.show()
    pump(app, 0.5)
    shot(dialog, os.path.join(outdir, "07-connect-sftp.png"))
    dialog.close()

    # config.ini contents, shown as text
    ini_path = settings.connections.path
    print("\n%s\n%s\n%s" % ("-" * 60, ini_path, "-" * 60))
    if os.path.isfile(ini_path):
        print(open(ini_path, encoding="utf-8").read())

    window.manager.shutdown()
    session.disconnect()
    server.stop()
    theme.cleanup()
    shutil.rmtree(workdir, ignore_errors=True)
    print("\nscreenshots in %s" % outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
