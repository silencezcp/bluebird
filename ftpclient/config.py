"""Persisted settings and colour palette definitions.

Two files are used:

* ``~/.bluebird/settings.json`` - application preferences and the colour
  palette (nested data, JSON is the right fit).
* ``~/.bluebird/config.ini`` - **saved server connections**, one INI section
  per connection, so they are easy to hand-edit and to share.

Python 3.8 compatible: no walrus operators, no ``dict | dict``.
"""

from __future__ import annotations

import configparser
import copy
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

APP_NAME = "BlueBird"
APP_SLUG = "bluebird"

# --------------------------------------------------------------------------
# Colour palette
# --------------------------------------------------------------------------
# The palette is a flat ``key -> "#rrggbb"`` mapping.  Keys are referenced
# from the Qt stylesheet as ``{{key}}`` placeholders, from the icon renderer
# as ``{{key}}`` in SVG templates, and from the models for row tinting.

DEFAULT_PALETTE: Dict[str, str] = {
    # --- surfaces -------------------------------------------------------
    "window": "#F7F3EA",        # window background (milk white / cream)
    "surface": "#FFFCF5",       # panels, table background
    "surface_alt": "#FBF7EE",   # alternating rows
    "surface_sunken": "#F1EBDE",  # inputs, sunken areas
    "surface_hover": "#F3EBD9",   # hovered rows / buttons
    "sidebar": "#F2ECDF",       # toolbar + status bars
    "header": "#EFE8D8",        # table headers
    # --- lines ----------------------------------------------------------
    "border": "#E2D8C4",
    "border_strong": "#D2C4A9",
    "gridline": "#DCD2BC",
    # --- text -----------------------------------------------------------
    "text": "#3B352C",
    "text_muted": "#8A8072",
    "text_inverse": "#FFFFFF",
    # --- accent ---------------------------------------------------------
    "accent": "#3E7CB1",
    "accent_hover": "#4E8CC1",
    "accent_pressed": "#2F648F",
    "accent_soft": "#E6EFF7",
    "focus": "#7FA8CB",
    # --- selection ------------------------------------------------------
    "selection_bg": "#DCE9F5",
    "selection_text": "#22384D",
    # --- file list item colours (customisable by the user) --------------
    "folder": "#2E6FA8",        # folders: blue by default
    "folder_dark": "#23578A",   # folder tab / darker half
    "file": "#3B352C",          # files: default text colour
    "link": "#2F8F83",          # symlinks
    # --- semantic -------------------------------------------------------
    "success": "#2E8B57",
    "warning": "#C08A2E",
    "danger": "#B4483C",
    "info": "#3E7CB1",
    # --- progress / special rows ---------------------------------------
    "progress": "#2E8B57",
    "progress_text": "#FFFFFF",
    "error_row": "#F7E3DF",
    "ok_row": "#E4F1E4",
    "queued_row": "#F3EBD9",
    "active_row": "#E1EEF8",
}

#: Human readable labels + grouping for the settings dialog.
COLOR_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Interface", [
        ("window", "Window background"),
        ("surface", "Panel background"),
        ("surface_alt", "Alternating rows"),
        ("surface_sunken", "Input background"),
        ("surface_hover", "Hover background"),
        ("sidebar", "Toolbar / status bar"),
        ("header", "Table header"),
    ]),
    ("Lines", [
        ("border", "Border"),
        ("border_strong", "Strong border"),
        ("gridline", "Grid line"),
    ]),
    ("Text", [
        ("text", "Primary text"),
        ("text_muted", "Muted text"),
        ("text_inverse", "Inverted text"),
    ]),
    ("Accent", [
        ("accent", "Accent"),
        ("accent_hover", "Accent (hover)"),
        ("accent_pressed", "Accent (pressed)"),
        ("accent_soft", "Accent (soft)"),
        ("focus", "Focus ring"),
        ("selection_bg", "Selection background"),
        ("selection_text", "Selection text"),
    ]),
    ("File list items", [
        ("folder", "Folder"),
        ("folder_dark", "Folder (shaded)"),
        ("file", "File"),
        ("link", "Symbolic link"),
    ]),
    ("Status", [
        ("success", "Success / finished"),
        ("warning", "Warning"),
        ("danger", "Error"),
        ("info", "Information"),
    ]),
    ("Queued transfers", [
        ("progress", "Progress bar"),
        ("progress_text", "Progress text"),
        ("queued_row", "Queued row"),
        ("active_row", "Active row"),
        ("ok_row", "Completed row"),
        ("error_row", "Failed row"),
    ]),
]

