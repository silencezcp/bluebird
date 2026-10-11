"""Unified FTP / FTPS / SFTP session layer.

This module deliberately imports **no Qt**: it can be unit-tested and driven
from plain Python.  The UI talks to :class:`BaseSession` only.

Protocol notes
-------------
* FTP/FTPS use their own data connection.  To keep the UI responsive and to
  support pause / cancel we drive the data socket ourselves instead of using
  ``storbinary``/``retrbinary``.
* SFTP runs over a :class:`paramiko.SSHClient`; every session carries a
  re-entrant lock so several worker threads can share one connection safely.
"""

from __future__ import annotations

import errno
import ftplib
import io
import os
import posixpath
import re
import select
import socket
import stat as stat_module
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import paramiko

from .core import Entry, parse_size

ProgressFn = Optional[Callable[[int, Optional[int]], None]]

#: data socket read chunk
CHUNK = 64 * 1024

#: ``ftplib.all_errors`` is already a tuple, so it must be flattened before it
#: can be extended - ``except FTP_ERRORS`` would raise
#: ``TypeError: catching classes that do not inherit from BaseException``.
FTP_ERRORS = tuple(ftplib.all_errors) + (OSError, EOFError)

#: The DOS style directory line that Microsoft's FTP service returns:
#: ``10-11-26  01:17PM              1661239 name`` or ``... <DIR>  name``.
#: A pattern is used rather than fixed columns because the padding before the
#: name changes with the width of the size field.
_DOS_LIST_RE = re.compile(
    r"^(\d{2})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})\s*([AaPp][Mm])"
    r"\s+(<DIR>|\d+)\s+(.+?)\s*$",
    re.IGNORECASE)


#: RFC 3659 "perm" fact letters, in the order the RFC documents them.  They
#: describe what the *current user* may do, not the file's Unix mode, so they
#: are shown as-is instead of being dressed up as "-rw-r--r--".
MLSD_PERM_LETTERS = (
    ("e", "enter"), ("l", "list"), ("r", "read"), ("a", "append"),
    ("w", "write"), ("f", "rename"), ("d", "delete"), ("c", "create"),
    ("m", "mkdir"), ("p", "delete inside"), ("M", "set last-modified time"),
    ("T", "set last-modified time"),
)


def _permissions_from_mlsd_perm(text: str, is_dir: bool = False,
                                is_link: bool = False) -> str:
    """Render the MLSD ``perm`` fact as a readable permission string.

    Many servers (pyftpdlib, pure-ftpd, IIS, ...) never send ``unix.mode``, so
    without this the Permissions column stays empty.  RFC 3659 defines ``perm``
    as the operations the current user may perform, which is the question the
    column answers in practice.

    Letters are emitted in the RFC order so the display is stable and
    comparable between servers.
    """
    tokens = set((text or "").strip())
    if not tokens:
        return ""
    kind = "d" if is_dir else ("l" if is_link else "-")
    letters = "".join(letter for letter, _meaning in MLSD_PERM_LETTERS
                      if letter in tokens)
    return kind + letters if letters else ""


def describe_mlsd_perm(text: str) -> str:
    """Human readable expansion of an MLSD ``perm`` value, for tooltips."""
    tokens = set((text or "").strip())
    seen: List[str] = []
    for letter, meaning in MLSD_PERM_LETTERS:
        # M and T are two spellings of the same right
        if letter in tokens and meaning not in seen:
            seen.append(meaning)
    return ", ".join(seen)


def _mode_from_octal(text: str) -> Optional[int]:
    """Turn an MLSD ``unix.mode`` value such as ``0644`` into an int mode.

    Returns ``None`` when the server did not send a usable value, so callers
    can fall back to the ``ls -l`` permissions instead of showing a bare
    number.
    """
    value = (text or "").strip()
    if not value:
        return None
    try:
        # some servers send "644", others "0644" or "0o644"
        cleaned = value.lower().replace("0o", "")
        mode = int(cleaned, 8)
    except (TypeError, ValueError):
        return None
    if mode <= 0:
        return None
    return mode


class SessionError(Exception):
    """Any failure while talking to a server."""

    def __init__(self, message: str, code: str = "") -> None:
        super(SessionError, self).__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class Cancelled(Exception):
    """Raised inside a transfer when the user cancels it."""


