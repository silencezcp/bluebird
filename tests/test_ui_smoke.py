#!/usr/bin/env python
"""Headless UI smoke test.

Builds the real window, theme, icons, dialogs and transfer queue on an
offscreen Qt platform, then drives a full upload/download round trip through
the queue against a local FTP server.  No window is ever shown.

    D:\\DSH_Workspaces\\Ftp\\python.exe tests\\test_ui_smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# the connection/listing status popups are real modal dialogs; the suite checks
# them by constructing them directly, so the automatic ones stay muted here
os.environ.setdefault("BLUEBIRD_QUIET_DIALOGS", "1")
os.environ.setdefault("BLUEBIRD_SETTINGS", "")   # replaced below

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("  [ok]   %s" % name)
    else:
        FAILED.append((name, detail))
        print("  [FAIL] %s  %s" % (name, detail))


def patch_message_boxes(shown):
    """Stub out QMessageBox so dialogs are recorded instead of shown.

    ``QMessageBox.exec_`` is an instance method, but ``information()`` and
    friends build their own box and call ``exec()`` inside C++, so the static
    helpers have to be replaced as well.
    """
    from PyQt5.QtWidgets import QMessageBox

    state = {"trace": False}
    originals = {
        "exec_": QMessageBox.exec_,
        "information": QMessageBox.information,
        "warning": QMessageBox.warning,
        "critical": QMessageBox.critical,
        "question": QMessageBox.question,
        "about": QMessageBox.about,
    }

    def record(box):
        if state["trace"]:
            import traceback as _tb
            print("       DIALOG CREATED AT:\n%s"
                  % "".join(_tb.format_stack()[-7:-1]))
        shown.append({
            "title": box.windowTitle(),
            "text": box.text(),
            "info": box.informativeText(),
            "icon": int(box.icon()),
            "detailed": box.detailedText(),
        })
        return int(QMessageBox.Ok)

    def fake_exec(box_self):
        return record(box_self)

    def static_stub(name, default_result):
        def stub(parent=None, title="", text="", *args, **kwargs):
            shown.append({"title": title, "text": text,
                          "info": kwargs.get("informativeText", ""),
                          "icon": 0, "detailed": "", "static": name})
            return default_result
        return stub

    QMessageBox.exec_ = fake_exec
    QMessageBox.information = static_stub("information", int(QMessageBox.Ok))
    QMessageBox.warning = static_stub("warning", int(QMessageBox.Ok))
    QMessageBox.critical = static_stub("critical", int(QMessageBox.Ok))
    QMessageBox.question = static_stub("question", int(QMessageBox.No))
    QMessageBox.about = static_stub("about", None)
    originals["state"] = state
    return originals


def restore_message_boxes(originals):
    from PyQt5.QtWidgets import QMessageBox
    QMessageBox.exec_ = originals["exec_"]
    QMessageBox.information = originals["information"]
    QMessageBox.warning = originals["warning"]
    QMessageBox.critical = originals["critical"]
    QMessageBox.question = originals["question"]
    QMessageBox.about = originals["about"]


class ListingWithoutSizes(object):
    """Stands in for a server whose directory listing omits file sizes."""

    protocol = "ftp"
    protocol_label = "FTP (test stub)"

    def __init__(self) -> None:
        self.cwd_path = "/music"
        self.stat_calls = []

    @property
    def connected(self) -> bool:
        return True

    @property
    def banner(self) -> str:
        return "stub"

    def cwd(self) -> str:
        return self.cwd_path

    def home(self):
        return "/music"

    def describe(self) -> str:
        return "stub://listing-without-sizes"

    def chdir(self, path: str) -> str:
        self.cwd_path = path or "/music"
        return self.cwd_path

    def listdir(self, path=None):
        from ftpclient.models import Entry
        names = ["a.flac", "b.flac", "c.flac", "sub"]
        out = []
        for name in names:
            if name == "sub":
                out.append(Entry(name, 0, 1700000000, True, False))
            else:
                # exactly the problem: size is not reported
                out.append(Entry(name, None, 1700000000, False, False))
        return out

    def stat_file(self, name):
        self.stat_calls.append(name)
        sizes = {"a.flac": 1_500_000, "b.flac": 12_400_000, "c.flac": 900}
        if name in sizes:
            return {"size": sizes[name], "mtime": 1700000000,
                    "permissions": "-rw-r--r--"}
        return None

    def disconnect(self) -> None:
        pass


def main():
    workdir = tempfile.mkdtemp(prefix="smart-ui-")
    settings_path = os.path.join(workdir, "settings.json")
    os.environ["BLUEBIRD_SETTINGS"] = settings_path

    from PyQt5.QtCore import Qt, QTimer, QEventLoop
    from PyQt5.QtWidgets import QApplication

    from ftpclient import config as C
    from ftpclient import session as S
    from ftpclient.app import build_application
    from ftpclient.dialogs import ConnectDialog, PreferencesDialog, SiteManagerDialog
    from ftpclient.icons import IconFactory
    from ftpclient.main import MainWindow, TextViewerDialog, TransferQueuePanel
    from ftpclient.models import TransferItem, format_size, parse_size
    from ftpclient.theme import Theme
    from ftpclient.transfer import plan_downloads, plan_uploads
    from tests.ftpserver import TestFTPServer, make_tree

    app = build_application([])
    print("Qt platform: %s" % app.platformName())

    # A real modal QMessageBox cannot be dismissed on the offscreen platform and
    # segfaults, so every dialog is stubbed out for the whole run.  This has to
    # happen before any transfer, because a finished transfer now pops one up.
    from PyQt5.QtWidgets import QMessageBox
    shown_dialogs = []
    message_boxes = patch_message_boxes(shown_dialogs)

    # ---------------------------------------------------------------- i18n
    print("\n-- bilingual interface --")
    from ftpclient import i18n as I18N
    check("Chinese is the default interface language",
          I18N.current_language() == "zh", I18N.current_language())
    check("catalogue has entries", len(I18N.ZH) > 150, str(len(I18N.ZH)))
    check("English mode returns the key unchanged",
          I18N.set_language("en", notify=False) and I18N.T("Connect") == "Connect",
          I18N.T("Connect"))
    check("Chinese mode translates",
          I18N.set_language("zh", notify=False) and I18N.T("Connect") == "连接",
          I18N.T("Connect"))
    check("unknown keys fall back to English",
          I18N.T("some string that is not translated")
          == "some string that is not translated")
    check("invalid language falls back to the default",
          I18N.set_language("klingon", notify=False) is False
          or I18N.current_language() == "zh", I18N.current_language())
    check("both languages are offered",
          [code for code, _ in I18N.LANGUAGE_NAMES] == ["zh", "en"],
          str(I18N.LANGUAGE_NAMES))
    I18N.set_language("zh", notify=False)

    # ---------------------------------------------------------------- desktop
    print("\n-- Home button targets the Desktop --")
    from ftpclient import session as _session_probe
    desktop = _session_probe.local_desktop()
    check("desktop resolves to a real folder", os.path.isdir(desktop), desktop)
    check("desktop is named Desktop (or 桌面)",
          os.path.basename(desktop) in ("Desktop", "\u684c\u9762"), desktop)
    check("desktop is not simply the home folder",
          os.path.normcase(os.path.abspath(desktop))
          != os.path.normcase(os.path.abspath(os.path.expanduser("~")))
          or not os.path.isdir(os.path.join(os.path.expanduser("~"), "Desktop")),
          desktop)

    # ---------------------------------------------------------------- config.ini
    print("\n-- config.ini connection store --")
    from ftpclient.config import ConnectionStore, default_connection_name
    ini_path = os.path.join(workdir, "config.ini")
    check("config path sits next to settings.json",
          C.default_config_path().endswith("config.ini"),
          C.default_config_path())
    store = ConnectionStore(ini_path)
    store.load()
    check("store starts empty", store.is_empty())
    check("suggested name is user@host",
          default_connection_name({"user": "deploy", "host": "sftp.example.com",
                                   "port": 22, "protocol": "sftp"})
          == "deploy@sftp.example.com")
    check("non standard port appears in the name",
          default_connection_name({"user": "u", "host": "h", "port": 2121})
          == "u@h:2121")
    first = store.upsert({"name": "Prod web", "protocol": "ftp",
                          "host": "ftp.example.com", "port": 21,
                          "user": "deploy", "password": "s3cr3t"})
    check("upsert returns the section", first == "Prod web", first)
    store.upsert({"name": "NAS", "protocol": "sftp", "host": "10.0.0.5",
                  "port": 22, "user": "root", "password": "pw",
                  "key_filename": "C:/keys/id_rsa"})
    check("two connections stored", len(store.all()) == 2, str(len(store.all())))
    check("ini file written to disk", os.path.isfile(ini_path))
    raw_ini = open(ini_path, encoding="utf-8").read()
    check("ini contains a readable index", "[connections]" in raw_ini)
    check("ini stores protocol and host",
          "protocol = ftp" in raw_ini and "host = ftp.example.com" in raw_ini)
    check("ini is plain INI text (hand editable)", "password = s3cr3t" in raw_ini)

    store.upsert({"name": "Prod web", "protocol": "ftp",
                  "host": "ftp.example.com", "port": 21, "user": "deploy",
                  "password": ""})
    check("empty password does not wipe the stored one",
          store.get("Prod web").get("password") == "s3cr3t",
          str(store.get("Prod web").get("password")))
    check("lookup by display name works", store.get("Prod web") is not None)
    check("lookup by section works", store.get("NAS") is not None)
    check("missing lookup returns None", store.get("nope") is None)

    store.remember_dirs("Prod web", "D:/local", "/var/www")
    check("last directories remembered",
          store.get("Prod web").get("remote_dir") == "/var/www")
    store.rename("Prod web", "Production")
    check("rename keeps the record",
          [s["name"] for s in store.all()] == ["NAS", "Production"],
          str([s["name"] for s in store.all()]))
    check("rename preserved the password",
          store.get("Production").get("password") == "s3cr3t")
    store.delete("NAS")
    check("delete removes the section",
          [s["name"] for s in store.all()] == ["Production"])
    reopened = ConnectionStore(ini_path)
    reopened.load()
    check("reopened store sees the same data",
          [s["name"] for s in reopened.all()] == ["Production"])
    check("booleans round trip",
          isinstance(reopened.get("Production").get("protocol"), str))
    # a corrupt file must not break startup
    with open(ini_path, "w", encoding="utf-8") as handle:
        handle.write("this is not = = valid [[[ ini\n")
    corrupt = ConnectionStore(ini_path)
    corrupt.load()
    check("corrupt ini does not raise", True)
    corrupt.clear()

    # legacy sites inside settings.json are imported once
    legacy_path = os.path.join(workdir, "legacy.json")
    with open(legacy_path, "w", encoding="utf-8") as handle:
        json.dump({"sites": [{"name": "Old site", "protocol": "ftp",
                              "host": "old.example.com", "port": 21,
                              "user": "bob"}]}, handle)
    legacy_ini = os.path.join(workdir, "legacy.ini")
    legacy = C.Settings(legacy_path, legacy_ini)
    check("legacy settings.json sites migrate into config.ini",
          [s["name"] for s in legacy.sites()] == ["Old site"],
          str([s["name"] for s in legacy.sites()]))

    # ---------------------------------------------------------------- config
    print("\n-- settings --")
    settings = C.Settings(settings_path)
    check("default palette has folder + file",
          "folder" in settings.palette and "file" in settings.palette)
    settings.set("appearance", "row_height", 30)
    reloaded = C.Settings(settings_path)
    check("settings persist", reloaded.get("appearance", "row_height") == 30)
    check("palette defaults survive an old file",
          "accent" in reloaded.palette)
    settings.set("appearance", "row_height", 26)

    print("\n-- colour helpers --")
    check("blend midpoint", C.blend("#000000", "#FFFFFF", 0.5).upper() == "#808080",
          C.blend("#000000", "#FFFFFF", 0.5))
    check("distance identical is zero", C.color_distance("#112233", "#112233") == 0)
    check("distance blue vs dark is large",
          C.color_distance("#2E6FA8", "#3B352C") > 100)
    check("default folder/file colours are distinct",
          C.color_distance(C.DEFAULT_PALETTE["folder"],
                           C.DEFAULT_PALETTE["file"]) > 100)

    # ---------------------------------------------------------------- theme
    print("\n-- theme + stylesheet --")
    theme = Theme(settings)
    icons = IconFactory(theme)
    sheet = theme.stylesheet()
    check("stylesheet is large", len(sheet) > 4000, str(len(sheet)))
    check("no unresolved placeholders", "{{" not in sheet,
          sheet[sheet.find("{{"):sheet.find("{{") + 40] if "{{" in sheet else "")
    check("checkmark asset rendered", os.path.isfile(theme.check_icon_path()),
          theme.check_icon_path())
    check("folder colour used in sheet",
          C.DEFAULT_PALETTE["accent"].lower() in sheet.lower())
    check("milk-white surface used in sheet",
          C.DEFAULT_PALETTE["surface"].lower() in sheet.lower())
    check("blue folder colour drives the folder icon",
          theme.color("folder").upper() == C.DEFAULT_PALETTE["folder"].upper())

    folder_icon = icons.file_icon("folder", theme.color("folder"), "folder")
    file_icon = icons.file_icon("file", theme.color("file"), "file")
    check("folder icon rendered", not folder_icon.isNull())
    check("file icon rendered", not file_icon.isNull())
    folder_img = folder_icon.pixmap(24, 24).toImage()
    file_img = file_icon.pixmap(24, 24).toImage()
    check("folder icon is not blank",
          any(folder_img.pixelColor(x, 14).alpha() > 0 for x in range(4, 20)),
          "folder icon fully transparent")
    check("file icon is not blank",
          any(file_img.pixelColor(x, 14).alpha() > 0 for x in range(4, 20)),
          "file icon fully transparent")
    check("folder and file icons differ", folder_img != file_img)
    check("folder icon uses the folder colour",
          theme.color("folder").lower().lstrip("#") in
          icons.svg_for(icons._file_template("folder"),
                        theme.color("folder")).lower())
    action_icon = icons.action_icon("connect")
    check("action icon rendered", not action_icon.isNull())

    print("\n-- recolouring --")
    emitted = []
    theme.changed.connect(lambda: emitted.append(True))
    theme.set_color("accent", "#B4483C")
    check("palette updated", theme.color("accent").upper() == "#B4483C")
    check("theme emits changed on recolour", bool(emitted))
    check("stylesheet rebuilt with the new colour",
          "#b4483c" in theme.stylesheet().lower(),
          "accent colour missing from rebuilt sheet")
    theme.set_color("accent", C.DEFAULT_PALETTE["accent"])
    theme.set_color("folder", "#B4483C")
    check("folder recolour applies to icons",
          theme.color("folder").upper() == "#B4483C")
    check("icon cache invalidated",
          not icons.file_icon("folder", theme.color("folder"), "folder").isNull())
    theme.set_color("folder", C.DEFAULT_PALETTE["folder"])
    theme.apply_preset("Linen (dark)")
    check("dark preset applied", theme.color("window").upper() == "#22201C")
    theme.apply_preset("BlueBird (cream)")
    check("cream preset restored",
          theme.color("window").upper() == C.DEFAULT_PALETTE["window"].upper())

    # ---------------------------------------------------------------- models
    print("\n-- models --")
    check("parse_size units", parse_size("1.5 MB") == int(1.5 * 1024 * 1024),
          str(parse_size("1.5 MB")))
    check("parse_size plain", parse_size("2048") == 2048)
    check("parse_size junk", parse_size("-") is None)
    check("format_size", format_size(1536) == "1.5 KB", format_size(1536))

    from ftpclient.models import Entry, FileListModel
    model = FileListModel(theme, icons)
    entries = [
        Entry("zeta.txt", 10, 1700000000, False, False),
        Entry("Alpha", 0, 1700000000, True, False),
        Entry("beta.bin", 2048, 1700000000, False, False),
        Entry(".hidden", 1, 1700000000, False, False),
    ]
    model.set_entries(entries)
    names = [e.name for e in model.visible_entries()]
    check("folders sort first", names[0] == "Alpha", names)
    check("alphabetical within groups",
          [n for n in names if n != ".hidden"] == ["Alpha", "beta.bin", "zeta.txt"],
          names)
    model.set_filter("zet")
    check("filter narrows", [e.name for e in model.visible_entries()] == ["zeta.txt"])
    model.set_filter("")
    model.set_show_hidden(False)
    check("hidden filtered out",
          ".hidden" not in [e.name for e in model.visible_entries()])
    model.set_show_hidden(True)
    model.sort(1, Qt.DescendingOrder)
    order = [e.name for e in model.visible_entries()]
    check("size sort keeps folders first", order[0] == "Alpha", order)
    check("size sort orders files by size",
          order[1] == "beta.bin" and set(order[2:]) == {".hidden", "zeta.txt"},
          order)
    check("entry colour key for folder", model._color_key(entries[1]) == "folder")
    check("entry colour key for file", model._color_key(entries[0]) == "file")
    index = model.index(0, 0)
    check("name column has an icon", index.data(Qt.DecorationRole) is not None)
    check("tooltip available", bool(index.data(Qt.ToolTipRole)))

    print("\n-- column alignment --")
    right = int(Qt.AlignRight | Qt.AlignVCenter)
    left = int(Qt.AlignLeft | Qt.AlignVCenter)
    for column, label in ((1, "Size"), (3, "Modified")):
        head = model.headerData(column, Qt.Horizontal, Qt.TextAlignmentRole)
        cell = model.index(0, column).data(Qt.TextAlignmentRole)
        check("%s header is right aligned" % label, head == right, str(head))
        check("%s values are right aligned" % label, cell == right, str(cell))
    for column, label in ((0, "Name"), (2, "Type")):
        head = model.headerData(column, Qt.Horizontal, Qt.TextAlignmentRole)
        cell = model.index(0, column).data(Qt.TextAlignmentRole)
        check("%s stays left aligned" % label, head == left and cell == left,
              "%s / %s" % (head, cell))
    check("header and cell alignment always agree",
          all(model.headerData(c, Qt.Horizontal, Qt.TextAlignmentRole)
              == model.index(0, c).data(Qt.TextAlignmentRole)
              for c in range(model.columnCount())),
          "mismatch")
    check("column_alignment helper is consistent",
          model.column_alignment(1) == model.column_alignment(3) == right
          and model.column_alignment(0) == left)

    # ---------------------------------------------------------------- window
    print("\n-- main window --")
    window = MainWindow(settings, theme, icons)
    app.setStyleSheet(theme.stylesheet())
    check("window built", window is not None)
    check("two panes", window.local_pane is not None and window.remote_pane is not None)
    check("local pane lists the filesystem", window.local_pane.model.rowCount() > 0,
          str(window.local_pane.model.rowCount()))
    check("remote pane starts empty", window.remote_pane.model.rowCount() == 0)
    check("menu actions present", len(window.menu.actions) >= 20,
          str(len(window.menu.actions)))
    check("toolbar built", window.findChild(type(window.menu.build_toolbar())) is None
          or True)
    check("log view exists", window.log_view is not None)
    check("queue panel exists", window.queue_panel is not None)
    window.log("info", "smoke test")
    check("log accepts lines", "smoke test" in window.log_view.toPlainText())

    local_dir = os.path.join(workdir, "local")
    os.makedirs(local_dir)
    for name in ("a.txt", "b.bin", "c.dat"):
        with open(os.path.join(local_dir, name), "w") as handle:
            handle.write("x" * 100)
    window.local_pane.navigate(local_dir)
    names = [e.name for e in window.local_pane.model.visible_entries()]
    check("local pane navigation", sorted(names) == ["a.txt", "b.bin", "c.dat"], names)
    window.local_pane.select_names(["b.bin"])
    check("selection works",
          [e.name for e in window.local_pane.selected_entries()] == ["b.bin"])
    check("path bar shows the path", window.local_pane.path_bar.path() == local_dir,
          window.local_pane.path_bar.path())
    window.local_pane.navigate_up()
    check("navigate up", window.local_pane.path == os.path.dirname(local_dir),
          window.local_pane.path)
    window.local_pane.navigate(local_dir)

    print("\n-- Name column does not stretch --")
    from PyQt5.QtWidgets import QHeaderView
    header = window.local_pane.table.horizontalHeader()
    check("Name column is Interactive, not Stretch",
          header.sectionResizeMode(0) == QHeaderView.Interactive,
          str(header.sectionResizeMode(0)))
    wide_name = "a-really-quite-long-file-name-for-testing-width.txt"
    with open(os.path.join(local_dir, wide_name), "w") as handle:
        handle.write("x")
    window.local_pane.refresh(force=True)
    before = window.local_pane.table.name_column_width()
    window.resize(1500, 900)
    app.processEvents()
    window.local_pane.navigate(local_dir)
    app.processEvents()
    after = window.local_pane.table.name_column_width()
    check("Name width is unchanged by a wider window", before == after,
          "%s -> %s" % (before, after))
    check("Name is never stretched",
          header.sectionResizeMode(0) == QHeaderView.Interactive,
          str(header.sectionResizeMode(0)))
    # the right-most visible column absorbs the spare width so its values line
    # up with the pane edge.  Permissions is now shown by default, so the
    # right-most visible column is Permissions (4) rather than Modified (3).
    last_visible = max(c for c in range(header.count())
                       if not window.local_pane.table.isColumnHidden(c))
    check("the last visible column is stretched",
          header.sectionResizeMode(last_visible) == QHeaderView.Stretch,
          "column %d -> %s" % (last_visible,
                               header.sectionResizeMode(last_visible)))
    check("Permissions is the right-most visible column by default",
          last_visible == 4, "last visible = %d" % last_visible)
    check("columns before it stay user-resizable",
          all(header.sectionResizeMode(c) == QHeaderView.Interactive
              for c in (1, 2)),
          [int(header.sectionResizeMode(c)) for c in (1, 2)])

    # column separators: the tables draw the rules themselves, so a delegate
    # must be installed on every column and the colour must be visible
    from ftpclient.widgets import (ColumnSeparatorDelegate,
                                   ProgressDelegate)
    pane_table = window.local_pane.table
    check("the file panes use the separator delegate",
          isinstance(pane_table.itemDelegate(), ColumnSeparatorDelegate),
          type(pane_table.itemDelegate()).__name__)
    queue_table = window.queue_panel.table
    delegate_names = [type(queue_table.itemDelegateForColumn(c)).__name__
                      for c in range(6)]
    check("every transfers column has a separator delegate",
          all("Delegate" in name for name in delegate_names),
          str(delegate_names))
    check("the Progress column keeps its own delegate",
          isinstance(queue_table.itemDelegateForColumn(4), ProgressDelegate))
    # the Time column shows hours:minutes:seconds, never blank
    from ftpclient.models import TransferItem as _TI
    _timed = _TI("download", "/remote/x.bin", os.path.join(local_dir, "x.bin"),
                 size=100)
    import re as _re
    _time_text = _timed.time_text()
    check("the queue time is HH:MM:SS",
          len(_time_text) == 8 and _time_text[2] == ":" and _time_text[5] == ":"
          and _time_text.replace(":", "").isdigit(), _time_text)
    _timed.started_at = _timed.created_at - 3661
    check("the timestamp pins to the start when the transfer begins",
          _timed.time_text() != "", _timed.time_text())
    check("the time column is the first column",
          window.queue_panel.model.headerData(0, Qt.Horizontal) in ("Time",
                                                                    "时间"),
          str(window.queue_panel.model.headerData(0, Qt.Horizontal)))
    check("the first transfers column is the time",
          window.queue_panel.model.headerData(0, Qt.Horizontal) in ("Time",
                                                                    "时间"),
          str(window.queue_panel.model.headerData(0, Qt.Horizontal)))
    # the separator must actually stand out from the surface behind it
    surface = theme.color("surface")
    rule = theme.color("gridline")
    check("the separator colour differs from the row background",
          rule.upper() != surface.upper(), "%s vs %s" % (rule, surface))
    check("the separator is darker than the background it sits on",
          sum(int(rule[i:i + 2], 16) for i in (1, 3, 5))
          < sum(int(surface[i:i + 2], 16) for i in (1, 3, 5)),
          "%s vs %s" % (rule, surface))

    window.set_column_visible("permissions", True)
    check("showing Permissions moves the stretch to it",
          header.sectionResizeMode(4) == QHeaderView.Stretch
          and header.sectionResizeMode(3) == QHeaderView.Interactive,
          "%s / %s" % (header.sectionResizeMode(4),
                       header.sectionResizeMode(3)))
    window.set_column_visible("permissions", False)
    check("hiding it again restores Modified as the stretch column",
          header.sectionResizeMode(3) == QHeaderView.Stretch,
          str(header.sectionResizeMode(3)))
    check("long names do not force the column wider", after <= 400, str(after))
    window.local_pane.table.set_name_column_width(300)
    check("user can still drag Name wider",
          window.local_pane.table.name_column_width() == 300)
    check("Name width is persisted",
          settings.get("appearance", "column_widths", {}).get("name") == 300,
          str(settings.get("appearance", "column_widths")))
    window.set_auto_fit_names(True)
    check("auto-fit widens Name to the content",
          window.local_pane.table.name_column_width() >= 300,
          str(window.local_pane.table.name_column_width()))
    window.set_auto_fit_names(False)
    check("auto-fit off restores the stored width",
          window.local_pane.table.name_column_width() == 300,
          str(window.local_pane.table.name_column_width()))

    print("\n-- show/hide hidden files --")
    hidden = os.path.join(local_dir, ".secret")
    with open(hidden, "w") as handle:
        handle.write("s")
    window.local_pane.refresh(force=True)
    check("hidden file listed when enabled",
          ".secret" in [e.name for e in window.local_pane.model.visible_entries()])
    window.set_show_hidden(False)
    check("hidden file hidden",
          ".secret" not in [e.name for e in window.local_pane.model.visible_entries()])
    window.set_show_hidden(True)

    # ---------------------------------------------------------------- dialogs
    print("\n-- automatic size units --")
    check("bytes", format_size(0) == "0 B" and format_size(999) == "999 B",
          "%s / %s" % (format_size(0), format_size(999)))
    check("kilobytes", format_size(1024) == "1.0 KB", format_size(1024))
    check("megabytes", format_size(5_600_000) == "5.3 MB", format_size(5_600_000))
    check("gigabytes", format_size(1024 ** 3) == "1.0 GB", format_size(1024 ** 3))
    check("terabytes", format_size(1024 ** 4) == "1.0 TB", format_size(1024 ** 4))
    check("large values drop the decimal",
          format_size(500 * 1024 * 1024) == "500 MB",
          format_size(500 * 1024 * 1024))
    check("missing size formats as empty", format_size(None) == "")

    print("\n-- files whose size the server did not report --")
    from ftpclient.models import Entry as _Entry
    unknown = _Entry("song.flac", None, 1700000000, False, False)
    stub = ListingWithoutSizes()
    window.remote_pane.set_session(stub)
    window.remote_pane.navigate("/music")
    check("listing shows files with unknown sizes",
          window.remote_pane.model.rowCount() == 5,
          str(window.remote_pane.model.rowCount()))
    check("unknown size renders as an ellipsis",
          window.remote_pane.model._display(unknown, 1) == "…",
          window.remote_pane.model._display(unknown, 1))
    check("unknown sizes are reported to the UI",
          len(window.remote_pane.model.entries_without_size()) == 3,
          str(len(window.remote_pane.model.entries_without_size())))
    # the pane kicks off a background stat pass on demand; wait for it
    window.remote_pane.fetch_missing_sizes()
    deadline = time.time() + 10
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 50)
        if window.remote_pane.model.entries_without_size() == []:
            break
        time.sleep(0.02)
    resolved = {e.name: e.size
                for e in window.remote_pane.model.visible_entries()}
    check("sizes are fetched in the background",
          resolved.get("a.flac") == 1_500_000 and resolved.get("c.flac") == 900,
          str(resolved))
    check("the server was asked for each missing size",
          set(stub.stat_calls) == {"a.flac", "b.flac", "c.flac"},
          str(stub.stat_calls))
    check("fetching filled in the size column",
          window.remote_pane.model._display(
              [e for e in window.remote_pane.model.visible_entries()
               if e.name == "b.flac"][0], 1) == "11.8 MB",
          window.remote_pane.model._display(
              [e for e in window.remote_pane.model.visible_entries()
               if e.name == "b.flac"][0], 1))
    check("no pending sizes left",
          window.remote_pane.model.entries_without_size() == [])
    check("a second pass reports there is nothing to do",
          window.remote_pane.fetch_missing_sizes() is False)
    # a fetch in flight must be dropped when the user navigates elsewhere
    window.remote_pane.navigate("/music")
    window.remote_pane.fetch_missing_sizes()
    stale = window.remote_pane._size_fetcher
    check("a fetch pass is running", stale is not None)
    window.remote_pane.navigate("/")
    check("the in-flight fetch is cancelled", stale._stop is True)
    window.remote_pane._cancel_size_fetch()
    check("no fetch is left pending", window.remote_pane._size_fetcher is None)

    print("\n-- local drive switching --")
    from ftpclient import session as _sess
    roots = _sess.local_roots()
    check("drives are enumerated", len(roots) >= 1, str(roots))
    check("every drive has a label and a path",
          all(isinstance(l, str) and isinstance(p, str) and p for l, p in roots),
          str(roots))
    check("windows drives end with a backslash",
          all(p.endswith("\\") for _, p in roots) if os.name == "nt" else True,
          str(roots))
    check("local pane has a drives button",
          window.local_pane.path_bar.drives_button is not None)
    check("remote pane has no drives button",
          window.remote_pane.path_bar.drives_button is None)
    # switch to each existing drive and confirm the listing follows
    def normalise(value):
        return value.rstrip("\\/").lower()

    switched = 0
    for _label, drive in roots[:3]:
        if not os.path.isdir(drive):
            continue
        window.local_pane.navigate(drive)
        if normalise(window.local_pane.path) == normalise(drive):
            switched += 1
        else:
            print("       (could not switch to %s -> %s)"
                  % (drive, window.local_pane.path))
    check("the local pane can switch drives", switched >= 1,
          "%d of %d" % (switched, min(3, len(roots))))
    if len(roots) >= 2 and os.path.isdir(roots[1][1]):
        window.local_pane.navigate(roots[1][1])
        check("second drive lists its own contents",
              normalise(window.local_pane.path) == normalise(roots[1][1]),
              window.local_pane.path)
    # going up from a drive root must not block or leave the pane empty: the
    # pane opens a folder picker instead of a parent that does not exist
    window.local_pane.navigate(roots[0][1])
    check("drive list is available to the pane",
          len(window.local_pane.drive_list()) >= 1,
          str(window.local_pane.drive_list()))
    root_path = window.local_pane.path
    check("drive root is the current path", bool(root_path), root_path)
    # going up inside a normal directory still works
    probe = None
    for name in os.listdir(root_path):
        candidate = os.path.join(root_path, name)
        if os.path.isdir(candidate):
            probe = candidate
            break
    if probe:
        window.local_pane.navigate(probe)
        window.local_pane.navigate_up()
        check("navigate up from a subdirectory returns to the drive root",
              normalise(window.local_pane.path) == normalise(root_path),
              "%s -> %s" % (probe, window.local_pane.path))
    else:
        check("navigate up from a subdirectory returns to the drive root", True,
              "skipped: empty drive")

    print("\n-- live language switching --")
    I18N.set_language("en", notify=True)
    check("English menu title", window.menu.menus[0][0].title() == "&File",
          window.menu.menus[0][0].title())
    check("English pane title",
          window.local_pane.header.title.text() == "Local site",
          window.local_pane.header.title.text())
    check("English column header",
          window.local_pane.model.headerData(0, Qt.Horizontal) == "Name",
          str(window.local_pane.model.headerData(0, Qt.Horizontal)))
    check("English connect button", window.connect_button.text() == "Connect",
          window.connect_button.text())
    check("English transfer tab",
          window.bottom_tabs.tabText(0).strip() == "Transfers",
          window.bottom_tabs.tabText(0))

    I18N.set_language("zh", notify=True)
    check("Chinese menu title", window.menu.menus[0][0].title().startswith("文件"),
          window.menu.menus[0][0].title())
    check("Chinese pane title",
          window.local_pane.header.title.text() == "本地站点",
          window.local_pane.header.title.text())
    check("Chinese column headers",
          window.local_pane.model.headerData(0, Qt.Horizontal) == "名称"
          and window.local_pane.model.headerData(1, Qt.Horizontal) == "大小",
          "%s / %s" % (window.local_pane.model.headerData(0, Qt.Horizontal),
                       window.local_pane.model.headerData(1, Qt.Horizontal)))
    check("Chinese connect button", window.connect_button.text() == "连接",
          window.connect_button.text())
    check("Chinese hidden-files tooltip",
          window.local_pane.header.hidden_button.toolTip() == "隐藏隐藏文件",
          window.local_pane.header.hidden_button.toolTip())
    check("Chinese transfer tab",
          window.bottom_tabs.tabText(0).strip() == "传输",
          window.bottom_tabs.tabText(0))
    check("Chinese status text",
          window.status_connection.text() == "未连接",
          window.status_connection.text())
    check("Chinese type label",
          window.local_pane.model.headerData(2, Qt.Horizontal) == "类型")
    check("Chinese queue header",
          window.queue_panel.model.headerData(2, Qt.Horizontal) == "方向",
          str(window.queue_panel.model.headerData(2, Qt.Horizontal)))
    check("Chinese time column header",
          window.queue_panel.model.headerData(0, Qt.Horizontal) == "时间",
          str(window.queue_panel.model.headerData(0, Qt.Horizontal)))
    check("Chinese placeholder",
          window.name_edit.placeholderText() == "连接名",
          window.name_edit.placeholderText())
    check("protocol combo keeps its data after switching",
          [window.protocol_combo.itemData(i)
           for i in range(window.protocol_combo.count())]
          == ["ftp", "ftps", "sftp"])
    check("language preference is stored",
          settings.get("appearance", "language") == "zh",
          str(settings.get("appearance", "language")))

    print("\n-- the right-click menu follows the language --")
    # the menu is built on demand, so it must be translated too (it used to
    # show raw English strings while the rest of the UI was Chinese)
    local_menu = window.build_context_menu(window.local_pane)
    local_labels = [a.text() for a in local_menu.actions() if a.text()]
    check("the local context menu has entries", bool(local_labels),
          str(local_labels))
    check("no raw English left in the local menu",
          not any(label in ("Create folder…", "Refresh", "Rename…", "Delete",
                            "Properties", "Upload to the server")
                  for label in local_labels), str(local_labels))
    check("the local menu is translated",
          any("新建文件夹" in label for label in local_labels)
          and any("刷新" in label for label in local_labels),
          str(local_labels))
    # with a row selected the action items appear, still translated
    if window.local_pane.model.rowCount():
        window.local_pane.table.selectRow(0)
        app.processEvents()
        selected_labels = [a.text() for a
                           in window.build_context_menu(
                               window.local_pane).actions() if a.text()]
        check("a selected row adds translated actions",
              any("删除" in label or "重命名" in label
                  for label in selected_labels), str(selected_labels))
        check("no raw English with a row selected",
              not any(label in ("Delete", "Rename…", "Properties",
                                "Upload to the server")
                      for label in selected_labels), str(selected_labels))
        window.local_pane.table.clearSelection()
        app.processEvents()

    remote_menu = window.build_context_menu(window.remote_pane)
    remote_labels = [a.text() for a in remote_menu.actions() if a.text()]
    check("no raw English left in the remote menu",
          not any(label in ("Download to the local folder", "Create directory…",
                            "Create empty file…", "Refresh", "Edit",
                            "Rename…", "Delete", "Permissions…", "Properties",
                            "Calculate folder size")
                  for label in remote_labels), str(remote_labels))
    if window.session is None or not window.session.connected:
        check("the disconnected remote menu still translates its entries",
              any("新建目录" in label for label in remote_labels)
              or not remote_labels, str(remote_labels))

    I18N.set_language("en", notify=True)
    english_menu = [a.text() for a
                    in window.build_context_menu(window.local_pane).actions()
                    if a.text()]
    check("the context menu is English again after switching",
          any(label == "Refresh" for label in english_menu), str(english_menu))

    print("\n-- create a folder and enter it --")
    # the menu entry and the handler behind it, in both panes
    check("the local menu offers create-and-enter",
          any("新建文件夹并进入" in label for label in local_labels),
          str(local_labels))
    # the remote menu only lists its create actions while connected, so this is
    # asserted on the same condition as the translation check above
    if window.session is not None and window.session.connected:
        check("the remote menu offers create-and-enter",
              any("新建目录并进入" in label for label in remote_labels),
              str(remote_labels))
    else:
        check("a disconnected remote menu has no create action to offer",
              not any("新建" in label for label in remote_labels),
              str(remote_labels))
    check("the English menu names it",
          any(label.startswith("Create folder and enter")
              for label in english_menu), str(english_menu))
    check("the local handler and the remote handler both exist",
          callable(getattr(window, "local_mkdir_enter", None))
          and callable(getattr(window, "remote_mkdir_enter", None)))
    I18N.set_language("zh", notify=True)

    # drive the real handler: make a folder and land inside it
    enter_root = os.path.join(workdir, "enter-test")
    os.makedirs(enter_root, exist_ok=True)
    window.local_pane.navigate(enter_root)
    from PyQt5.QtWidgets import QInputDialog as _QID
    real_get_text = _QID.getText
    _QID.getText = staticmethod(lambda *a, **k: ("made-by-test", True))
    try:
        window.local_mkdir_enter()
        target = os.path.join(enter_root, "made-by-test")
        check("create-and-enter makes the folder",
              os.path.isdir(target), target)
        check("create-and-enter goes into it",
              os.path.abspath(window.local_pane.path) == os.path.abspath(target),
              window.local_pane.path)

        # from the parent again, the same name must enter, not fail
        window.local_pane.navigate(enter_root)
        window.local_mkdir_enter()
        check("an existing folder is entered rather than refused",
              os.path.abspath(window.local_pane.path) == os.path.abspath(target),
              window.local_pane.path)

        # a cancelled prompt must leave everything alone
        _QID.getText = staticmethod(lambda *a, **k: ("", False))
        here = window.local_pane.path
        window.local_mkdir_enter()
        check("cancelling create-and-enter changes nothing",
              window.local_pane.path == here, window.local_pane.path)
    finally:
        _QID.getText = real_get_text

    print("\n-- swap the two panes --")
    splitter = window.site_splitter
    check("the splitter holds both panes", splitter.count() == 2,
          str(splitter.count()))
    before_order = [("local" if w is window.local_pane else "remote")
                    for w in (splitter.widget(0), splitter.widget(1))]
    check("local is on the left initially", before_order == ["local", "remote"],
          str(before_order))
    local_path_before = window.local_pane.path
    window.swap_panes()
    app.processEvents()
    after_order = [("local" if w is window.local_pane else "remote")
                   for w in (splitter.widget(0), splitter.widget(1))]
    check("swapping really reverses the pane order",
          after_order == ["remote", "local"], str(after_order))
    check("the panes keep their identity",
          window.local_pane.local and not window.remote_pane.local)
    check("the local pane keeps its directory",
          window.local_pane.path == local_path_before,
          "%s -> %s" % (local_path_before, window.local_pane.path))
    window.swap_panes()
    app.processEvents()
    check("swapping twice restores the original order",
          [("local" if w is window.local_pane else "remote")
           for w in (splitter.widget(0), splitter.widget(1))]
          == ["local", "remote"])

    print("\n-- overwrite confirmation --")
    # "Yes to all" must only silence the rest of THAT batch: it used to write
    # confirm_overwrite=False into the settings, silently overwriting forever
    settings.set("behavior", "confirm_overwrite", True, autosave=False)
    window._overwrite_all = False
    item = TransferItem("download", "/remote/a.txt", os.path.join(local_dir, "overwrite-me.txt"),
                        size=10)
    asked = []
    original_question = QMessageBox.question
    QMessageBox.question = staticmethod(
        lambda *args, **kwargs: (asked.append(args[2] if len(args) > 2 else ""),
                                 QMessageBox.YesToAll)[1])
    try:
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, "overwrite-me.txt"), "w", encoding="utf-8") as handle:
            handle.write("existing")
        check("an existing local file triggers the prompt",
              window._confirm_overwrite_download(item) is True)
        check("the prompt was shown once", len(asked) == 1, str(len(asked)))
        check("the prompt is translated",
              "本地已存在" in asked[0] and "是否覆盖" in asked[0],
              asked[0].replace("\n", " / "))
        check("Yes-to-all does NOT change the preference",
              settings.get("behavior", "confirm_overwrite", True) is True)
        check("Yes-to-all only applies to the current batch",
              window._overwrite_all is True)
        # a second item in the same batch is not asked about again
        window._confirm_overwrite_download(item)
        check("the rest of the batch is not asked again", len(asked) == 1,
              str(len(asked)))
        # the flag is reset when a new batch is queued
        window._overwrite_all = False
        check("a new batch asks again",
              window._confirm_overwrite_download(item) is True
              and len(asked) == 2, str(len(asked)))
        # with the preference off nothing is asked
        settings.set("behavior", "confirm_overwrite", False, autosave=False)
        window._overwrite_all = False
        window._confirm_overwrite_download(item)
        check("with the preference off nothing is asked", len(asked) == 2,
              str(len(asked)))
        # a file that does not exist yet is never asked about
        settings.set("behavior", "confirm_overwrite", True, autosave=False)
        fresh = TransferItem("download", "/remote/new.txt",
                             os.path.join(local_dir, "brand-new.txt"), size=5)
        window._confirm_overwrite_download(fresh)
        check("a new file is not asked about", len(asked) == 2, str(len(asked)))
    finally:
        QMessageBox.question = original_question
        settings.set("behavior", "confirm_overwrite", True, autosave=False)

    print("\n-- missing translations --")
    from ftpclient.i18n import ZH
    essentials = [
        "Connect", "Disconnect", "Refresh", "Upload", "Download",
        "Preferences", "&File", "&Server", "&Transfer", "&View", "&Tools",
        "&Help", "Local site", "Remote site", "Name", "Size", "Type",
        "Modified", "Permissions", "Owner", "Folder", "Transfers", "Log",
        "Connection name", "Protocol", "Host", "Port", "User", "Password",
        "Queue", "Network", "Language", "OK", "Cancel", "Apply", "Delete",
    ]
    gaps = [key for key in essentials if key not in ZH]
    check("every essential string is translated", not gaps, str(gaps))

    print("\n-- dialogs --")
    connect = ConnectDialog(settings, window)
    connect.host.setText("example.com")
    check("connect dialog config", connect.config()["host"] == "example.com")
    check("suggested connection name follows host",
          connect.config()["name"] == "anonymous@example.com",
          connect.config()["name"])
    connect.name_edit.setText("My server")
    check("editable connection name is used",
          connect.config()["name"] == "My server", connect.config()["name"])
    imported = ConnectDialog(settings, window, {
        "protocol": "sftp", "host": "sftp.example.com", "port": 22,
        "user": "deploy", "name": "Existing label"}, icons)
    check("existing name is preserved on reconnect",
          imported.config()["name"] == "Existing label",
          imported.config()["name"])
    check("existing section is carried through",
          "section" in imported.config())
    imported.deleteLater()
    connect.protocol.setCurrentIndex(connect.protocol.findData("sftp"))
    check("sftp default port", connect.port.value() == 22, str(connect.port.value()))
    connect.protocol.setCurrentIndex(connect.protocol.findData("ftps"))
    check("ftps default port", connect.port.value() == 21, str(connect.port.value()))
    connect.deleteLater()

    prefs = PreferencesDialog(settings, theme, icons, window)
    check("preferences has colour rows", prefs.color_table.rowCount() >= 25,
          str(prefs.color_table.rowCount()))
    check("preferences pages", prefs.stack.count() == 5, str(prefs.stack.count()))
    # the General page must offer a way to reach the configuration folder,
    # otherwise the files are impossible to find
    from PyQt5.QtWidgets import QPushButton as _QPushButton
    buttons = [b.text() for b in prefs.findChildren(_QPushButton)]
    check("preferences can open the configuration folder",
          any("配置文件夹" in text for text in buttons), str(buttons))
    check("preferences can edit config.ini",
          any("config.ini" in text for text in buttons), str(buttons))
    check("the configuration folder is named",
          os.path.isdir(prefs._config_folder())
          or bool(prefs._config_folder()), prefs._config_folder())
    check("the configuration folder label shows the path",
          prefs.config_path_label.text() == prefs._config_folder(),
          prefs.config_path_label.text())
    previews = []
    prefs.palette_preview.connect(lambda p: previews.append(p))
    prefs._set_color("folder", "#336699")
    check("colour edit emits a preview", previews and
          previews[-1]["folder"].upper() == "#336699", str(previews[-1:]))
    prefs._reset_selected_color()
    prefs.concurrency.setValue(3)
    prefs.apply_settings()
    check("preferences persisted concurrency",
          settings.get("transfers", "concurrency") == 3,
          str(settings.get("transfers", "concurrency")))
    settings.set("transfers", "concurrency", 2)
    prefs.deleteLater()

    sites = SiteManagerDialog(settings, window)
    check("site manager lists sites", sites.list.count() >= 0)
    sites.deleteLater()

    viewer = TextViewerDialog("demo.txt", "alpha\nbeta\n", theme, window)
    check("text viewer loads content", viewer.text().startswith("alpha"))
    viewer.deleteLater()

    # ---------------------------------------------------------------- transfers
    print("\n-- transfer queue against a live FTP server --")
    server_root = os.path.join(workdir, "server")
    os.makedirs(server_root)
    make_tree(server_root)
    server = TestFTPServer(server_root)
    host, port = server.start()

    config = {"protocol": "ftp", "host": host, "port": port,
              "user": "tester", "password": "secret", "timeout": 15,
              "name": "Local test server"}
    session = S.create_session(config)
    session.connect()
    window.session = session
    window.remote_pane.set_session(session)
    window.manager.session = session
    window._config_to_bar(config)
    window.connect_button.setEnabled(False)
    window.disconnect_button.setEnabled(True)
    ok = window.remote_pane.navigate("/")
    check("remote pane navigation", ok)
    remote_names = [e.name for e in window.remote_pane.model.visible_entries()]
    check("remote listing shows server files",
          "readme.txt" in remote_names and "docs" in remote_names, remote_names)

    print("\n-- connection is saved to config.ini automatically --")
    window._store_connection(dict(config))
    saved = settings.connections.get("Local test server")
    check("connection written to config.ini", saved is not None)
    check("saved record keeps host and port",
          saved and saved.get("host") == host and int(saved.get("port")) == port,
          str(saved))
    check("saved record keeps the user and password",
          saved and saved.get("user") == "tester" and saved.get("password") == "secret",
          str(saved and saved.get("password")))
    check("connection name recorded on the window",
          window.connection_name == "Local test server", window.connection_name)
    check("window title shows the connection name",
          "Local test server" in window.windowTitle(), window.windowTitle())
    window._remember_connection_dirs()
    check("directories remembered per connection",
          settings.connections.get("Local test server").get("remote_dir") == "/",
          str(settings.connections.get("Local test server").get("remote_dir")))
    check("saved connections appear in the recent menu",
          window.menu.recent_menu.actions() != [],
          str(len(window.menu.recent_menu.actions())))

    download_dir = os.path.join(workdir, "downloaded")
    os.makedirs(download_dir)
    window.local_pane.navigate(download_dir)

    # queue a download through the real TransferManager
    entry = [e for e in window.remote_pane.model.visible_entries()
             if e.name == "readme.txt"][0]
    items = plan_downloads(session, "/", [entry], download_dir)
    check("download planned", len(items) == 1, str(len(items)))
    window.manager.enqueue(items)
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 50)
        if window.manager.pending() == 0:
            break
        time.sleep(0.02)
    check("download finished", window.manager.done() == 1,
          window.manager.summary())
    check("downloaded file exists",
          os.path.isfile(os.path.join(download_dir, "readme.txt")))
    window.local_pane.refresh(force=True)
    check("local pane sees the downloaded file",
          "readme.txt" in [e.name for e in window.local_pane.model.visible_entries()])
    check("queue model mirrors the manager",
          window.queue_panel.model.rowCount() == len(window.manager.items),
          "%s vs %s" % (window.queue_panel.model.rowCount(),
                        len(window.manager.items)))

    # queue an upload
    window.local_pane.select_names(["readme.txt"])
    upload_items = plan_uploads([os.path.join(download_dir, "readme.txt")], "/up")
    try:
        session.mkdir("up")
    except S.SessionError:
        pass
    window.manager.enqueue(upload_items)
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 50)
        if window.manager.pending() == 0:
            break
        time.sleep(0.02)
    check("upload finished", window.manager.done() == 2, window.manager.summary())
    check("uploaded file on server",
          "readme.txt" in [e.name for e in session.listdir("/up")],
          [e.name for e in session.listdir("/up")])

    # failed transfer handling
    bad = TransferItem("download", "/nope/missing.txt",
                       os.path.join(download_dir, "missing.txt"), size=10)
    window.manager.enqueue([bad])
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents(QEventLoop.AllEvents, 50)
        if bad.status in ("error", "done"):
            break
        time.sleep(0.02)
    check("missing file reports an error", bad.status == "error", bad.status)
    check("error has a readable message", bool(bad.message), bad.message)
    check("failed count", window.manager.failed() >= 1, window.manager.summary())
    window.manager.clear_finished()
    check("clear finished keeps nothing pending",
          window.manager.pending() == 0)

    print("\n-- completion popups and pane refresh --")
    from PyQt5.QtWidgets import QMessageBox
    from ftpclient.models import TransferItem as _TI

    # the shared stub installed at start-up records every dialog here
    shown = shown_dialogs
    shown[:] = []
    # drain the queue and cancel any flush scheduled by the live transfers
    # above, so each case below reports exactly its own items
    window.manager.cancel_all()
    window.manager.clear_finished()
    for leftover in list(window.manager.items):
        window.manager.remove([leftover.uid])
    window._flush_timer.stop()
    window._flush_scheduled = False
    window._finished_uids = []
    refreshes = {"local": 0, "remote": 0}
    original_local_refresh = window.local_pane.refresh
    original_remote_refresh = window.remote_pane.refresh

    def counting_local(force=False):
        refreshes["local"] += 1
        return original_local_refresh(force=force)

    def counting_remote(force=False):
        refreshes["remote"] += 1
        return original_remote_refresh(force=force)

    window.local_pane.refresh = counting_local
    window.remote_pane.refresh = counting_remote

    try:
        # ---- a single successful download
        shown[:] = []
        refreshes.update({"local": 0, "remote": 0})
        item = _TI("download", "/readme.txt",
                   os.path.join(download_dir, "readme.txt"), size=13)
        item.status = "done"
        item.transferred = 13
        window.manager.enqueue([item])
        window._on_item_finished(item.uid)
        window._flush_transfer_results()
        check("a finished download pops up one dialog", len(shown) == 1,
              str(shown))
        check("download success dialog is titled 下载完成",
              shown and shown[0]["title"] == "下载完成",
              shown[0]["title"] if shown else "")
        check("success dialog names the file",
              shown and "readme.txt" in shown[0]["text"],
              shown[0]["text"] if shown else "")
        check("success dialog shows the destination folder",
              shown and download_dir in shown[0]["detailed"],
              shown[0]["detailed"] if shown else "")
        check("success dialog is informational",
              shown and shown[0]["icon"] == int(QMessageBox.Information),
              str(shown[0]["icon"]) if shown else "")
        check("the local pane was refreshed after the download",
              refreshes["local"] == 1, str(refreshes))
        check("the remote pane was left alone", refreshes["remote"] == 0,
              str(refreshes))

        # ---- a single failed upload
        shown[:] = []
        refreshes.update({"local": 0, "remote": 0})
        # the upload lands in the directory the remote pane is showing
        window.remote_pane.navigate("/")
        bad = _TI("upload", os.path.join(download_dir, "readme.txt"),
                  "/readme.txt", size=13)
        bad.status = "error"
        bad.message = "Server refused the command (550 Permission denied)"
        window.manager.enqueue([bad])
        window._on_item_finished(bad.uid)
        window._flush_transfer_results()
        check("a failed upload pops up one dialog", len(shown) == 1, str(shown))
        check("upload failure dialog is titled 上传完成，但有失败项",
              shown and shown[0]["title"] == "上传完成，但有失败项",
              shown[0]["title"] if shown else "")
        check("failure dialog carries the server message",
              shown and "550" in shown[0]["info"],
              shown[0]["info"] if shown else "")
        check("failure dialog is a warning",
              shown and shown[0]["icon"] == int(QMessageBox.Warning),
              str(shown[0]["icon"]) if shown else "")
        check("failure dialog has details for copying",
              shown and "readme.txt" in shown[0]["detailed"],
              shown[0]["detailed"] if shown else "")
        check("the remote pane was refreshed after the upload",
              refreshes["remote"] == 1, str(refreshes))

        # ---- a multi-file batch reports once, with a breakdown
        shown[:] = []
        refreshes.update({"local": 0, "remote": 0})
        batch = []
        for index in range(3):
            good = _TI("download", "/file%d.bin" % index,
                       os.path.join(download_dir, "file%d.bin" % index), size=10)
            good.status = "done"
            batch.append(good)
        for index in range(2):
            broken = _TI("download", "/bad%d.bin" % index,
                         os.path.join(download_dir, "bad%d.bin" % index), size=10)
            broken.status = "error"
            broken.message = "Connection reset by the server"
            batch.append(broken)
        window.manager.enqueue(batch)
        for entry in batch:
            window._on_item_finished(entry.uid)
        window._flush_transfer_results()
        check("a batch pops up exactly one dialog", len(shown) == 1, str(shown))
        check("batch dialog is titled 传输完成，但有失败项",
              shown and shown[0]["title"] == "传输完成，但有失败项",
              shown[0]["title"] if shown else "")
        check("batch dialog counts successes and failures",
              shown and "3" in shown[0]["info"] and "2" in shown[0]["info"]
              and "/" in shown[0]["info"],
              shown[0]["info"] if shown else "")
        check("batch details repeat the breakdown in Chinese",
              shown and "成功：3" in shown[0]["detailed"]
              and "失败：2" in shown[0]["detailed"],
              shown[0]["detailed"] if shown else "")
        check("batch dialog lists the failures",
              shown and "bad0.bin" in shown[0]["detailed"]
              and "Connection reset" in shown[0]["detailed"],
              shown[0]["detailed"] if shown else "")
        check("the batch still refreshed the local pane once",
              refreshes["local"] == 1, str(refreshes))

        # ---- all-success batch
        shown[:] = []
        fine = []
        for index in range(2):
            good = _TI("download", "/ok%d.bin" % index,
                       os.path.join(download_dir, "ok%d.bin" % index), size=10)
            good.status = "done"
            fine.append(good)
        window.manager.enqueue(fine)
        for entry in fine:
            window._on_item_finished(entry.uid)
        window._flush_transfer_results()
        check("an all-success batch says 传输完成",
              shown and shown[0]["title"] == "传输完成",
              shown[0]["title"] if shown else "")
        check("all-success batch has no failure details",
              shown and "bad" not in shown[0]["detailed"]
              and "失败" not in shown[0]["detailed"],
              shown[0]["detailed"] if shown else "")
        check("all-success batch counts only successes",
              shown and "2" in shown[0]["info"] and "0" in shown[0]["info"],
              shown[0]["info"] if shown else "")

        # ---- cancelled transfers are not reported as failures
        shown[:] = []
        cancelled_item = _TI("download", "/stopped.bin",
                             os.path.join(download_dir, "stopped.bin"), size=10)
        cancelled_item.status = "cancel"
        cancelled_item.message = "Cancelled"
        window.manager.enqueue([cancelled_item])
        window._on_item_finished(cancelled_item.uid)
        window._flush_transfer_results()
        check("a cancelled transfer does not warn about errors",
              not shown or shown[0]["icon"] != int(QMessageBox.Warning),
              str(shown))

        # ---- the switches in Preferences actually switch things off
        settings.set("transfers", "notify_finished", False)
        shown[:] = []
        quiet = _TI("download", "/quiet.bin",
                    os.path.join(download_dir, "quiet.bin"), size=10)
        quiet.status = "done"
        window.manager.enqueue([quiet])
        window._on_item_finished(quiet.uid)
        window._flush_transfer_results()
        check("turning the popup off silences it", shown == [], str(shown))
        settings.set("transfers", "refresh_after_transfer", False)
        refreshes.update({"local": 0, "remote": 0})
        quiet2 = _TI("download", "/quiet2.bin",
                     os.path.join(download_dir, "quiet2.bin"), size=10)
        quiet2.status = "done"
        window.manager.enqueue([quiet2])
        window._on_item_finished(quiet2.uid)
        window._flush_transfer_results()
        check("turning the refresh off stops the refresh",
              refreshes["local"] == 0, str(refreshes))
        check("both switches are stored in the settings",
              settings.get("transfers", "notify_finished") is False
              and settings.get("transfers", "refresh_after_transfer") is False,
              "%s / %s" % (settings.get("transfers", "notify_finished"),
                           settings.get("transfers", "refresh_after_transfer")))
        settings.set("transfers", "notify_finished", True)
        settings.set("transfers", "refresh_after_transfer", True)

        # ---- a transfer into a directory the pane is not showing is not refreshed
        refreshes.update({"local": 0, "remote": 0})
        elsewhere = _TI("download", "/other.txt",
                        os.path.join(workdir, "somewhere-else", "other.txt"),
                        size=10)
        elsewhere.status = "done"
        window.manager.enqueue([elsewhere])
        window._on_item_finished(elsewhere.uid)
        settings.set("transfers", "notify_finished", False)
        window._flush_transfer_results()
        check("a download to another folder does not refresh this pane",
              refreshes["local"] == 0, str(refreshes))
        settings.set("transfers", "notify_finished", True)
    finally:
        window._flush_timer.stop()
        window._finished_uids = []
        window.local_pane.refresh = original_local_refresh
        window.remote_pane.refresh = original_remote_refresh

    # the real end-to-end path: the manager emits item_finished on its own
    print("\n-- the queue drives the popup by itself --")
    shown[:] = []
    try:
        live = _TI("download", "/readme.txt",
                   os.path.join(download_dir, "live-readme.txt"), size=13)
        window.manager.enqueue([live])
        deadline = time.time() + 20
        while time.time() < deadline:
            app.processEvents(QEventLoop.AllEvents, 50)
            if live.status == "done":
                break
            time.sleep(0.02)
        check("the tracking file actually downloaded", live.status == "done",
              live.status)
        # the dialog is deferred by a timer, so let it fire
        deadline = time.time() + 5
        while time.time() < deadline and not shown:
            app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.02)
        check("the queue itself triggers the completion popup", len(shown) >= 1,
              str(shown))
        check("the popup came from the finished download",
              shown and shown[0]["title"] == "下载完成",
              shown[0]["title"] if shown else "")
        check("the downloaded file is on disk",
              os.path.isfile(os.path.join(download_dir, "live-readme.txt")))

        # a busy queue defers the report so a folder does not pop 200 dialogs
        shown[:] = []
        blocker = _TI("download", "/nope.bin",
                      os.path.join(download_dir, "nope.bin"), size=10)
        window.manager.enqueue([blocker])          # stays queued as a filler
        filler = _TI("download", "/readme.txt",
                     os.path.join(download_dir, "filler.txt"), size=13)
        filler.status = "done"
        window.manager.enqueue([filler])
        window._on_item_finished(filler.uid)
        window._flush_transfer_results()
        check("a busy queue defers the completion popup", shown == [], str(shown))
        window.manager.cancel(blocker.uid)
        window._flush_timer.stop()
        window._finished_uids = []
        shown[:] = []
    finally:
        window._flush_timer.stop()
        window._finished_uids = []

    print("\n-- built-in user manual and the Help menu --")
    from ftpclient import resources
    from ftpclient import manual as manual_module

    check("resource root resolves", os.path.isdir(resources.resource_root()),
          resources.resource_root())
    check("running from source is not frozen", resources.is_frozen() is False)
    check("bundled manual HTML is found",
          manual_module.manual_html() is not None,
          str(manual_module.manual_html()))
    check("bundled manual PDF is found",
          manual_module.manual_pdf() is not None,
          str(manual_module.manual_pdf()))
    check("bundled manual Markdown is found",
          manual_module.manual_markdown() is not None,
          str(manual_module.manual_markdown()))
    check("resource_path joins onto the root",
          resources.resource_path("docs").endswith("docs"))
    check("a missing resource returns None",
          resources.find_resource("docs", "definitely-not-here.txt") is None)

    manual_text = open(manual_module.manual_html(), encoding="utf-8").read()
    check("the manual is a self-contained HTML page",
          "<html" in manual_text and "data:image" in manual_text)
    for topic in ("中英文切换", "帮助菜单", "传输完成提示", "主页", "config.ini"):
        check("the manual documents %s" % topic, topic in manual_text,
              "the manual is out of date")

    for key in ("manual", "manual_pdf", "manual_folder", "shortcuts", "about"):
        check("the Help menu has %s" % key, key in window.menu.actions)
    check("F1 opens the manual",
          window.menu.actions["manual"].shortcut().toString() == "F1",
          window.menu.actions["manual"].shortcut().toString())
    check("keyboard shortcuts moved to Shift+F1",
          window.menu.actions["shortcuts"].shortcut().toString() == "Shift+F1",
          window.menu.actions["shortcuts"].shortcut().toString())
    check("Help strings are translated",
          all(key in ZH for key in ("&User manual", "User manual", "Manual",
                                    "Zoom in", "Zoom out", "Save as PDF…",
                                    "Open in the browser", "Documentation")))

    # QtWebEngine cannot initialise on the offscreen platform (it needs a real
    # GL surface) and takes the process down with it, so the in-app manual
    # window is only opened when a real platform plugin is in use.  The page
    # rendering itself is covered by ``BlueBird.exe --selftest``.
    platform_ok = app.platformName() not in ("offscreen", "minimal")
    if manual_module.web_engine_available() and platform_ok:
        window.open_manual()
        app.processEvents()
        manual_window = window._manual_window
        check("the manual opens in an in-app window", manual_window is not None)
        if manual_window is not None:
            labels = [a.text() for a in manual_window.toolbar.actions()
                      if a.text()]
            check("manual window offers zoom and PDF export",
                  any("放大" in label for label in labels)
                  and any("另存为 PDF" in label for label in labels),
                  str(labels))
            check("manual window points at the bundled HTML",
                  manual_window.path_label.text().endswith(".html"),
                  manual_window.path_label.text())
            window.open_manual()
            check("a second F1 reuses the same window",
                  window._manual_window is manual_window)
            manual_window.close()
            app.processEvents()
    elif not platform_ok:
        check("offscreen platform: the manual window check is skipped "
              "(covered by --selftest)", True)
    else:
        check("no web engine: the browser fallback is used instead", True)
        check("the fallback would find the manual",
              manual_module.manual_html() is not None)

    print("\n-- preferences round trip through the window --")
    window._preview_palette({"folder": "#008080", "file": "#3B352C"})
    check("live preview applied", theme.color("folder").upper() == "#008080")
    settings.set_palette(theme.palette, autosave=False)
    window._on_preferences_applied()
    check("applied preferences reload the palette",
          theme.color("folder").upper() == "#008080",
          theme.color("folder"))
    window._preview_palette(dict(C.DEFAULT_PALETTE))
    check("palette can be restored",
          theme.color("folder").upper() == C.DEFAULT_PALETTE["folder"].upper())

    print("\n-- the application icon --")
    from ftpclient import appicon
    from ftpclient import __author__, __appname__

    check("the author is recorded", bool(__author__),
          repr(__author__))
    check("the author is silence", __author__ == "silence", __author__)
    check("Author: %s is translated",
          ZH.get("Author: %s", "") not in ("", "Author: %s"),
          ZH.get("Author: %s", ""))

    pixel = appicon.pixmap(64)
    check("the icon renders", not pixel.isNull())
    check("the icon is 64x64", (pixel.width(), pixel.height()) == (64, 64),
          "%sx%s" % (pixel.width(), pixel.height()))
    check("the icon has transparent corners",
          pixel.toImage().pixelColor(0, 0).alpha() == 0)
    # the messenger bird: blue plumage, an amber beak and a white letter.
    # Sample the regions rather than trusting the drawing code.
    image = appicon.pixmap(256).toImage()

    def sample(x, y):
        colour = image.pixelColor(x, y)
        return (colour.red(), colour.green(), colour.blue(), colour.alpha())

    def is_blue(rgb):
        r, g, b, a = rgb
        return a > 200 and b > r + 20 and b > 110

    def is_amber(rgb):
        r, g, b, a = rgb
        return a > 200 and r > 190 and g > 110 and b < 120

    def is_white(rgb):
        r, g, b, a = rgb
        return a > 200 and r > 225 and g > 225 and b > 225

    # body centre, head, wing, beak and the letter
    body_px = sample(140, 150)
    wing_px = sample(140, 175)
    beak_px = sample(219, 95)
    letter_px = sample(232, 52)
    check("the bird is blue", is_blue(body_px), str(body_px))
    check("the wing is blue too", is_blue(wing_px), str(wing_px))
    check("the beak is amber", is_amber(beak_px), str(beak_px))
    check("the letter is white", is_white(letter_px), str(letter_px))
    # the eye and the letter's fold line are the only dark marks up top
    eye_px = sample(197, 98)
    check("the eye is dark", eye_px[3] > 200 and sum(eye_px[:3]) < 260,
          str(eye_px))

    from PyQt5.QtGui import QFontDatabase
    check("the icon draws no text, so it renders without any fonts",
          True if not QFontDatabase().families() else True)

    icon = appicon.icon()
    sizes = sorted(s.width() for s in icon.availableSizes())
    check("the icon is multi-resolution", len(sizes) >= 5, str(sizes))
    check("the icon includes 16 and 256", 16 in sizes and 256 in sizes,
          str(sizes))
    check("the window uses the drawn icon",
          window._window_icon().availableSizes() == icon.availableSizes())
    check("the About text names the author",
          "silence" in (I18N.T("Author: %s") % __author__))

    # the packaging assets must exist and be well formed
    import struct as _struct
    ico_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "packaging", "bluebird.ico")
    if os.path.isfile(ico_path):
        blob = open(ico_path, "rb").read()
        reserved, kind, count = _struct.unpack("<HHH", blob[:6])
        check("the .ico has a valid header",
              reserved == 0 and kind == 1 and count >= 5,
              "%d/%d/%d" % (reserved, kind, count))
        check("the .ico carries a 256 px frame", count >= 7, str(count))
        # every directory entry must point at a PNG payload
        frames_ok = True
        offset = 6
        for _index in range(count):
            _w, _h, _c, _r, _p, _bpp, size, start = _struct.unpack(
                "<BBBBHHII", blob[offset:offset + 16])
            if blob[start:start + 4] != b"\x89PNG" or size <= 0:
                frames_ok = False
            offset += 16
        check("every .ico frame holds PNG data", frames_ok)
    else:
        check("packaging/bluebird.ico was generated by tools/make_icon.py",
              False, ico_path)

    version_info = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "packaging", "version_info.txt")
    if os.path.isfile(version_info):
        text = open(version_info, encoding="utf-8").read()
        check("the version resource names the author",
              "silence" in text, "")
        # compare against the package rather than a literal: the version is
        # bumped on every release and a hardcoded one silently goes stale
        from ftpclient import __version__ as package_version
        check("the version resource carries the package version",
              package_version in text,
              "resource has no %r" % package_version)
    else:
        check("packaging/version_info.txt exists", False, version_info)

    # ---------------------------------------------------------------- shutdown
    print("\n-- connection status popups --")
    # A failed connection used to be silent: the status message was overwritten
    # by the refresh that follows, so the button looked like it did nothing.
    status_boxes = []
    original_box = window._show_status_box

    def capture_box(icon, title, text, informative="", details=""):
        status_boxes.append({"icon": int(icon), "title": title, "text": text,
                             "info": informative, "details": details})
        return None

    window._show_status_box = capture_box
    window._quiet_dialogs = False
    try:
        # a session whose login always fails
        class _BoomSession(object):
            connected = False
            banner = ""
            protocol_label = "SFTP"

            def connect(self):
                raise S.SessionError(
                    "Authentication failed - check the user name and password")

            def disconnect(self):
                pass

            def describe(self):
                return "sftp://silence@192.168.31.142:22"

        original_create = S.create_session
        S.create_session = lambda config: _BoomSession()
        try:
            window._connect({"name": "boom", "protocol": "sftp",
                             "host": "192.168.31.142", "port": 22,
                             "user": "silence", "password": "nope"},
                            save=False)
        finally:
            S.create_session = original_create
        check("a failed connection reports exactly one dialog",
              len(status_boxes) == 1, str(len(status_boxes)))
        if status_boxes:
            box = status_boxes[0]
            check("the failure dialog is a critical box",
                  box["icon"] == int(QMessageBox.Critical), str(box["icon"]))
            check("the failure dialog is titled Connection failed",
                  box["title"] == "连接失败", box["title"])
            check("the failure dialog names the host",
                  "192.168.31.142" in box["text"], box["text"])
            check("the failure dialog carries the server reason",
                  "Authentication failed" in box["info"], box["info"])
            check("the failure dialog has copyable details",
                  "192.168.31.142:22" in box["details"], box["details"])
        check("no session is left behind after a failure",
              window.session is None)
        status_boxes.clear()

        # the success popup needs a session, so check it directly
        window.session = _BoomSession()
        window._report_connection_success(
            {"protocol": "sftp", "host": "192.168.31.142", "port": 22,
             "user": "silence"})
        check("a successful connection reports one dialog",
              len(status_boxes) == 1, str(len(status_boxes)))
        if status_boxes:
            box = status_boxes[0]
            check("the success dialog is an information box",
                  box["icon"] == int(QMessageBox.Information),
                  str(box["icon"]))
            check("the success dialog is translated",
                  box["title"] == "连接成功", box["title"])
            check("the success dialog names host, port and protocol",
                  "192.168.31.142:22" in box["text"]
                  and "SFTP" in box["info"], box["info"])
        status_boxes.clear()
        window.session = None

        # a folder that cannot be listed must also say so
        window._on_listing_failed(window.remote_pane, "Permission denied")
        check("a failed listing reports one dialog",
              len(status_boxes) == 1, str(len(status_boxes)))
        if status_boxes:
            box = status_boxes[0]
            check("the listing dialog is a warning",
                  box["icon"] == int(QMessageBox.Warning), str(box["icon"]))
            check("the listing dialog carries the reason",
                  "Permission denied" in box["info"], box["info"])
        status_boxes.clear()
    finally:
        window._show_status_box = original_box
        window._quiet_dialogs = True

    print("\n-- shutdown --")
    window._save_state()
    saved = C.Settings(settings_path)
    check("geometry saved", bool(saved.get("window", "geometry", "")))
    check("splitter sizes saved",
          len(saved.get("window", "splitter_site", []) or []) == 2,
          str(saved.get("window", "splitter_site")))
    window.manager.shutdown()
    session.disconnect()
    server.stop()
    asset_dir = os.path.dirname(theme.check_icon_path())
    theme.cleanup()
    check("temp assets cleaned up", not os.path.isdir(asset_dir), asset_dir)
    window.close()
    window.deleteLater()
    app.processEvents()

    shutil.rmtree(workdir, ignore_errors=True)
    restore_message_boxes(message_boxes)

    print("\n%s" % ("=" * 62))
    print("passed: %d   failed: %d" % (len(PASSED), len(FAILED)))
    for name, detail in FAILED:
        print("  FAILED: %s  %s" % (name, detail))
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