#: Ready-made palettes.  ``None`` means "use DEFAULT_PALETTE".
PRESETS: Dict[str, Optional[Dict[str, str]]] = {
    "BlueBird (cream)": None,
    "Cloud": {
        "window": "#F4F6F9", "surface": "#FFFFFF", "surface_alt": "#F8FAFC",
        "surface_sunken": "#EDF1F6", "surface_hover": "#EEF3F9",
        "sidebar": "#EEF2F7", "header": "#E9EEF5",
        "border": "#DCE3EC", "border_strong": "#C6D0DD", "gridline": "#D3DDE9",
        "text": "#25303C", "text_muted": "#7C8899",
        "accent": "#2F6FB5", "accent_hover": "#3D80C8", "accent_pressed": "#255A94",
        "accent_soft": "#E4EEF8", "focus": "#7FA8CB",
        "selection_bg": "#D8E8F7", "selection_text": "#1E3146",
        "folder": "#2F6FB5", "folder_dark": "#255A94", "file": "#25303C",
        "link": "#2A8C80",
    },
    "Matcha": {
        "window": "#F3F6EE", "surface": "#FCFDF8", "surface_alt": "#F6F9F0",
        "surface_sunken": "#ECF1E3", "surface_hover": "#EDF3E2",
        "sidebar": "#EDF2E5", "header": "#E7EEDC",
        "border": "#DAE2CD", "border_strong": "#C3CDB2", "gridline": "#D3DDC3",
        "text": "#31382A", "text_muted": "#7E8873",
        "accent": "#5C8A3C", "accent_hover": "#6C9C49", "accent_pressed": "#4A7130",
        "accent_soft": "#E8F0DF", "focus": "#9DBC7F",
        "selection_bg": "#DDEAD0", "selection_text": "#2A3A1E",
        "folder": "#3E7CB1", "folder_dark": "#2F648F", "file": "#31382A",
        "link": "#2F8F83",
    },
    "Linen (dark)": {
        "window": "#22201C", "surface": "#2A2724", "surface_alt": "#2F2B27",
        "surface_sunken": "#1E1C19", "surface_hover": "#3A352F",
        "sidebar": "#262320", "header": "#332F2A",
        "border": "#3D3831", "border_strong": "#4E483F", "gridline": "#443E37",
        "text": "#EDE6D8", "text_muted": "#A79C89", "text_inverse": "#22201C",
        "accent": "#7FA8CB", "accent_hover": "#93B8D8", "accent_pressed": "#6A92B4",
        "accent_soft": "#33404B", "focus": "#7FA8CB",
        "selection_bg": "#33475A", "selection_text": "#F0F4F8",
        "folder": "#7FB2E0", "folder_dark": "#5E93C4", "file": "#EDE6D8",
        "link": "#79C3B6",
    },
}


def blend(color_a: str, color_b: str, ratio: float) -> str:
    """Blend two ``#rrggbb`` colours; ``ratio`` 0.0 -> a, 1.0 -> b."""
    try:
        ra, ga, ba = _to_rgb(color_a)
        rb, gb, bb = _to_rgb(color_b)
    except ValueError:
        return color_a
    ratio = max(0.0, min(1.0, ratio))
    return "#%02X%02X%02X" % (
        int(round(ra + (rb - ra) * ratio)),
        int(round(ga + (gb - ga) * ratio)),
        int(round(ba + (bb - ba) * ratio)),
    )