class TransferControl(object):
    """Cooperative cancel/pause token shared with the transfer queue."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        self._event.set()

    def pause(self) -> None:
        self._event.set()

    def resume(self) -> None:
        self._event.clear()

    @property
    def paused(self) -> bool:
        return self._event.is_set() and not self._cancelled.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def wait_if_paused(self, timeout: float = 0.1) -> bool:
        """Block while paused.  Returns False when the transfer was cancelled."""
        while self._event.is_set():
            if self._cancelled.is_set():
                return False
            self._event.wait(timeout)
            if self._event.is_set() and not self._cancelled.is_set():
                # still paused: keep waiting
                continue
        return not self._cancelled.is_set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise Cancelled("cancelled")


# ---------------------------------------------------------------------------
# Local filesystem
# ---------------------------------------------------------------------------

def local_listdir(path: str, show_hidden: bool = True) -> List[Entry]:
    """List a local directory as :class:`Entry` objects."""
    entries: List[Entry] = []
    try:
        iterator = os.scandir(path)
    except OSError as exc:
        raise SessionError("Cannot open %s: %s" % (path, exc.strerror or exc))
    with iterator:
        for item in iterator:
            name = item.name
            if not show_hidden and name.startswith("."):
                continue
            try:
                is_link = item.is_symlink()
                is_dir = item.is_dir(follow_symlinks=True)
                info = item.stat(follow_symlinks=True)
                size = info.st_size
                mtime = info.st_mtime
                mode = info.st_mode
            except OSError:
                is_link = True
                is_dir = False
                size = 0
                mtime = 0.0
                mode = 0
            entries.append(Entry(
                name=name, size=size, mtime=mtime, is_dir=is_dir,
                is_link=is_link, mode=mode,
                permissions=stat_module.filemode(mode) if mode else "",
            ))
    return entries


def local_roots() -> List[Tuple[str, str]]:
    """Return ``(label, path)`` for the drives that exist on this machine.

    Network and removable drives are included, which is what makes it possible
    to switch the local pane to another volume.
    """
    roots: List[Tuple[str, str]] = []
    if os.name == "nt":
        for letter, kind in _windows_drives():
            root = "%s:\\" % letter
            label = "%s:\\" % letter
            if kind:
                label = "%s:\\   (%s)" % (letter, kind)
            roots.append((label, root))
        if not roots:
            # fall back to probing every letter
            import string
            for letter in string.ascii_uppercase:
                root = "%s:\\" % letter
                try:
                    if os.path.exists(root):
                        roots.append((root, root))
                except OSError:
                    continue
    else:
        roots.append(("/", "/"))
        home = os.path.expanduser("~")
        if home:
            roots.append((home, home))
        for extra in ("/mnt", "/media", "/Volumes"):
            if os.path.isdir(extra):
                try:
                    for name in sorted(os.listdir(extra)):
                        full = os.path.join(extra, name)
                        if os.path.isdir(full):
                            roots.append((full, full))
                except OSError:
                    pass
    return roots


#: Win32 drive type -> human label
_DRIVE_TYPES = {0: "unknown", 1: "no root", 2: "removable", 3: "local disk",
                4: "network", 5: "CD/DVD", 6: "RAM disk"}


def _windows_drives() -> List[Tuple[str, str]]:
    """(letter, type label) for each drive, using Win32 when available."""
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        kinds = []
        import string
        for index, letter in enumerate(string.ascii_uppercase):
            if not (bitmask >> index) & 1:
                continue
            kind = ""
            try:
                root = "%s:\\" % letter
                value = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
                kind = _DRIVE_TYPES.get(int(value), "")
            except Exception:
                kind = ""
            kinds.append((letter, kind))
        return kinds
    except Exception:
        return []


def local_home() -> str:
    home = os.path.expanduser("~")
    return home if os.path.isdir(home) else os.getcwd()


def local_desktop() -> str:
    """The user's Desktop folder.

    On Windows the Desktop can be redirected (OneDrive, a corporate profile),
    so the real location is looked up in the registry first and only then
    falls back to ``%USERPROFILE%\\Desktop``.  If neither exists we return the
    home folder, because a "Home" button that goes nowhere is worse.
    """
    candidates: List[str] = []
    if os.name == "nt":
        candidates.extend(_windows_desktop_candidates())
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "Desktop"))
    candidates.append(os.path.join(home, "\u684c\u9762"))
    candidates.append(home)
    for candidate in candidates:
        try:
            if candidate and os.path.isdir(candidate):
                return os.path.abspath(candidate)
        except OSError:
            continue
    return local_home()


def _windows_desktop_candidates() -> List[str]:
    """Read the shell's Desktop path out of HKCU (no pywin32 required)."""
    found: List[str] = []
    try:
        import winreg
    except ImportError:
        return found
    key_path = (r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\Shell Folders")
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
            if value:
                expanded = os.path.expandvars(str(value))
                if expanded not in found:
                    found.append(expanded)
        except (OSError, ValueError):
            continue
    # the "User Shell Folders" hive keeps the %USERPROFILE%-based value
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\User Shell Folders") as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        if value:
            expanded = os.path.expandvars(str(value))
            if expanded not in found:
                found.append(expanded)
    except (OSError, ValueError):
        pass
    return found


def ensure_local_dir(path: str) -> None:
    if path and not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise SessionError("Cannot create %s: %s" % (path, exc))


def human_error(exc: BaseException) -> str:
    """Turn a low level exception into something a user can act on.

    The text is deliberately localised-agnostic: Windows reports network
    failures in the system language, so ``winerror`` codes are checked first
    and every known socket error code maps to a plain English sentence.
    """
    if isinstance(exc, SessionError):
        return exc.message
    if isinstance(exc, Cancelled):
        return "Cancelled"
    if isinstance(exc, ftplib.error_perm):
        return "Server refused the command (%s)" % str(exc)
    if isinstance(exc, ftplib.error_temp):
        return "Temporary server error: %s" % exc
    if isinstance(exc, ftplib.error_proto):
        return "Protocol error: %s" % exc
    if isinstance(exc, paramiko.AuthenticationException):
        return "Authentication failed - check the user name and password"
    if isinstance(exc, paramiko.SSHException):
        return "SSH error: %s" % exc

    code = _error_code(exc)
    if code is not None:
        return _socket_message(code)

    if isinstance(exc, FTP_ERRORS):
        text = str(exc)
        lowered = text.lower()
        if "getaddrinfo" in lowered or "name or service not known" in lowered \
                or "11001" in lowered:
            return "Host not found (%s)" % text
        if "timed out" in lowered or "timeout" in lowered or "10060" in lowered:
            return "Connection timed out"
        return text or exc.__class__.__name__
    return str(exc) or exc.__class__.__name__


_SOCKET_MESSAGES = {
    10013: "Permission denied by the firewall or the server",
    10048: "Address already in use",
    10049: "Address not available",
    10051: "Network unreachable",
    10054: "Connection reset by the server",
    10060: "Connection timed out",
    10061: "Connection refused - is the server running, and is the port right?",
    10064: "Host is down",
    10065: "No route to host",
    11001: "Host not found - check the server name",
    11002: "Temporary name resolution failure",
    11004: "Host not found - check the server name",
}


def _error_code(exc: BaseException) -> Optional[int]:
    if isinstance(exc, socket.timeout):
        return 10060
    if isinstance(exc, socket.gaierror):
        return 11001
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if isinstance(winerror, int):
            return winerror
        if isinstance(exc.errno, int):
            return exc.errno
    return None


def _socket_message(code: int) -> str:
    known = _SOCKET_MESSAGES.get(code)
    if known:
        return known
    if code in (errno.ECONNREFUSED,):
        return _SOCKET_MESSAGES[10061]
    if code in (errno.ETIMEDOUT,):
        return _SOCKET_MESSAGES[10060]
    if code in (errno.EHOSTUNREACH, errno.ENETUNREACH):
        return "Network unreachable"
    if code in (errno.ECONNRESET, errno.EPIPE):
        return "Connection reset by the server"
    return "Network error (code %d)" % code


# ---------------------------------------------------------------------------
# Text conversion for ASCII mode
# ---------------------------------------------------------------------------

import io as _io


def _to_crlf(data: bytes) -> bytes:
    """Unix line endings to Windows ones, without doubling existing CRLFs."""
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


class _TextStreams(object):
    """Streams for a file that has to cross in ASCII mode.

    FTP can ask the server for ASCII, but SFTP has no such notion, so the line
    endings are translated here instead.  Going through the io module rather
    than replacing bytes by hand keeps a CRLF that straddles two read() chunks
    intact.
    """

    def __init__(self, session: "BaseSession", path: str,
                 remote: Any = None) -> None:
        self.session = session
        self.path = path
        self.remote = remote

    def reader(self) -> Any:
        """What to read from when downloading: LF becomes CRLF.

        The server is assumed to use the Unix convention and this client to use
        the Windows one, which is the case the ASCII mode exists for.  FTP has
        its own ASCII type but servers vary, so the conversion is done here for
        both protocols.
        """
        if self.session.transfer_type != "ascii" or self.remote is None:
            return self.remote
        data = self.remote.read()
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        return _io.BytesIO(_to_crlf(data))

    def writer(self) -> Any:
        """Where to read a local file from when uploading: CRLF becomes LF.

        Reading as text is what makes this work: any CRLF the file already had
        collapses to LF, so an upload cannot end up with doubled line endings.
        """
        if self.session.transfer_type != "ascii":
            return open(self.path, "rb")
        text = _io.open(self.path, "r", encoding="utf-8", errors="replace",
                        newline=None).read()
        return _io.BytesIO(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Base session
# ---------------------------------------------------------------------------

class BaseSession(object):
    protocol = "base"
    protocol_label = "Base"

    #: True when only one transfer may run at a time on this session.
    #:
    #: FTP needs this.  Its data connections are negotiated over a single
    #: control connection, so two transfers started together race for the one
    #: data socket: measured against the test server, three of four concurrent
    #: downloads came back truncated to a single 64 KB chunk with no error
    #: raised.  FTP is therefore also run one at a time regardless of the
    #: parallel-transfers preference.  SFTP does not need it - every download
    #: runs on its own SSH channel, and four concurrent 3 MB downloads were
    #: verified intact.
    serial_transfers = False

    #: "binary" (byte exact, the default) or "ascii" (line endings translated).
    #: Set per file by the queue, from the extension whitelist.
    transfer_type = "binary"

    def _set_transfer_type(self, mode: str) -> None:
        """Record the mode for the next transfer.

        FTP switches its representation type; SFTP has no such notion and
        converts the line endings itself in :meth:`_text_bytes` /
        :meth:`_text_read`.
        """
        self.transfer_type = "ascii" if mode == "ascii" else "binary"

    @staticmethod
    def _to_unix_newlines(data: bytes) -> bytes:
        """CRLF -> LF, the direction a download from a server needs."""
        return data.replace(b"\r\n", b"\n")

    @staticmethod
    def _to_local_newlines(data: bytes) -> bytes:
        """LF -> CRLF, the direction an upload to a server needs."""
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

    def _text_read(self, path: str) -> bytes:
        """Read a local file for an ASCII upload, in the local convention."""
        with open(path, "rb") as handle:
            return self._to_local_newlines(handle.read())

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = dict(config or {})
        self.host: str = str(self.config.get("host", ""))
        self.port: int = int(self.config.get("port", 0) or 0)
        self.user: str = str(self.config.get("user", ""))
        self.password: str = str(self.config.get("password", ""))
        self.timeout: float = float(self.config.get("timeout", 30) or 30)
        self.keepalive: float = float(self.config.get("keepalive", 30) or 30)
        self.passive: bool = bool(self.config.get("passive", True))
        self.verify_host_key: bool = bool(self.config.get("verify_host_key", False))
        self.lock = threading.RLock()
        self._connected = False
        self._server_banner = ""

    # -- lifecycle ------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def banner(self) -> str:
        return self._server_banner

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def noop(self) -> None:
        """Keep-alive; ignore failures."""

    def cwd(self) -> str:
        """Directory the session currently sits in (remote absolute path)."""
        raise NotImplementedError

    # -- listing --------------------------------------------------------
    def listdir(self, path: Optional[str] = None) -> List[Entry]:
        raise NotImplementedError

    # -- navigation -----------------------------------------------------
    def chdir(self, path: str) -> str:
        raise NotImplementedError

    def mkdir(self, name: str) -> None:
        raise NotImplementedError

    def home(self) -> Optional[str]:
        return None

    # -- mutation -------------------------------------------------------
    def rename(self, old: str, new: str) -> None:
        raise NotImplementedError

    def delete(self, name: str, is_dir: bool = False) -> None:
        raise NotImplementedError

    def delete_recursive(self, name: str, is_dir: bool = True) -> int:
        raise NotImplementedError

    def chmod(self, name: str, mode: int) -> None:
        raise NotImplementedError

    def stat_file(self, name: str) -> Optional[Dict[str, Any]]:
        """Size / mtime / permissions for one path.

        Servers frequently omit the size from a directory listing (older SFTP
        servers, ``LIST`` output without a size column).  Returning ``None``
        tells the caller the value is genuinely unavailable.
        """
        return None

    # -- data -----------------------------------------------------------
    def download_file(self, remote_name: str, local_path: str,
                      progress: ProgressFn = None,
                      control: Optional[TransferControl] = None) -> int:
        raise NotImplementedError

    def upload_file(self, local_path: str, remote_name: str,
                    progress: ProgressFn = None,
                    control: Optional[TransferControl] = None) -> int:
        raise NotImplementedError

    def read_text(self, name: str, limit: int = 1024 * 1024) -> str:
        raise NotImplementedError

    def write_text(self, name: str, text: str) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        user = self.user or "anonymous"
        return "%s://%s@%s:%d" % (self.protocol, user, self.host, self.port)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _report(progress: ProgressFn, done: int, total: Optional[int]) -> None:
        if progress is not None:
            try:
                progress(done, total)
            except Exception:
                pass

    @staticmethod
    def _check(control: Optional[TransferControl]) -> None:
        if control is not None:
            control.check()

    @staticmethod
    def _pace(control: Optional[TransferControl], tick: float = 0.02) -> None:
        if control is not None:
            if not control.wait_if_paused():
                raise Cancelled("cancelled")


# ---------------------------------------------------------------------------
# FTP / FTPS
# ---------------------------------------------------------------------------

class FTPSession(BaseSession):
    protocol = "ftps"

    #: one transfer at a time; see BaseSession.serial_transfers for the
    #: measurement behind this
    serial_transfers = True

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super(FTPSession, self).__init__(config)
        self.protocol = "ftps" if self.config.get("tls") else "ftp"
        self.protocol_label = "FTPS (explicit TLS)" if self.protocol == "ftps" else "FTP"
        self._ftp: Optional[ftplib.FTP] = None
        self._cwd = "/"
        self.encoding = str(self.config.get("encoding", "utf-8") or "utf-8")

    # -- connection -----------------------------------------------------
    def connect(self) -> None:
        with self.lock:
            self.disconnect()
            host = self.host
            port = self.port or 21
            if self.protocol == "ftps":
                ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=self.timeout)
            else:
                ftp = ftplib.FTP(timeout=self.timeout)
            ftp.encoding = self.encoding
            try:
                ftp.connect(host, port, timeout=self.timeout)
                ftp.login(self.user or "anonymous", self.password or "")
                if isinstance(ftp, ftplib.FTP_TLS):
                    ftp.prot_p()
                ftp.set_pasv(self.passive)
                try:
                    ftp.voidcmd("OPTS UTF8 ON")
                except ftplib.all_errors:
                    pass
            except Exception as exc:
                try:
                    ftp.close()
                except Exception:
                    pass
                raise SessionError(human_error(exc))
            self._ftp = ftp
            self._server_banner = ftp.getwelcome() or ""
            self._connected = True
            try:
                self._cwd = ftp.pwd() or "/"
            except ftplib.all_errors:
                self._cwd = "/"

    def disconnect(self) -> None:
        ftp = self._ftp
        self._ftp = None
        self._connected = False
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

    def noop(self) -> None:
        ftp = self._ftp
        if ftp is None:
            return
        try:
            with self.lock:
                ftp.voidcmd("NOOP")
        except Exception:
            pass

    @property
    def ftp(self) -> ftplib.FTP:
        if self._ftp is None:
            raise SessionError("Not connected")
        return self._ftp

    def _reconnect(self) -> None:
        """Try once to re-establish a dropped control connection."""
        if self._ftp is None:
            self.connect()
            return
        try:
            self._ftp.voidcmd("NOOP")
        except Exception:
            self.connect()

    def cwd(self) -> str:
        return self._cwd

    # -- navigation -----------------------------------------------------
    def chdir(self, path: str) -> str:
        with self.lock:
            self._reconnect()
            try:
                self.ftp.cwd(path)
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))
            try:
                self._cwd = self.ftp.pwd() or path
            except ftplib.all_errors:
                self._cwd = path
            return self._cwd

    def mkdir(self, name: str) -> None:
        with self.lock:
            try:
                self.ftp.mkd(name)
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))

    def home(self) -> Optional[str]:
        return None

    # -- listing --------------------------------------------------------
    def listdir(self, path: Optional[str] = None) -> List[Entry]:
        self._sync_control()
        with self.lock:
            self._reconnect()
            ftp = self.ftp
            previous = None
            if path is not None:
                try:
                    previous = ftp.pwd()
                except ftplib.all_errors:
                    previous = None
                try:
                    ftp.cwd(path)
                except ftplib.all_errors as exc:
                    raise SessionError(human_error(exc))
            try:
                entries = self._list_mlsd(ftp)
                if entries is None:
                    entries = self._list_nlst(ftp)
                return entries
            finally:
                if path is not None and previous:
                    try:
                        ftp.cwd(previous)
                    except ftplib.all_errors:
                        pass

    def _list_mlsd(self, ftp: ftplib.FTP) -> Optional[List[Entry]]:
        try:
            lines: List[str] = []
            ftp.retrlines("MLSD", lines.append)
        except ftplib.all_errors:
            return None
        entries: List[Entry] = []
        for line in lines:
            facts, _, name = line.partition("; ")
            if not name:
                # some servers omit the space after the last ';'
                parts = line.split(";")
                name = parts[-1].strip()
                facts = ";".join(parts[:-1])
            if not name or name in (".", ".."):
                continue
            info: Dict[str, str] = {}
            for fact in facts.split(";"):
                if "=" in fact:
                    key, _, value = fact.partition("=")
                    info[key.strip().lower()] = value.strip()
            entry_type = info.get("type", "").lower()
            is_dir = entry_type in ("dir", "cdir", "pdir")
            is_link = entry_type == "os.unix=slink" or "slink" in entry_type
            size = parse_size(info.get("size", ""))
            mtime = self._parse_mlsd_time(info.get("modify", ""))
            # MLSD reports "unix.mode" as octal ("0644"); turn it into the same
            # "-rw-r--r--" form the LIST parser produces, otherwise the
            # Permissions column shows a bare number or nothing at all
            mode = _mode_from_octal(info.get("unix.mode", ""))
            if mode is not None:
                # MLSD reports only the permission bits, so add the file-type
                # bits to get the familiar "-rw-r--r--" / "drwxr-xr-x" string
                if is_dir:
                    mode |= stat_module.S_IFDIR
                elif is_link:
                    mode |= stat_module.S_IFLNK
                else:
                    mode |= stat_module.S_IFREG
                permissions = stat_module.filemode(mode)
            else:
                # no unix.mode: fall back to the RFC 3659 perm fact, which is
                # what most servers actually send
                permissions = _permissions_from_mlsd_perm(
                    info.get("perm", ""), is_dir, is_link)
            entry = Entry(
                name=name, size=size, mtime=mtime, is_dir=is_dir,
                is_link=is_link, mode=mode, permissions=permissions,
                owner=info.get("unix.owner", "") or info.get("unix.uid", ""),
                group=info.get("unix.group", "") or info.get("unix.gid", ""),
            )
            if info.get("perm"):
                # keep the raw fact so the tooltip can spell the letters out
                entry.extra["mlsd_perm"] = info["perm"]
            entries.append(entry)
        return entries

    @staticmethod
    def _parse_mlsd_time(value: str) -> Optional[float]:
        if not value:
            return None
        import calendar
        import datetime
        text = value.strip()
        for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
            try:
                parsed = datetime.datetime.strptime(text[:len(fmt) + 4], fmt)
                return calendar.timegm(parsed.timetuple())
            except ValueError:
                continue
        return None

    def _list_nlst(self, ftp: ftplib.FTP) -> List[Entry]:
        lines: List[str] = []
        ftp.retrlines("LIST", lines.append)
        entries: List[Entry] = []
        for line in lines:
            entry = self._parse_list_line(line)
            if entry is not None:
                entries.append(entry)
        return entries

    @staticmethod
    def _parse_list_line(line: str) -> Optional[Entry]:
        """Best-effort parser for ``ls -l`` style listings."""
        text = line.rstrip("\r\n")
        if not text:
            return None
        if text[0] in "-dlcbps" and len(text) > 10:
            parts = text.split(None, 8)
            if len(parts) < 9:
                return None
            perms = parts[0]
            is_dir = perms.startswith("d")
            is_link = perms.startswith("l")
            owner = parts[2]
            group = parts[3]
            size_text = parts[4]
            name = parts[8]
            link_target = ""
            if is_link and " -> " in name:
                name, _, link_target = name.partition(" -> ")
            if name in (".", ".."):
                return None
            return Entry(
                name=name, size=parse_size(size_text) if not is_dir else 0,
                mtime=None, is_dir=is_dir, is_link=is_link,
                permissions=perms, owner=owner, group=group,
                link_target=link_target,
            )
        # MS-DOS style, which is what Microsoft's FTP service returns:
        #   10-11-26  01:17PM              1661239 7z2603-x64.exe
        #   10-11-26  01:16PM       <DIR>          backup
        # Parsed with a pattern rather than fixed column positions: the padding
        # between the size field and the name varies with the width of the size
        # itself, so slicing at a constant offset mis-reads wider files.  The
        # timestamp is worth taking too, where the fixed slice threw it away.
        dos = _DOS_LIST_RE.match(text)
        if dos:
            month, day, year = (int(dos.group(1)), int(dos.group(2)),
                                int(dos.group(3)))
            # a two digit year that is more than a little ahead belongs to the
            # previous century
            this_year = time.localtime().tm_year % 100
            year += 1900 if year > this_year + 1 else 2000
            hour = int(dos.group(4)) % 12
            if dos.group(6).upper() == "PM":
                hour += 12
            size_field = dos.group(7)
            name = dos.group(8).strip()
            if not name or name in (".", ".."):
                return None
            is_dir = size_field.upper() == "<DIR>"
            stamp = None
            try:
                stamp = time.mktime((year, month, day, hour,
                                     int(dos.group(5)), 0, 0, 0, -1))
            except (ValueError, OverflowError):
                stamp = None
            return Entry(name=name,
                         size=0 if is_dir else parse_size(size_field),
                         mtime=stamp, is_dir=is_dir)
        return None

    # -- mutation -------------------------------------------------------
    def rename(self, old: str, new: str) -> None:
        with self.lock:
            try:
                self.ftp.rename(old, new)
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))

    def delete(self, name: str, is_dir: bool = False) -> None:
        with self.lock:
            try:
                if is_dir:
                    self.ftp.rmd(name)
                else:
                    self.ftp.delete(name)
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))

    def delete_recursive(self, name: str, is_dir: bool = True) -> int:
        """Delete a path, recursing into folders.  Returns how many went.

        Callers report that count back to the user; returning None here used to
        crash the format string that prints it.
        """
        if not is_dir:
            self.delete(name, False)
            return 1
        removed = 0
        for entry in self.listdir(name):
            child = posixpath.join(name, entry.name)
            if entry.is_dir and not entry.is_link:
                removed += self.delete_recursive(child, True)
            else:
                self.delete(child, False)
                removed += 1
        self.delete(name, True)
        return removed + 1

    def chmod(self, name: str, mode: int) -> None:
        with self.lock:
            try:
                self.ftp.sendcmd("SITE CHMOD %o %s" % (mode, name))
            except ftplib.all_errors as exc:
                raise SessionError("Server rejected CHMOD: %s" % human_error(exc))

    def stat_file(self, name: str) -> Optional[Dict[str, Any]]:
        """Ask the server for one file's size (RFC 3659 ``SIZE``).

        Some servers refuse ``SIZE`` while the control connection is in ASCII
        mode, so binary mode is requested first - which is what every client
        does before a transfer anyway.  Any stale reply is cleared beforehand,
        otherwise ``SIZE`` reads the previous command's answer and from that
        point on the whole session is one response behind.
        """
        self._sync_control()
        info: Dict[str, Any] = {}
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                return None
            try:
                # voidcmd() is avoided on purpose: it raises when the server
                # answers with a 2xx other than 200, which some do here
                ftp.sendcmd("TYPE I")
            except FTP_ERRORS:
                pass
            try:
                info["size"] = int(ftp.size(name))
            except FTP_ERRORS + (TypeError, ValueError):
                pass
            try:
                mdtm = ftp.sendcmd("MDTM " + name)
                if mdtm[:3] == "213":
                    stamp = self._parse_mlsd_time(mdtm[4:].strip())
                    if stamp:
                        info["mtime"] = stamp
            except FTP_ERRORS:
                pass
        return info or None

    # -- data -----------------------------------------------------------
    def _new_data_socket(self) -> socket.socket:
        """Open a passive data connection (FTPS wraps it in TLS)."""
        ftp = self.ftp
        host, port = ftp.makepasv()
        if isinstance(ftp, ftplib.FTP_TLS):
            raw = socket.create_connection((host, port), timeout=self.timeout)
            data = ftp.context.wrap_socket(raw, server_hostname=host)
        else:
            data = socket.create_connection((host, port), timeout=self.timeout)
        data.settimeout(1.0)
        return data

    def _pasv_socket(self, command: str) -> socket.socket:
        """Open a passive data connection and send ``command``."""
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                raise SessionError("Not connected")
            if isinstance(ftp, ftplib.FTP_TLS):
                host, port = ftp.makepasv()
                raw = socket.create_connection((host, port), timeout=self.timeout)
                data = ftp.context.wrap_socket(raw, server_hostname=host)
            else:
                host, port = ftp.makepasv()
                data = socket.create_connection((host, port), timeout=self.timeout)
            data.settimeout(1.0)
            ftp.putcmd(command)
            response = ftp.getresp()
            code = response[:3]
            if code not in ("125", "150"):
                try:
                    data.close()
                except Exception:
                    pass
                raise SessionError("Server refused transfer: %s" % response.strip())
            return data

    def _remote_size(self, name: str) -> Optional[int]:
        """Best-effort size lookup that never raises and never desyncs.

        ``SIZE`` is refused by many servers while the control connection is in
        ASCII mode ("550 SIZE not allowed in ASCII mode"), so binary mode is
        requested first.  Any failure here is only used for the progress bar,
        so it must not be able to fail the transfer itself.
        """
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                return None
            # A chatty server sends its extra completion reply only when the
            # next command arrives, so it can still be queued here.  Without
            # this drain the TYPE I below reads that stray 226 and every later
            # reply belongs to the previous command - which is what made a
            # transfer fail with "Server refused transfer: 213 2564".
            self._drain_control(settle=0.05, max_wait=0.25)
            try:
                # sendcmd() rather than voidcmd(): some servers answer with a
                # non-200 2xx here and voidcmd() would raise
                ftp.sendcmd("TYPE I")
                # the connection is binary now, whatever the next transfer
                # wanted, so record it and let _apply_transfer_type re-issue
                self._type_command = "I"
            except FTP_ERRORS:
                pass
            try:
                value = ftp.size(name)
                if value is None:
                    return None
                return int(value)
            except FTP_ERRORS + (TypeError, ValueError):
                return None
            finally:
                # Whatever happened, leave nothing queued for the transfer
                # itself: the size is only used for the progress bar.
                self._drain_control(settle=0.05, max_wait=0.25)

    def switch_to_binary(self) -> bool:
        """Put the data connection in binary (image) mode."""
        self._sync_control()
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                return False
            try:
                ftp.sendcmd("TYPE I")
                return True
            except FTP_ERRORS:
                return False

    def _apply_transfer_type(self) -> None:
        """Put the control connection in binary mode.

        Binary is always used on the wire, even for a file the user asked to
        send as ASCII: measured against pyftpdlib, ``TYPE A`` is accepted with
        "200 Type set to: ASCII" and the server then stores the bytes
        unconverted, so trusting it would silently do nothing.  The line
        endings are therefore translated by this client (see
        :meth:`_convert_downloaded` and the upload loop), which is what
        FileZilla does too and behaves the same everywhere.
        """
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                return
            if getattr(self, "_type_command", None) == "I":
                return
            try:
                ftp.sendcmd("TYPE I")
                self._type_command = "I"
            except FTP_ERRORS:
                self._type_command = "I"

    def _convert_downloaded(self, path: str) -> None:
        """Rewrite a freshly downloaded file with Windows line endings.

        Only called in ASCII mode.  Done on the file rather than on the socket
        so the transfer loop stays a plain byte pump: the server is assumed to
        send the Unix convention and this client stores the Windows one.
        """
        try:
            with open(path, "rb") as handle:
                data = handle.read()
            converted = _to_crlf(data)
            if converted != data:
                with open(path, "wb") as handle:
                    handle.write(converted)
        except OSError:
            pass

    def _begin_transfer(self, command: str) -> socket.socket:
        """Open the data connection for ``command``.

        If the first attempt is refused the control channel may have slipped by
        one reply, so it is drained and the attempt is repeated once.  Without
        this a single stray informational reply turns into a failed transfer.
        """
        try:
            return self._pasv_socket(command)
        except SessionError:
            if not self._drain_control(settle=0.15, max_wait=0.8):
                raise
            return self._pasv_socket(command)

    def download_file(self, remote_name: str, local_path: str,
                      progress: ProgressFn = None,
                      control: Optional[TransferControl] = None) -> int:
        # a transfer that is already cancelled must raise before any command is
        # sent, otherwise the server is left with a half-open data connection
        self._check(control)
        total = self._remote_size(remote_name)
        self._apply_transfer_type()
        data = self._begin_transfer("RETR " + remote_name)
        done = 0
        try:
            self._report(progress, 0, total)
            with open(local_path, "wb") as handle:
                while True:
                    self._check(control)
                    self._pace(control)
                    ready, _, _ = select.select([data], [], [], 0.2)
                    if not ready:
                        continue
                    try:
                        chunk = data.recv(CHUNK)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    self._report(progress, done, total)
            data.close()
        except Cancelled:
            self._abort_transfer(data)
            raise
        except Exception:
            try:
                data.close()
            except Exception:
                pass
            raise
        self._finish_command()
        if self.transfer_type == "ascii":
            # the wire stayed binary, so the line endings are converted here
            self._convert_downloaded(local_path)
        self._report(progress, done, total or done)
        return done

    def upload_file(self, local_path: str, remote_name: str,
                    progress: ProgressFn = None,
                    control: Optional[TransferControl] = None) -> int:
        self._sync_control()
        try:
            total: Optional[int] = os.path.getsize(local_path)
        except OSError:
            total = None
        self._check(control)
        self._apply_transfer_type()
        data = self._begin_transfer("STOR " + remote_name)
        done = 0
        try:
            # in ASCII mode the source is read as text with CRLF line endings,
            # because the wire itself stays binary
            source = _TextStreams(self, local_path).writer()
            try:
                self._report(progress, 0, total)
                while True:
                    self._check(control)
                    self._pace(control)
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    self._send_chunk(data, chunk, control)
                    done += len(chunk)
                    self._report(progress, done, total)
            finally:
                source.close()
            data.close()
        except Cancelled:
            self._abort_transfer(data)
            raise
        except Exception:
            try:
                data.close()
            except Exception:
                pass
            raise
        self._finish_command()
        self._report(progress, done, total or done)
        return done

    def _send_chunk(self, data: socket.socket, chunk: bytes,
                    control: Optional[TransferControl]) -> None:
        """Send ``chunk`` while staying responsive to pause/cancel."""
        view = memoryview(chunk)
        while view:
            self._check(control)
            self._pace(control)
            written = data.send(view)
            if written <= 0:
                raise SessionError("Data connection closed by the server")
            view = view[written:]

    def _abort_transfer(self, data: Optional[socket.socket]) -> None:
        """A cancelled transfer leaves the control channel unusable."""
        if data is not None:
            try:
                data.close()
            except Exception:
                pass
        ftp = self._ftp
        if ftp is not None:
            try:
                ftp.close()
            except Exception:
                pass
        self._ftp = None
        self._connected = False

    # -- control channel hygiene ----------------------------------------
    def _drain_control(self, settle: float = 0.35, max_wait: float = 1.5,
                       require_one: bool = False) -> int:
        """Read and discard trailing 2xx chatter on the control connection.

        Chatty servers send an extra informational reply (typically a second
        ``226``) once a transfer ends, and it can arrive a moment *after* the
        data connection closes.  If it is left in the channel the next command
        reads it instead of its own reply, and from then on every response
        belongs to the previous command - which is exactly how a successful
        transfer gets reported as failed with the message
        "226 Transfer complete.".

        With ``require_one`` the call waits until at least one 2xx has been
        consumed, because a completed transfer is always followed by exactly
        one completion reply.  Returning early there is what lets a late reply
        slip into the next command.

        Only 2xx replies are consumed; anything else is left for the command
        that actually expects it.
        """
        ftp = self._ftp
        if ftp is None:
            return 0
        drained = 0
        deadline = time.time() + max_wait
        while time.time() < deadline:
            if drained and not self._control_has_data(ftp, settle):
                break
            if not drained and not self._control_has_data(ftp, settle):
                if require_one:
                    continue          # keep waiting for the reply
                break
            try:
                response = ftp.getmultiline()
            except (ftplib.error_proto, ftplib.error_reply, OSError, EOFError):
                break
            except Exception:
                break
            code = response[:3]
            if not code.isdigit() or not code.startswith("2"):
                return drained
            drained += 1
            if not require_one:
                continue
            if drained and not self._control_has_data(ftp, settle):
                break
        return drained

    @staticmethod
    def _control_has_data(ftp: Any, timeout: float) -> bool:
        """True when a reply is already buffered or readable right now."""
        reader = getattr(ftp, "file", None)
        try:
            if reader is not None and getattr(reader, "_peek", b""):
                return True
        except Exception:
            pass
        sock = getattr(ftp, "sock", None)
        if sock is None:
            return False
        try:
            ready, _, _ = select.select([sock], [], [], timeout)
        except (OSError, ValueError):
            return False
        return bool(ready)

    def _sync_control(self) -> None:
        """Discard any stray 2xx waiting before the next command.

        FTP guarantees exactly one reply per command, so a reply already queued
        *before* a command is sent cannot be that command's answer - it is
        leftover chatter (a chatty server or a proxy repeating the completion
        line).  Reading it later would shift every following response by one,
        which is how a successful transfer ends up reported as
        "226 Transfer complete.".

        The drain is bounded and consumes only 2xx replies, so a genuine error
        that arrived early is left in place for the command that expects it.
        """
        if self._ftp is None:
            return
        with self.lock:
            try:
                self._drain_control(settle=0.05, max_wait=0.25)
            except Exception:
                pass

    def _finish_command(self) -> None:
        """Consume the completion reply (and any extra chatter) after a
        data transfer.

        ``ftplib.voidresp()`` is too strict here: it rejects anything that is
        not a 2xx *and* raises with the bare response text, so a server that
        sends an extra informational ``226`` makes a successful transfer look
        like a failure.  The data socket already reached EOF, so the transfer
        itself is done - the rest is bookkeeping.
        """
        if self._ftp is None:
            return
        with self.lock:
            self._drain_control(settle=0.35, max_wait=2.0, require_one=True)

    def read_text(self, name: str, limit: int = 1024 * 1024) -> str:
        buffer = io.BytesIO()
        with self.lock:
            try:
                self.ftp.retrbinary("RETR " + name, buffer.write)
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))
        data = buffer.getvalue()[:limit]
        return data.decode("utf-8", "replace")

    def write_text(self, name: str, text: str) -> None:
        payload = text.encode("utf-8")
        with self.lock:
            try:
                self.ftp.storbinary("STOR " + name, io.BytesIO(payload))
            except ftplib.all_errors as exc:
                raise SessionError(human_error(exc))


