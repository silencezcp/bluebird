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
import select
import socket
import stat as stat_module
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import paramiko

from .models import Entry, parse_size

ProgressFn = Optional[Callable[[int, Optional[int]], None]]

#: data socket read chunk
CHUNK = 64 * 1024

#: ``ftplib.all_errors`` is already a tuple, so it must be flattened before it
#: can be extended - ``except FTP_ERRORS`` would raise
#: ``TypeError: catching classes that do not inherit from BaseException``.
FTP_ERRORS = tuple(ftplib.all_errors) + (OSError, EOFError)


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
# Base session
# ---------------------------------------------------------------------------

class BaseSession(object):
    protocol = "base"
    protocol_label = "Base"

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

    def delete_recursive(self, name: str, is_dir: bool = True) -> None:
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
            entries.append(Entry(
                name=name, size=size, mtime=mtime, is_dir=is_dir,
                is_link=is_link, permissions=info.get("unix.mode", ""),
                owner=info.get("unix.owner", "") or info.get("unix.uid", ""),
                group=info.get("unix.group", "") or info.get("unix.gid", ""),
            ))
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
        # MS-DOS style: 04-27-00  09:09PM       <DIR>          name
        if len(text) > 39 and text[2] == "-" and text[5] == "-":
            size_text = text[18:30].strip()
            name = text[39:].strip()
            if not name:
                return None
            is_dir = size_text.upper() == "<DIR>"
            return Entry(name=name, size=0 if is_dir else parse_size(size_text),
                         is_dir=is_dir, mtime=None)
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

    def delete_recursive(self, name: str, is_dir: bool = True) -> None:
        if not is_dir:
            self.delete(name, False)
            return
        for entry in self.listdir(name):
            child = posixpath.join(name, entry.name)
            if entry.is_dir and not entry.is_link:
                self.delete_recursive(child, True)
            else:
                self.delete(child, False)
        self.delete(name, True)

    def chmod(self, name: str, mode: int) -> None:
        with self.lock:
            try:
                self.ftp.sendcmd("SITE CHMOD %o %s" % (mode, name))
            except ftplib.all_errors as exc:
                raise SessionError("Server rejected CHMOD: %s" % human_error(exc))

    def stat_file(self, name: str) -> Optional[Dict[str, Any]]:
        """Ask the server for one file's size (RFC 3659 ``SIZE``).

        Most servers refuse ``SIZE`` while the control connection is in ASCII
        mode, so switch to binary first - which is what every client does
        before a transfer anyway.
        """
        info: Dict[str, Any] = {}
        with self.lock:
            ftp = self._ftp
            if ftp is None:
                return None
            try:
                ftp.voidcmd("TYPE I")
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

    def download_file(self, remote_name: str, local_path: str,
                      progress: ProgressFn = None,
                      control: Optional[TransferControl] = None) -> int:
        total: Optional[int] = None
        try:
            total = self.ftp.size(remote_name)
        except Exception:
            total = None
        data = self._pasv_socket("RETR " + remote_name)
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
        self._report(progress, done, total or done)
        return done

    def upload_file(self, local_path: str, remote_name: str,
                    progress: ProgressFn = None,
                    control: Optional[TransferControl] = None) -> int:
        try:
            total: Optional[int] = os.path.getsize(local_path)
        except OSError:
            total = None
        data = self._pasv_socket("STOR " + remote_name)
        done = 0
        try:
            with open(local_path, "rb") as handle:
                self._report(progress, 0, total)
                while True:
                    self._check(control)
                    self._pace(control)
                    chunk = handle.read(CHUNK)
                    if not chunk:
                        break
                    self._send_chunk(data, chunk, control)
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

    def _finish_command(self) -> None:
        """Read the trailing 226 response (tolerate chatty servers)."""
        ftp = self._ftp
        if ftp is None:
            return
        try:
            with self.lock:
                ftp.voidresp()
        except Exception:
            pass

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
                resolved = self.sftp.normalize(path or ".")
            except Exception as exc:
                raise SessionError(human_error(exc))
            self._cwd = resolved
            return resolved

    def mkdir(self, name: str) -> None:
        with self.lock:
            try:
                self.sftp.mkdir(name)
            except Exception as exc:
                raise SessionError(human_error(exc))

    # -- listing --------------------------------------------------------
    def listdir(self, path: Optional[str] = None) -> List[Entry]:
        with self.lock:
            target = path if path is not None else (self._cwd or ".")
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
                    self.sftp.posix_rename(old, new)
                except (IOError, OSError, AttributeError):
                    self.sftp.rename(old, new)
            except Exception as exc:
                raise SessionError(human_error(exc))

    def delete(self, name: str, is_dir: bool = False) -> None:
        with self.lock:
            try:
                if is_dir:
                    self.sftp.rmdir(name)
                else:
                    self.sftp.remove(name)
            except Exception as exc:
                raise SessionError(human_error(exc))

    def delete_recursive(self, name: str, is_dir: bool = True) -> None:
        if not is_dir:
            self.delete(name, False)
            return
        for entry in self.listdir(name):
            child = posixpath.join(name, entry.name)
            if entry.is_dir and not entry.is_link:
                self.delete_recursive(child, True)
            else:
                self.delete(child, False)
        self.delete(name, True)

    def chmod(self, name: str, mode: int) -> None:
        with self.lock:
            try:
                self.sftp.chmod(name, mode)
            except Exception as exc:
                raise SessionError(human_error(exc))

    def _ensure_remote_dir(self, path: str) -> None:
        if not path or path in (".", "/"):
            return
        try:
            self.sftp.stat(path)
            return
        except Exception:
            pass
        parent = posixpath.dirname(path.rstrip("/"))
        if parent and parent != path:
            self._ensure_remote_dir(parent)
        try:
            self.sftp.mkdir(path)
        except Exception:
            pass

    # -- data -----------------------------------------------------------
    def download_file(self, remote_name: str, local_path: str,
                      progress: ProgressFn = None,
                      control: Optional[TransferControl] = None) -> int:
        with self.lock:
            try:
                attr = self.sftp.stat(remote_name)
                total: Optional[int] = attr.st_size
            except Exception:
                total = None
            done = 0
            self._report(progress, 0, total)
            try:
                remote = self.sftp.open(remote_name, "rb")
            except Exception as exc:
                raise SessionError(human_error(exc))
            try:
                remote.set_pipelined(True)
                with open(local_path, "wb") as handle:
                    while True:
                        self._check(control)
                        self._pace(control)
                        chunk = remote.read(CHUNK)
                        if not chunk:
                            break
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
                remote = self.sftp.open(remote_name, "wb")
            except Exception as exc:
                raise SessionError(human_error(exc))
            try:
                remote.set_pipelined(True)
                self._report(progress, 0, total)
                with open(local_path, "rb") as handle:
                    while True:
                        self._check(control)
                        self._pace(control)
                        chunk = handle.read(CHUNK)
                        if not chunk:
                            break
                        remote.write(chunk)
                        done += len(chunk)
                        self._report(progress, done, total)
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
                    self.sftp.utime(remote_name, (info.st_atime, info.st_mtime))
                elif self.config.get("preserve_permissions"):
                    info = os.stat(local_path)
                    self.sftp.chmod(remote_name, stat_module.S_IMODE(info.st_mode))
            except Exception:
                pass
        self._report(progress, done, total or done)
        return done

    def read_text(self, name: str, limit: int = 1024 * 1024) -> str:
        with self.lock:
            try:
                with self.sftp.open(name, "rb") as handle:
                    data = handle.read(limit)
            except Exception as exc:
                raise SessionError(human_error(exc))
        return data.decode("utf-8", "replace")

    def write_text(self, name: str, text: str) -> None:
        with self.lock:
            try:
                with self.sftp.open(name, "wb") as handle:
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