def _to_rgb(color: str) -> Tuple[int, int, int]:
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError("bad colour: %r" % (color,))
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def color_distance(color_a: str, color_b: str) -> float:
    """Perceptual-ish distance between two colours (0..441)."""
    ra, ga, ba = _to_rgb(color_a)
    rb, gb, bb = _to_rgb(color_b)
    # weighted euclidean ("redmean") - good enough for a UI warning
    rmean = (ra + rb) / 2.0
    dr, dg, db = ra - rb, ga - gb, ba - bb
    return ((2 + rmean / 256.0) * dr * dr + 4 * dg * dg
            + (2 + (255 - rmean) / 256.0) * db * db) ** 0.5


def is_readable_on(background: str, foreground: str) -> bool:
    return color_distance(background, foreground) > 60.0


# --------------------------------------------------------------------------
# Default settings tree
# --------------------------------------------------------------------------

DEFAULT_SETTINGS: Dict[str, Any] = {
    "appearance": {
        "palette": copy.deepcopy(DEFAULT_PALETTE),
        "language": "zh",           # "zh" | "en" - see ftpclient.i18n
        "row_height": 26,
        "font_family": "",          # "" -> use the platform UI font
        "font_size": 0,             # 0  -> platform default
        "show_hidden": True,
        "alternating_rows": True,
        "grid_lines": False,
        "icon_size": 18,
        # Name columns keep a fixed width by default (never stretched by the
        # pane). Turn auto-fit on to widen them to the longest name instead.
        "auto_fit_name_column": False,
        "column_widths": {"name": 260},
        # Permissions / Owner are handy on Unix servers. Permissions is on by
        # default because a remote listing is exactly where you need it; Owner
        # costs another ~92 px and stays off until asked for.
        "show_permissions": True,
        "show_owner": False,
    },
    "behavior": {
        "double_click_action": "open",   # open | transfer
        "confirm_delete": True,
        "confirm_overwrite": True,
        "local_start_dir": "",
        "remember_last_dirs": True,
        "last_local_dir": "",
        "last_remote_dir": "/",
        "log_lines": 2000,
    },
    "transfers": {
        "concurrency": 2,
        "retries": 2,
        "preserve_timestamps": False,
        #: pop up a result dialog when a transfer (batch) finishes
        "notify_finished": True,
        #: refresh the affected pane so the new files show up immediately
        "refresh_after_transfer": True,
        "ascii_extensions": ".txt .html .htm .php .js .css .json .xml .md .csv",
        "binary_extensions": ".zip .gz .tar .tgz .bz2 .7z .rar .exe .dll .so "
                             ".png .jpg .jpeg .gif .bmp .webp .ico .pdf .doc "
                             ".docx .xls .xlsx .ppt .pptx .mp3 .mp4 .avi .mkv "
                             ".iso .bin .dat .pyc .jar .woff .woff2 .ttf",
    },
    "sessions": {
        "timeout": 30,
        "keepalive": 30,
        "passive": True,
        "verify_host_key": False,
        "encoding": "utf-8",
    },
    "sites": [],
    "window": {
        "geometry": "",
        "splitter_main": [],
        "splitter_site": [],
        "active_tab": 0,
    },
    "recent": [],
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# --------------------------------------------------------------------------
# Connection store (config.ini)
# --------------------------------------------------------------------------

#: keys written to / read from each ``[name]`` section of config.ini
CONNECTION_FIELDS: List[str] = [
    "name", "protocol", "host", "port", "user", "password",
    "key_filename", "passive", "timeout", "keepalive", "verify_host_key",
    "encoding", "remote_dir", "local_dir",
]

_BOOL_FIELDS = ("passive", "verify_host_key")
_INT_FIELDS = ("port", "timeout", "keepalive")


def _ini_escape(value: Any) -> str:
    """configparser cannot handle newlines inside values."""
    return str(value if value is not None else "").replace("\r", " ").replace("\n", " ")


def connection_slug(name: str) -> str:
    """A unique, INI-friendly section name derived from a display name."""
    cleaned = re.sub(r"[^0-9A-Za-z_.@+-]+", "_", (name or "").strip())
    return cleaned or "connection"


def default_connection_name(site: Dict[str, Any]) -> str:
    """``user@host`` ??the same label the rest of the UI uses."""
    user = str(site.get("user") or "anonymous")
    host = str(site.get("host") or "server")
    port = site.get("port")
    protocol = str(site.get("protocol") or "ftp").lower()
    if port and int(port) not in (21, 22):
        return "%s@%s:%s" % (user, host, port)
    return "%s@%s" % (user, host)


class ConnectionStore(object):
    """FTP / SFTP connection definitions kept in a local ``config.ini``.

    Passwords are stored in clear text inside this file (INI has no key
    management), which is deliberate: it makes the file portable between
    machines and readable by other tools. Keep it private.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self.path = path or default_config_path()
        self._parser = configparser.ConfigParser(
            interpolation=None, delimiters=("=",))

    # -- IO -------------------------------------------------------------
    def load(self) -> "ConnectionStore":
        with self._lock:
            parser = configparser.ConfigParser(interpolation=None,
                                               delimiters=("=",))
            try:
                # keep the key spelling exactly as written (case sensitive)
                parser.optionxform = str  # type: ignore[assignment]
                with open(self.path, "r", encoding="utf-8-sig") as handle:
                    parser.read_file(handle)
            except (IOError, OSError):
                pass
            except configparser.Error:
                # a corrupt file must never stop the client from starting
                parser = configparser.ConfigParser(interpolation=None,
                                                   delimiters=("=",))
                parser.optionxform = str  # type: ignore[assignment]
            self._parser = parser
            return self

    def save(self) -> bool:
        with self._lock:
            parser = self._parser
            parser.optionxform = str  # type: ignore[assignment]
            if parser.has_section("connections"):
                parser.set("connections", "order", ",".join(sorted(self.names(), key=str.lower)))
            directory = os.path.dirname(self.path)
            try:
                if directory and not os.path.isdir(directory):
                    os.makedirs(directory)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    handle.write("# BlueBird - saved server connections\n")
                    handle.write("# One section per connection. Passwords are "
                                 "stored in clear text: keep this file private.\n\n")
                    parser.write(handle)
                os.replace(tmp, self.path)
                return True
            except (IOError, OSError):
                return False

    # -- queries --------------------------------------------------------
    def names(self) -> List[str]:
        with self._lock:
            if self._parser.has_section("connections"):
                return [n for n, _ in self._parser.items("connections")
                        if n and n != "order"]
            return [s for s in self._parser.sections() if s != "connections"]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        """Look a connection up by section **or** by its display label."""
        entry = self._get_section(name)
        if entry is not None:
            return entry
        wanted = (name or "").lower()
        if not wanted:
            return None
        for candidate in self.names():
            entry = self._get_section(candidate)
            if entry is not None and str(entry.get("name", "")).lower() == wanted:
                return entry
        return None

    def _get_section(self, section: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not section or not self._parser.has_section(section):
                return None
            raw = dict(self._parser.items(section))
        return self._decode(section, raw)

    def all(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for name in self.names():
            entry = self.get(name)
            if entry is not None:
                result.append(entry)
        result.sort(key=lambda item: str(item.get("name", "")).lower())
        return result

    def is_empty(self) -> bool:
        return not self.names()

    def find_by_host(self, host: str, user: str = "",
                     protocol: str = "") -> Optional[Dict[str, Any]]:
        for entry in self.all():
            if str(entry.get("host", "")).lower() != (host or "").lower():
                continue
            if protocol and entry.get("protocol") != protocol:
                continue
            if user and str(entry.get("user", "")) != user:
                continue
            return entry
        return None

    # -- mutation -------------------------------------------------------
    def unique_name(self, wanted: str) -> str:
        base = (wanted or "").strip() or "connection"
        with self._lock:
            existing = set(self.names())
        if base not in existing:
            return base
        index = 2
        while "%s (%d)" % (base, index) in existing:
            index += 1
        return "%s (%d)" % (base, index)

    def upsert(self, site: Dict[str, Any], save: bool = True) -> str:
        """Create or update a connection. Returns the stored section name.

        Matched first by the label the user sees, then by
        protocol + host + user. An empty password never wipes a password that
        is already stored, because the connection bar cannot show it back.
        """
        with self._lock:
            target = None
            wanted = str(site.get("name") or "").strip()
            for candidate in self.names():
                if wanted and candidate.lower() == wanted.lower():
                    target = candidate
                    break
                entry = self.get(candidate) or {}
                if wanted and str(entry.get("name", "")).lower() == wanted.lower():
                    target = candidate
                    break
            if target is None and wanted:
                target = wanted if self.get(wanted) is not None else None
            if target is None:
                previous = self.find_by_host(
                    str(site.get("host", "")), str(site.get("user", "")),
                    str(site.get("protocol", "")))
                if previous is not None:
                    target = str(previous.get("section") or previous.get("name"))
            current = self.get(target) if target else None
            if target is None:
                target = self.unique_name(wanted or default_connection_name(site))

            values = {}
            for field in CONNECTION_FIELDS:
                if field in site and site[field] is not None:
                    values[field] = site[field]
            for field in _BOOL_FIELDS:
                if field in values:
                    values[field] = "1" if values[field] else "0"
            if current:
                for field in ("name", "password", "key_filename", "remote_dir",
                              "local_dir", "protocol", "port"):
                    if not values.get(field) and current.get(field) is not None:
                        values[field] = current[field]
            if not values.get("name"):
                values["name"] = default_connection_name(values)
            self._write_section(target, values)
        if save:
            self.save()
        return target

    def remember_dirs(self, name: str, local_dir: str = "",
                      remote_dir: str = "") -> None:
        entry = self.get(name)
        if entry is None:
            return
        changed = False
        if local_dir and entry.get("local_dir") != local_dir:
            entry["local_dir"] = local_dir
            changed = True
        if remote_dir and entry.get("remote_dir") != remote_dir:
            entry["remote_dir"] = remote_dir
            changed = True
        if changed:
            self.upsert(entry)

    def delete(self, name: str) -> bool:
        with self._lock:
            entry = self.get(name)
            if entry is None:
                return False
            self._parser.remove_section(str(entry.get("section") or name))
            if self._parser.has_section("connections"):
                self._parser.remove_option("connections",
                                           str(entry.get("section") or name))
        return self.save()

    def rename(self, old: str, new: str) -> bool:
        entry = self.get(old)
        if entry is None or not new.strip() or new == old:
            return False
        section = str(entry.get("section") or old)
        entry["name"] = new.strip()
        with self._lock:
            self._parser.remove_section(section)
            if self._parser.has_section("connections"):
                self._parser.remove_option("connections", section)
        self.upsert(entry, save=False)
        return self.save()

    def clear(self) -> bool:
        with self._lock:
            self._parser = configparser.ConfigParser(interpolation=None,
                                                     delimiters=("=",))
            self._parser.optionxform = str  # type: ignore[assignment]
        return self.save()

    # -- internals ------------------------------------------------------
    def _write_section(self, section: str, values: Dict[str, Any]) -> None:
        with self._lock:
            parser = self._parser
            parser.optionxform = str  # type: ignore[assignment]
            if parser.has_section("connections"):
                parser.set("connections", "order", ",".join(sorted(self.names(), key=str.lower)))
            if not parser.has_section(section):
                parser.add_section(section)
            for key in CONNECTION_FIELDS:
                if key not in values or values[key] is None:
                    continue
                parser.set(section, key, _ini_escape(values[key]))
            # a human readable label so the file explains itself
            if not parser.has_section("connections"):
                parser.add_section("connections")
            parser.set("connections", section,
                       _ini_escape(values.get("name") or section))

    @staticmethod
    def _decode(section: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"name": raw.get("name") or section,
                                 "section": section}
        for key, value in raw.items():
            entry[key] = value
        for key in _BOOL_FIELDS:
            if key in entry:
                entry[key] = str(entry[key]).strip().lower() in (
                    "1", "true", "yes", "on")
        for key in _INT_FIELDS:
            if key in entry:
                try:
                    entry[key] = int(float(str(entry[key]).strip()))
                except (TypeError, ValueError):
                    entry.pop(key, None)
        entry.setdefault("protocol", "ftp")
        entry.setdefault("port", 22 if entry.get("protocol") == "sftp" else 21)
        return entry


class Settings(object):
    """Thread-safe, auto-saving settings store.

    Server connections live in a separate ``config.ini`` and are reached
    through :attr:`store` / :attr:`connections`.
    """

    def __init__(self, path: Optional[str] = None,
                 config_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        # an install from before the rename keeps its connections by copying
        # them across the first time this new build starts
        if path is None and config_path is None:
            self.migrated = migrate_legacy_config()
        else:
            self.migrated = []
        self.path = path or default_settings_path()
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self.store = ConnectionStore(config_path or default_config_path())
        self.store.load()
        self.load()
        self._migrate_sites()

    @property
    def connections(self) -> ConnectionStore:
        """The saved FTP / SFTP connections (``config.ini``)."""
        return self.store

    def _migrate_sites(self) -> None:
        """Import connections saved by older versions (inside settings.json)."""
        if not self.store.is_empty():
            return
        legacy = self.data.get("sites")
        if not isinstance(legacy, list) or not legacy:
            return
        imported = 0
        for site in legacy:
            if not isinstance(site, dict) or not site.get("host"):
                continue
            self.store.upsert(site, save=False)
            imported += 1
        if imported:
            self.store.save()

    # -- persistence ----------------------------------------------------
    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raw = {}
        except (IOError, OSError, ValueError):
            raw = {}
        with self._lock:
            self.data = _deep_merge(DEFAULT_SETTINGS, raw)
            # a palette saved by an older version may lack new keys
            palette = self.data.get("appearance", {}).get("palette", {})
            merged = copy.deepcopy(DEFAULT_PALETTE)
            for key, value in palette.items():
                if isinstance(value, str):
                    merged[key] = value
            self.data["appearance"]["palette"] = merged

    def save(self) -> None:
        with self._lock:
            payload = copy.deepcopy(self.data)
        directory = os.path.dirname(self.path)
        try:
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except (IOError, OSError):
            # never let a settings write break the session
            pass

    # -- access ---------------------------------------------------------
    def get(self, section: str, key: str = "", default: Any = None) -> Any:
        with self._lock:
            node = self.data.get(section)
            if key == "":
                return copy.deepcopy(node if node is not None else default)
            if isinstance(node, dict) and key in node:
                return copy.deepcopy(node[key])
            return default

    def set(self, section: str, key: str, value: Any, autosave: bool = True) -> None:
        with self._lock:
            node = self.data.setdefault(section, {})
            if not isinstance(node, dict):
                node = {}
                self.data[section] = node
            node[key] = copy.deepcopy(value)
        if autosave:
            self.save()

    def update(self, section: str, values: Dict[str, Any], autosave: bool = True) -> None:
        with self._lock:
            node = self.data.setdefault(section, {})
            if not isinstance(node, dict):
                node = {}
                self.data[section] = node
            for key, value in values.items():
                node[key] = copy.deepcopy(value)
        if autosave:
            self.save()

    # -- helpers --------------------------------------------------------
    @property
    def palette(self) -> Dict[str, str]:
        with self._lock:
            return copy.deepcopy(self.data["appearance"]["palette"])

    def set_palette(self, palette: Dict[str, str], autosave: bool = True) -> None:
        merged = copy.deepcopy(DEFAULT_PALETTE)
        for key, value in (palette or {}).items():
            if isinstance(value, str) and value:
                merged[key] = value
        self.set("appearance", "palette", merged, autosave=autosave)

    def apply_preset(self, name: str, autosave: bool = True) -> Dict[str, str]:
        preset = PRESETS.get(name)
        palette = copy.deepcopy(DEFAULT_PALETTE)
        if preset:
            palette.update(preset)
        self.set_palette(palette, autosave=autosave)
        return palette

    # -- sites (now backed by config.ini) -------------------------------
    def sites(self) -> List[Dict[str, Any]]:
        """Every saved connection, sorted by label."""
        return self.store.all()

    def save_site(self, site: Dict[str, Any]) -> str:
        """Store a connection; an existing host/user pair is updated."""
        return self.store.upsert(site)

    def delete_site(self, name: str) -> None:
        self.store.delete(name)

    def push_recent(self, entry: str, limit: int = 12) -> None:
        with self._lock:
            recent = [r for r in self.data.get("recent", []) if r != entry]
            recent.insert(0, entry)
            self.data["recent"] = recent[:limit]
        self.save()

    def recent(self) -> List[str]:
        value = self.get("recent", default=[])
        return value if isinstance(value, list) else []


#: Folders this application used before it was renamed, newest first.  Existing
#: installs are migrated from here so saved connections are not orphaned; the
#: list grows by one every time the product is renamed.
LEGACY_APP_SLUGS = ("smartftp", "nacreftp")
LEGACY_ENV_SETTINGS = ("SMART_FTP_SETTINGS", "NACRE_FTP_SETTINGS")
LEGACY_ENV_CONFIG = ("SMART_FTP_CONFIG", "NACRE_FTP_CONFIG")


def _env(*names: str) -> str:
    """First environment variable that is set, newest name first."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def legacy_settings_dirs() -> List[str]:
    """Folders the earlier names used, newest first (they may not exist)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return [os.path.join(base, "." + slug) for slug in LEGACY_APP_SLUGS]


def legacy_settings_dir() -> str:
    """The most recent pre-rename folder, for messages and tests."""
    return legacy_settings_dirs()[0]


def migrate_legacy_config() -> List[str]:
    """Copy settings/connections over from an earlier name, once.

    Every old folder is tried in turn, newest first, and only files that do not
    exist yet are copied.  The originals are left in place: this only ever
    reads them, so a user who rolls back to a previous build still finds
    everything.
    """
    import shutil

    moved: List[str] = []
    new_dir = os.path.dirname(os.path.abspath(default_settings_path()))
    try:
        if not os.path.isdir(new_dir):
            os.makedirs(new_dir)
    except OSError:
        return moved

    for old_dir in legacy_settings_dirs():
        if not os.path.isdir(old_dir):
            continue
        try:
            if os.path.abspath(old_dir) == os.path.abspath(new_dir):
                continue
        except OSError:
            continue
        for name in ("settings.json", "config.ini"):
            source = os.path.join(old_dir, name)
            target = os.path.join(new_dir, name)
            if not os.path.isfile(source) or os.path.exists(target):
                continue
            try:
                shutil.copy2(source, target)
                moved.append(target)
            except OSError:
                continue
    return moved


def default_settings_path() -> str:
    override = _env("BLUEBIRD_SETTINGS", *LEGACY_ENV_SETTINGS)
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "." + APP_SLUG, "settings.json")


def default_config_path() -> str:
    """Where the saved connections live (``config.ini``)."""
    override = _env("BLUEBIRD_CONFIG", *LEGACY_ENV_CONFIG)
    if override:
        return override
    return os.path.join(os.path.dirname(default_settings_path()), "config.ini")