# ---------------------------------------------------------------------------
# SFTP
# ---------------------------------------------------------------------------

class SFTPSession(BaseSession):
    protocol = "sftp"
    protocol_label = "SFTP (SSH)"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super(SFTPSession, self).__init__(config)
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._cwd = "."
        self._home: Optional[str] = None
        self.key_filename = str(self.config.get("key_filename", "") or "")
        self.key_passphrase = str(self.config.get("key_passphrase", "") or "")

    # -- connection -----------------------------------------------------
    def connect(self) -> None:
        with self.lock:
            self.disconnect()
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            if self.verify_host_key:
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
            else:
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs: Dict[str, Any] = {
                "hostname": self.host,
                "port": self.port or 22,
                "username": self.user or None,
                "password": self.password or None,
                "timeout": self.timeout,
                "banner_timeout": self.timeout,
                "auth_timeout": self.timeout,
                "allow_agent": True,
                "look_for_keys": not bool(self.key_filename),
            }
            if self.key_filename:
                connect_kwargs["key_filename"] = self.key_filename
                if self.key_passphrase:
                    connect_kwargs["passphrase"] = self.key_passphrase
            try:
                client.connect(**connect_kwargs)
                transport = client.get_transport()
                if transport is not None and self.keepalive:
                    transport.set_keepalive(int(self.keepalive))
                sftp = client.open_sftp()
            except Exception as exc:
                try:
                    client.close()
                except Exception:
                    pass
                raise SessionError(human_error(exc))
            self._client = client
            self._sftp = sftp
            self._connected = True
            self._server_banner = ""
            try:
                self._home = sftp.normalize(".")
                self._cwd = self._home
            except Exception:
                self._home = None
                self._cwd = "."

    def disconnect(self) -> None:
        sftp, client = self._sftp, self._client
        self._sftp = None
        self._client = None
        self._connected = False
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def noop(self) -> None:
        sftp = self._sftp
        if sftp is None:
            return
        try:
            with self.lock:
                sftp.normalize(".")
        except Exception:
            pass

    @property
    def sftp(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            raise SessionError("Not connected")
        return self._sftp

    def cwd(self) -> str:
        return self._cwd or "."

    def home(self) -> Optional[str]:
        return self._home

    # -- navigation -----------------------------------------------------
    def chdir(self, path: str) -> str:
        with self.lock:
            try:
                # resolve against our own directory, not the login home: SFTP
                # has no server-side current directory to lean on
                resolved = self.sftp.normalize(self._absolute(path or "."))
            except Exception as exc:
                raise SessionError(human_error(exc))
            self._cwd = resolved
            return resolved

    def mkdir(self, name: str) -> None:
        with self.lock:
            try:
                self.sftp.mkdir(self._absolute(name))
            except Exception as exc:
                raise SessionError(human_error(exc))

    # -- listing --------------------------------------------------------
    def listdir(self, path: Optional[str] = None) -> List[Entry]:
        with self.lock:
            target = self._absolute(path) if path is not None \
                else (self._cwd or ".")
            try:
                attrs = self.sftp.listdir_attr(target)
            except Exception as exc:
                raise SessionError(human_error(exc))
            entries: List[Entry] = []
            for attr in attrs:
                entries.append(self._entry_from_attr(attr))
            return entries

    def _entry_from_attr(self, attr: paramiko.SFTPAttributes) -> Entry:
        """Convert one ``SFTPAttributes`` row.

        Some servers omit ``st_size`` from a directory listing; the entry is
        still returned (so the file is visible) and the UI resolves the real
        size afterwards through :meth:`stat_file`.
        """
        name = attr.filename or ""
        mode = attr.st_mode or 0
        is_link = stat_module.S_ISLNK(mode)
        is_dir = stat_module.S_ISDIR(mode)
        size = attr.st_size
        if size is None and is_dir:
            size = 0
        owner = str(attr.st_uid) if attr.st_uid is not None else ""
        group = str(attr.st_gid) if attr.st_gid is not None else ""
        link_target = ""
        if self._sftp is not None:
            path = posixpath.join(self._cwd or ".", name)
            try:
                target = self._sftp.stat(path)
                is_dir = stat_module.S_ISDIR(target.st_mode or 0)
                if target.st_size is not None:
                    size = target.st_size
                if not attr.st_mtime and target.st_mtime:
                    attr.st_mtime = target.st_mtime
                if target.st_mode:
                    mode = target.st_mode
                if is_link:
                    is_dir = stat_module.S_ISDIR(target.st_mode or 0)
            except Exception:
                pass
            if is_link:
                try:
                    link_target = self._sftp.readlink(path)
                except Exception:
                    link_target = ""
        return Entry(
            name=name, size=size, mtime=attr.st_mtime, is_dir=is_dir,
            is_link=is_link, mode=mode,
            permissions=stat_module.filemode(mode) if mode else "",
            owner=owner, group=group, link_target=link_target,
        )

    def stat_file(self, name: str) -> Optional[Dict[str, Any]]:
        """Resolve size / mtime / permissions for one path via ``stat``."""
        with self.lock:
            sftp = self._sftp
            if sftp is None:
                return None
            path = self._absolute(name)
            info: Dict[str, Any] = {}
            try:
                attr = sftp.stat(path)
            except Exception:
                try:
                    attr = sftp.lstat(path)
                except Exception:
                    return None
            if attr.st_size is not None:
                info["size"] = attr.st_size
            if attr.st_mtime:
                info["mtime"] = attr.st_mtime
            if attr.st_mode:
                info["permissions"] = stat_module.filemode(attr.st_mode)
                info["is_dir"] = stat_module.S_ISDIR(attr.st_mode)
            return info or None

    def _absolute(self, name: str) -> str:
        """Join a listing name onto the current directory, never the session."""
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            return name
        base = self._cwd or "."
        return posixpath.normpath(posixpath.join(base, name))

    # -- mutation -------------------------------------------------------
    def rename(self, old: str, new: str) -> None:
        with self.lock:
            try:
                try:
                    self.sftp.posix_rename(self._absolute(old),
                                           self._absolute(new))
                except (IOError, OSError, AttributeError):
                    self.sftp.rename(self._absolute(old),
                                     self._absolute(new))
            except Exception as exc:
                raise SessionError(human_error(exc))

    def delete(self, name: str, is_dir: bool = False) -> None:
        with self.lock:
            try:
                if is_dir:
                    self.sftp.rmdir(self._absolute(name))
                else:
                    self.sftp.remove(self._absolute(name))
            except Exception as exc:
                raise SessionError(human_error(exc))

    def delete_recursive(self, name: str, is_dir: bool = True) -> int:
        """Delete a path, recursing into folders.  Returns how many went.

        Callers report that count back to the user; returning None here used to
        crash the format string that prints it.
        """
        if not is_dir:
            self.delete(name, False)
            return 1
        removed = 0
        for entry in self.listdir(name):
            child = posixpath.join(name, entry.name)
            if entry.is_dir and not entry.is_link:
                removed += self.delete_recursive(child, True)
            else:
                self.delete(child, False)
                removed += 1
        self.delete(name, True)
        return removed + 1

    def chmod(self, name: str, mode: int) -> None:
        with self.lock:
            try:
                self.sftp.chmod(self._absolute(name), mode)
            except Exception as exc:
                raise SessionError(human_error(exc))

    def _ensure_remote_dir(self, path: str) -> None:
        if not path or path in (".", "/"):
            return
        try:
            self.sftp.stat(self._absolute(path))
            return
        except Exception:
            pass
        parent = posixpath.dirname(path.rstrip("/"))
        if parent and parent != path:
            self._ensure_remote_dir(parent)
        try:
            self.sftp.mkdir(self._absolute(path))
        except Exception:
            pass

    # -- data -----------------------------------------------------------
    def download_file(self, remote_name: str, local_path: str,
                      progress: ProgressFn = None,
                      control: Optional[TransferControl] = None) -> int:
        with self.lock:
            try:
                target = self._absolute(remote_name)
                attr = self.sftp.stat(target)
                total: Optional[int] = attr.st_size
            except Exception:
                total = None
            done = 0
            self._report(progress, 0, total)
            try:
                remote = self.sftp.open(self._absolute(remote_name),
                                        "rb")
            except Exception as exc:
                raise SessionError(human_error(exc))
            try:
                remote.set_pipelined(True)
                # in ASCII mode the reader translates CRLF to LF; the wrapper
                # wraps remote, so closing it closes that as well
                source = _TextStreams(self, local_path, remote).reader()
                with open(local_path, "wb") as handle:
                    while True:
                        self._check(control)
                        self._pace(control)
                        chunk = source.read(CHUNK)
                        if not chunk:
                            break
                        if isinstance(chunk, str):
                            chunk = chunk.encode("utf-8")
                        handle.write(chunk)
                        done += len(chunk)
                        self._report(progress, done, total)
            except Cancelled:
                try:
                    remote.close()
                except Exception:
                    pass
                raise
            except Exception as exc:
                try:
                    remote.close()
                except Exception:
                    pass
                raise SessionError(human_error(exc))
            remote.close()
            self._report(progress, done, total or done)
            if self.config.get("preserve_timestamps") and total is not None:
                try:
                    os.utime(local_path, (time.time(), attr.st_mtime))
                except Exception:
                    pass
            return done

    def upload_file(self, local_path: str, remote_name: str,
                    progress: ProgressFn = None,
                    control: Optional[TransferControl] = None) -> int:
        try:
            total: Optional[int] = os.path.getsize(local_path)
        except OSError:
            total = None
        done = 0
        with self.lock:
            try:
                self._ensure_remote_dir(posixpath.dirname(remote_name))
                remote = self.sftp.open(self._absolute(remote_name),
                                        "wb")
            except Exception as exc:
                raise SessionError(human_error(exc))
            try:
                remote.set_pipelined(True)
                self._report(progress, 0, total)
                # in ASCII mode this reads the local file as text and turns LF
                # into CRLF on the way to the server
                source = _TextStreams(self, local_path).writer()
                while True:
                    self._check(control)
                    self._pace(control)
                    chunk = source.read(CHUNK)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    remote.write(chunk)
                    done += len(chunk)
                    self._report(progress, done, total)
                source.close()
                remote.flush()
            except Cancelled:
                try:
                    remote.close()
                except Exception:
                    pass
                raise
            except Exception as exc:
                try:
                    remote.close()
                except Exception:
                    pass
                raise SessionError(human_error(exc))
            remote.close()
            try:
                if self.config.get("preserve_timestamps"):
                    info = os.stat(local_path)
                    self.sftp.utime(self._absolute(remote_name),
                                    (info.st_atime, info.st_mtime))
                elif self.config.get("preserve_permissions"):
                    info = os.stat(local_path)
                    self.sftp.chmod(self._absolute(remote_name),
                                    stat_module.S_IMODE(info.st_mode))
            except Exception:
                pass
        self._report(progress, done, total or done)
        return done

    def read_text(self, name: str, limit: int = 1024 * 1024) -> str:
        with self.lock:
            try:
                with self.sftp.open(self._absolute(name), "rb") as handle:
                    data = handle.read(limit)
            except Exception as exc:
                raise SessionError(human_error(exc))
        return data.decode("utf-8", "replace")

    def write_text(self, name: str, text: str) -> None:
        with self.lock:
            try:
                with self.sftp.open(self._absolute(name), "wb") as handle:
                    handle.write(text.encode("utf-8"))
            except Exception as exc:
                raise SessionError(human_error(exc))


# ---------------------------------------------------------------------------

def create_session(config: Dict[str, Any]) -> BaseSession:
    """Build the right session class for a connection configuration."""
    protocol = str(config.get("protocol", "ftp")).lower()
    if protocol in ("sftp", "ssh", "scp"):
        return SFTPSession(config)
    return FTPSession(config)


def default_port(protocol: str) -> int:
    return 22 if str(protocol).lower() == "sftp" else 21
