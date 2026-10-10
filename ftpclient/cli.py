"""Command line interface for BlueBird.

Shares the whole networking layer with the GUI: :mod:`ftpclient.session` does
the protocol work and :mod:`ftpclient.transfer` plans recursive jobs, so the two
front ends cannot drift apart.  No Qt is imported here, which is what makes the
CLI usable in scripts and on machines without a display.

Examples::

    bluebird ls sftp://silence@192.168.31.142:22
    bluebird get sftp://silence@host/pub/file.bin -d C:\\Temp
    bluebird put ./build.zip ftp://user@host -r /releases
    bluebird mirror sftp://user@host -r /var/www -d ./www --delete
    bluebird stat ftp://user@host -r /pub/report.pdf
    bluebird ls --saved fa2oa
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import posixpath
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from . import __appname__, __version__
from . import config as _config
from . import session as _session

#: exit codes, so shell scripts can tell the cases apart
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

PROGRAM = "bluebird"


class CliError(Exception):
    """A problem worth printing without a traceback."""


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------
class Reporter(object):
    """Writes progress and messages, keeping stdout clean for piping."""

    def __init__(self, quiet: bool = False, stream: Any = None) -> None:
        self.quiet = quiet
        self.stream = stream or sys.stderr
        self.items = 0
        self.bytes = 0
        self.failures: List[Tuple[str, str]] = []

    def say(self, message: str) -> None:
        if not self.quiet:
            self.stream.write(message + "\n")
            self.stream.flush()

    def error(self, message: str) -> None:
        self.stream.write("%s: %s\n" % (PROGRAM, message))
        self.stream.flush()

    def progress(self, done: int, total: Optional[int]) -> None:
        if self.quiet:
            return
        if total:
            self.stream.write("\r  %s / %s (%.0f%%)"
                              % (human_size(done), human_size(total),
                                 done * 100.0 / total))
        else:
            self.stream.write("\r  %s" % human_size(done))
        self.stream.flush()
        if total and done >= total:
            self.stream.write("\n")

    def done(self, name: str, size: int) -> None:
        if not self.quiet and self.stream.isatty():
            self.stream.write("\r")
        self.items += 1
        self.bytes += size
        self.say("  ok  %s (%s)" % (name, human_size(size)))

    def failed(self, name: str, message: str) -> None:
        self.failures.append((name, message))
        self.error("%s: %s" % (name, message))


def human_size(value: Optional[int]) -> str:
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return ("%d %s" % (size, unit)) if unit == "B" \
                else ("%.1f %s" % (size, unit))
        size /= 1024.0
    return "%.1f TB" % size


def human_time(stamp: Optional[float]) -> str:
    if not stamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp))


def mode_of(entry: Any) -> str:
    return entry.permissions or "-"


# ---------------------------------------------------------------------------
# connection resolution
# ---------------------------------------------------------------------------
def parse_target(text: str) -> Dict[str, Any]:
    """Turn ``sftp://user@host:22`` into a partial connection config.

    Also accepts a bare ``user@host``, a plain ``host``, and the name of a
    connection saved in config.ini.
    """
    config: Dict[str, Any] = {}
    remainder = text.strip()
    if "://" in remainder:
        scheme, _, remainder = remainder.partition("://")
        scheme = scheme.lower()
        if scheme not in ("ftp", "ftps", "sftp"):
            raise CliError("unknown protocol %r (use ftp, ftps or sftp)"
                           % scheme)
        config["protocol"] = scheme
    if "@" in remainder:
        credentials, _, remainder = remainder.rpartition("@")
        if credentials:
            user, _, password = credentials.partition(":")
            if user:
                config["user"] = user
            if password:
                config["password"] = password
    # host[:port][/path]
    path = ""
    if "/" in remainder:
        remainder, _, path = remainder.partition("/")
        path = "/" + path
    if ":" in remainder:
        host, _, port = remainder.partition(":")
        if port:
            if not port.isdigit():
                raise CliError("port %r is not a number" % port)
            config["port"] = int(port)
        remainder = host
    if remainder:
        config["host"] = remainder
    if path:
        config["remote_dir"] = path
    return config


def resolve_connection(args: argparse.Namespace) -> Dict[str, Any]:
    """Merge the command line, a saved connection and the environment."""
    store = _config.ConnectionStore()
    store.load()

    config: Dict[str, Any] = {}
    target = getattr(args, "target", None)
    saved = getattr(args, "saved", None)

    if saved:
        record = store.get(saved)
        if record is None:
            # allow matching by the displayed name, which may differ
            for name in store.names():
                candidate = store.get(name) or {}
                if candidate.get("name") == saved:
                    record = candidate
                    break
        if record is None:
            raise CliError("no saved connection called %r (have: %s)"
                           % (saved, ", ".join(store.names()) or "none"))
        config.update(record)
    elif target:
        parsed = parse_target(target)
        config.update(parsed)
        # a saved connection with the same host supplies the extras
        if parsed.get("host"):
            found = store.find_by_host(parsed["host"])
            if found and not parsed.get("user"):
                config = dict(found, **{k: v for k, v in parsed.items()
                                        if v})
        if not config.get("host"):
            record = store.get(target)
            if record is None:
                for name in store.names():
                    candidate = store.get(name) or {}
                    if candidate.get("name") == target:
                        record = candidate
                        break
            if record is not None:
                config.update(record)
    else:
        raise CliError("no target: give a URL like sftp://user@host or "
                       "--saved NAME")

    # explicit flags win over everything
    for flag, key in (("protocol", "protocol"), ("port", "port"),
                      ("user", "user"), ("password", "password"),
                      ("key", "key_filename"), ("remote_dir", "remote_dir"),
                      ("encoding", "encoding")):
        value = getattr(args, flag, None)
        if value not in (None, ""):
            config[key] = value
    if getattr(args, "timeout", None):
        config["timeout"] = args.timeout
    if getattr(args, "passive", None) is not None:
        config["passive"] = args.passive
    if getattr(args, "verify_host_key", False):
        config["verify_host_key"] = True

    env_password = os.environ.get("BLUEBIRD_PASSWORD") or \
        os.environ.get("NACRE_FTP_PASSWORD")
    if env_password and not config.get("password"):
        config["password"] = env_password

    protocol = str(config.get("protocol") or "ftp").lower()
    config["protocol"] = protocol
    config.setdefault("host", "")
    config.setdefault("port", 22 if protocol == "sftp" else 21)
    config.setdefault("user", "")
    config.setdefault("timeout", 30)
    if not config["host"]:
        raise CliError("no host given")
    return config


def ask_password(config: Dict[str, Any]) -> None:
    """Prompt for a password when one is needed and none was supplied."""
    if config.get("password"):
        return
    if config.get("key_filename"):
        return
    if str(config.get("protocol")) == "sftp" and _default_key_exists(config):
        return
    if not sys.stdin.isatty():
        raise CliError("no password given (use --password, "
                       "BLUEBIRD_PASSWORD, or a saved connection)")
    prompt = "%s@%s's password: " % (config.get("user") or "anonymous",
                                     config.get("host"))
    try:
        config["password"] = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        raise CliError("no password given")


def _default_key_exists(config: Dict[str, Any]) -> bool:
    home = os.path.expanduser("~")
    for name in ("id_ed25519", "id_rsa", "id_ecdsa"):
        if os.path.isfile(os.path.join(home, ".ssh", name)):
            return True
    return False


def open_session(args: argparse.Namespace,
                 reporter: Reporter) -> Tuple[Any, Dict[str, Any]]:
    config = resolve_connection(args)
    ask_password(config)
    session = _session.create_session(config)
    try:
        session.connect()
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        raise CliError("could not connect to %s:%s: %s"
                       % (config["host"], config["port"],
                          _session.human_error(exc)))
    return session, config


# ---------------------------------------------------------------------------
# remote path helpers
# ---------------------------------------------------------------------------
def remote_join(directory: str, name: str) -> str:
    base = (directory or "").rstrip("/")
    return "%s/%s" % (base, name) if base else name


def require_remote_arg(args: argparse.Namespace) -> str:
    value = getattr(args, "remote", None)
    if not value:
        raise CliError("this command needs a remote path (-r/--remote)")
    return value


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_ls(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        try:
            entries = session.listdir(args.path or None)
        except _session.SessionError as exc:
            # a missing folder is a normal, reportable failure - exit 1, not
            # the usage error the exception would otherwise produce
            report.error("%s: %s" % (args.path or ".",
                                     _session.human_error(exc)))
            return EXIT_ERROR
    finally:
        session.disconnect()
    entries = [e for e in entries if e.name not in (".", "..")]
    if not args.all:
        entries = [e for e in entries if not e.name.startswith(".")]
    if args.pattern:
        entries = [e for e in entries
                   if fnmatch.fnmatch(e.name, args.pattern)]
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

    if args.json:
        out.write(json.dumps([{
            "name": e.name, "dir": bool(e.is_dir), "link": bool(e.is_link),
            "size": e.size, "modified": e.mtime,
            "permissions": e.permissions, "owner": e.owner,
        } for e in entries], indent=2, ensure_ascii=False) + "\n")
        return EXIT_OK

    for entry in entries:
        if args.long:
            out.write("%-11s %10s  %-19s %s%s\n"
                      % (mode_of(entry),
                         "<DIR>" if entry.is_dir else human_size(entry.size),
                         human_time(entry.mtime), entry.name,
                         "/" if entry.is_dir else ""))
        else:
            out.write("%s%s\n" % (entry.name, "/" if entry.is_dir else ""))
    if args.long:
        files = [e for e in entries if not e.is_dir]
        dirs = [e for e in entries if e.is_dir]
        total = sum(int(e.size or 0) for e in files)
        report.say("%d folder(s), %d file(s), %s"
                   % (len(dirs), len(files), human_size(total)))
    return EXIT_OK


def cmd_stat(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        target = require_remote_arg(args)
        info = session.stat_file(target) or {}
        parent = posixpath.dirname(target) or "/"
        name = posixpath.basename(target)
        entry = None
        for candidate in session.listdir(parent) or []:
            if candidate.name == name:
                entry = candidate
                break
    finally:
        session.disconnect()

    payload = {"path": target, "exists": bool(info or entry)}
    if entry is not None:
        payload.update({
            "name": entry.name, "dir": bool(entry.is_dir),
            "link": bool(entry.is_link), "size": entry.size,
            "modified": entry.mtime, "permissions": entry.permissions,
            "owner": entry.owner, "group": entry.group,
        })
    if info.get("size") is not None:
        payload["size"] = info["size"]
    if info.get("mtime"):
        payload["modified"] = info["mtime"]

    if args.json:
        out.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        out.write("%-14s %s\n" % ("path:", payload["path"]))
        out.write("%-14s %s\n" % ("exists:", "yes" if payload["exists"]
                                  else "no"))
        for key in ("dir", "link", "size", "modified", "permissions",
                    "owner", "group"):
            if key not in payload or payload[key] in (None, ""):
                continue
            value = payload[key]
            if key == "size":
                value = "%s (%s bytes)" % (human_size(value), value)
            elif key == "modified":
                value = human_time(value)
            out.write("%-14s %s\n" % (key + ":", value))
    if not payload["exists"]:
        return EXIT_ERROR
    return EXIT_OK


def cmd_get(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        target = require_remote_arg(args)
        if args.dest:
            if os.path.isdir(args.dest) or args.dest.endswith(os.sep):
                local = os.path.join(args.dest, posixpath.basename(target))
            else:
                local = args.dest
        else:
            local = os.path.basename(target) or "download"
        parent = os.path.dirname(os.path.abspath(local))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

        # is it a directory?
        parent_remote = posixpath.dirname(target) or "/"
        name = posixpath.basename(target)
        entry = None
        try:
            for candidate in session.listdir(parent_remote) or []:
                if candidate.name == name:
                    entry = candidate
                    break
        except Exception:  # noqa: BLE001 - a plain file may not be listable
            entry = None

        if entry is not None and entry.is_dir:
            return _download_tree(session, target, local, args, report)

        if not args.force and os.path.exists(local):
            report.error("%s already exists (use --force)" % local)
            return EXIT_ERROR
        downloaded = session.download_file(target, local, report.progress)
        report.done("%s -> %s" % (target, local), downloaded)
        return EXIT_OK
    finally:
        session.disconnect()


def _download_tree(session: Any, remote_dir: str, local_dir: str,
                   args: argparse.Namespace, report: Reporter) -> int:
    """Recursive download using the same planner the GUI uses."""
    from .transfer import plan_downloads

    entries = session.listdir(remote_dir)
    entries = [e for e in entries if e.name not in (".", "..")]
    if not args.all:
        entries = [e for e in entries if not e.name.startswith(".")]
    items = plan_downloads(session, remote_dir, entries, local_dir)
    report.say("%d item(s) to download" % len(items))

    for item in items:
        if item.is_dir:
            try:
                _session.ensure_local_dir(item.target)
                report.say("  dir %s" % item.target)
            except _session.SessionError as exc:
                report.failed(item.target, str(exc))
            continue
        if not args.force and os.path.exists(item.target):
            report.say("  skip %s (exists)" % item.target)
            continue
        try:
            _download_tree_file(session, item, report)
        except Exception as exc:  # noqa: BLE001
            report.failed(item.source, _session.human_error(exc))
    return _finish(report)


def _download_tree_file(session: Any, item: Any, report: Reporter) -> None:
    size = session.download_file(item.source, item.target, report.progress)
    report.done("%s -> %s" % (item.source, item.target), size)


def cmd_put(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    local_paths = list(args.local or [])
    if not local_paths:
        raise CliError("nothing to upload: give one or more local paths")
    missing = [p for p in local_paths if not os.path.exists(p)]
    if missing:
        raise CliError("local path not found: %s" % ", ".join(missing))

    session, config = open_session(args, report)
    try:
        target_dir = args.remote or config.get("remote_dir") or "."
        session.chdir(target_dir)
        for path in local_paths:
            if os.path.isdir(path):
                _upload_tree(session, path, target_dir, args, report)
            else:
                name = os.path.basename(path)
                remote = remote_join(target_dir, name)
                if not args.force and _remote_exists(session, remote):
                    report.error("%s already exists (use --force)" % remote)
                    continue
                try:
                    size = session.upload_file(path, name, report.progress)
                    report.done("%s -> %s" % (path, remote), size)
                except Exception as exc:  # noqa: BLE001
                    report.failed(path, _session.human_error(exc))
    finally:
        session.disconnect()
    return _finish(report)


def _remote_exists(session: Any, remote: str) -> bool:
    parent = posixpath.dirname(remote) or "/"
    name = posixpath.basename(remote)
    try:
        return any(e.name == name for e in session.listdir(parent) or [])
    except Exception:  # noqa: BLE001
        return False


def _upload_tree(session: Any, local_dir: str, target_dir: str,
                 args: argparse.Namespace, report: Reporter) -> None:
    from .transfer import plan_uploads

    files = plan_uploads([local_dir], target_dir)
    report.say("%d item(s) to upload" % len(files))
    # make the directories first, shallowest first
    for item in sorted(files, key=lambda i: len(i.target)):
        if item.is_dir:
            try:
                session.mkdir(item.target)
                report.say("  dir %s" % item.target)
            except Exception as exc:  # noqa: BLE001 - may already exist
                if "exist" not in _session.human_error(exc).lower():
                    report.failed(item.target, _session.human_error(exc))
    for item in files:
        if item.is_dir:
            continue
        if not args.force and _remote_exists(session, item.target):
            report.say("  skip %s (exists)" % item.target)
            continue
        try:
            remote_name = posixpath.basename(item.target)
            directory = posixpath.dirname(item.target) or "."
            session.chdir(directory)
            size = session.upload_file(item.source, remote_name,
                                       report.progress)
            report.done("%s -> %s" % (item.source, item.target), size)
        except Exception as exc:  # noqa: BLE001
            report.failed(item.source, _session.human_error(exc))


def _already_exists(exc: Exception) -> bool:
    text = _session.human_error(exc).lower()
    return ("exist" in text or "failure" in text or "file exists" in text)


def remote_mkdir_p(session: Any, path: str) -> bool:
    """Create a remote folder and its parents; True when it was created.

    A CLI runs the same command twice without thinking about it, so an
    existing folder is not an error.
    """
    path = (path or "").strip()
    if not path or path in (".", "/"):
        return False
    parent = posixpath.dirname(path.rstrip("/"))
    if parent and parent != path and parent != "/":
        remote_mkdir_p(session, parent)
    try:
        session.mkdir(path)
        return True
    except Exception as exc:  # noqa: BLE001
        if _already_exists(exc):
            return False
        raise


def cmd_mkdir(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        for path in require_remote_arg(args).split(","):
            path = path.strip()
            if not path:
                continue
            try:
                created = remote_mkdir_p(session, path)
                report.say("  %s %s" % ("created" if created else "exists ",
                                        path))
            except Exception as exc:  # noqa: BLE001
                report.failed(path, _session.human_error(exc))
    finally:
        session.disconnect()
    return _finish(report)


def cmd_rm(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        for path in require_remote_arg(args).split(","):
            path = path.strip()
            if not path:
                continue
            try:
                if args.recursive:
                    count = session.delete_recursive(path)
                    report.done("deleted %s" % path, 0)
                    report.say("     (%d object(s) removed)" % count)
                else:
                    session.delete(path)
                    report.done("deleted %s" % path, 0)
            except Exception as exc:  # noqa: BLE001
                report.failed(path, _session.human_error(exc))
    finally:
        session.disconnect()
    return _finish(report)


def cmd_rename(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        session.rename(require_remote_arg(args), args.to)
        report.say("  renamed %s -> %s" % (args.remote, args.to))
    finally:
        session.disconnect()
    return _finish(report)


def cmd_chmod(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        session.chmod(require_remote_arg(args), args.mode)
        report.say("  %s -> %s" % (args.remote, args.mode))
    finally:
        session.disconnect()
    return _finish(report)


def cmd_cat(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, _config_used = open_session(args, report)
    try:
        text = session.read_text(require_remote_arg(args))
    finally:
        session.disconnect()
    out.write(text)
    if not text.endswith("\n"):
        out.write("\n")
    return EXIT_OK


def cmd_tree(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    session, config = open_session(args, report)
    root = args.path or config.get("remote_dir") or "."
    try:
        _print_tree(session, root, out, args, report, prefix="", depth=0)
    finally:
        session.disconnect()
    return EXIT_OK


def _print_tree(session: Any, path: str, out: Any, args: argparse.Namespace,
                report: Reporter, prefix: str, depth: int) -> None:
    if args.max_depth is not None and depth >= args.max_depth:
        return
    try:
        entries = session.listdir(path)
    except Exception as exc:  # noqa: BLE001
        report.error("%s: %s" % (path, _session.human_error(exc)))
        return
    entries = [e for e in entries if e.name not in (".", "..")]
    if not args.all:
        entries = [e for e in entries if not e.name.startswith(".")]
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        branch = "`-- " if last else "|-- "
        suffix = "/" if entry.is_dir else ""
        if args.long and not entry.is_dir:
            out.write("%s%s%s%s  (%s)\n"
                      % (prefix, branch, entry.name, suffix,
                         human_size(entry.size)))
        else:
            out.write("%s%s%s%s\n" % (prefix, branch, entry.name, suffix))
        if entry.is_dir:
            child = remote_join(path, entry.name)
            _print_tree(session, child, out, args, report,
                        prefix + ("    " if last else "|   "), depth + 1)


def cmd_mirror(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    """Download the remote tree into a local folder."""
    session, config = open_session(args, report)
    remote = args.remote or config.get("remote_dir") or "."
    local = args.dest or "."
    try:
        if not os.path.isdir(local):
            os.makedirs(local)
        _mirror(session, remote, local, args, report)
    finally:
        session.disconnect()
    return _finish(report)


def _mirror(session: Any, remote_dir: str, local_dir: str,
            args: argparse.Namespace, report: Reporter) -> None:
    try:
        entries = session.listdir(remote_dir)
    except Exception as exc:  # noqa: BLE001
        report.error("%s: %s" % (remote_dir, _session.human_error(exc)))
        return
    entries = [e for e in entries if e.name not in (".", "..")]
    if not args.all:
        entries = [e for e in entries if not e.name.startswith(".")]
    if args.pattern:
        entries = [e for e in entries
                   if fnmatch.fnmatch(e.name, args.pattern)]

    wanted = set()
    for entry in entries:
        local_path = os.path.join(local_dir, entry.name)
        wanted.add(os.path.normcase(entry.name))
        remote_path = remote_join(remote_dir, entry.name)
        if entry.is_dir:
            if not os.path.isdir(local_path):
                os.makedirs(local_path)
            _mirror(session, remote_path, local_path, args, report)
            continue
        if os.path.exists(local_path) and not args.force:
            remote_size = entry.size
            if remote_size is not None \
                    and os.path.getsize(local_path) == remote_size:
                report.say("  same %s" % local_path)
                continue
        try:
            size = session.download_file(remote_path, local_path,
                                         report.progress)
            report.done("%s -> %s" % (remote_path, local_path), size)
        except Exception as exc:  # noqa: BLE001
            report.failed(remote_path, _session.human_error(exc))

    if args.delete:
        for name in sorted(os.listdir(local_dir)):
            if os.path.normcase(name) in wanted:
                continue
            victim = os.path.join(local_dir, name)
            try:
                if os.path.isdir(victim):
                    import shutil
                    shutil.rmtree(victim)
                else:
                    os.remove(victim)
                report.say("  removed %s (not on the server)" % victim)
            except OSError as exc:
                report.failed(victim, str(exc))


def _finish(report: Reporter) -> int:
    if report.failures:
        report.error("%d item(s) failed" % len(report.failures))
        return EXIT_ERROR
    if report.items and not report.quiet:
        report.say("done: %d item(s), %s" % (report.items,
                                             human_size(report.bytes)))
    return EXIT_OK


def cmd_sites(args: argparse.Namespace, out: Any, report: Reporter) -> int:
    """List the connections saved in config.ini."""
    store = _config.ConnectionStore()
    store.load()
    names = store.names()
    if args.json:
        out.write(json.dumps([store.get(n) for n in names], indent=2,
                             ensure_ascii=False) + "\n")
        return EXIT_OK
    if not names:
        report.say("no saved connections (%s)" % store.path)
        return EXIT_OK
    out.write("%-28s %-6s %-24s %s\n"
              % ("NAME", "PROTO", "HOST", "PATH"))
    for name in names:
        site = store.get(name) or {}
        host = "%s:%s" % (site.get("host", ""), site.get("port", ""))
        out.write("%-28s %-6s %-24s %s\n"
                  % (site.get("name") or name,
                     str(site.get("protocol", "")).upper(), host,
                     site.get("remote_dir", "")))
    report.say("%d saved connection(s) in %s" % (len(names), store.path))
    return EXIT_OK


def cmd_selftest(args: argparse.Namespace, out: Any,
                 report: Reporter) -> int:
    """Report what the CLI can see, for troubleshooting."""
    from . import resources
    out.write("%s %s\n" % (__appname__, __version__))
    out.write("python       : %s\n" % sys.version.split()[0])
    out.write("frozen       : %s\n" % resources.is_frozen())
    out.write("resource     : %s\n" % resources.resource_root())
    store = _config.ConnectionStore()
    store.load()
    out.write("config.ini   : %s (%d saved)\n"
              % (store.path, len(store.names())))
    out.write("settings     : %s\n" % _config.default_settings_path())
    try:
        import paramiko
        out.write("paramiko     : %s\n" % paramiko.__version__)
    except Exception as exc:  # noqa: BLE001
        out.write("paramiko     : MISSING (%s)\n" % exc)
    try:
        import nacl
        out.write("pynacl       : %s\n" % getattr(nacl, "__version__", "?"))
    except Exception as exc:  # noqa: BLE001
        out.write("pynacl       : MISSING (%s)\n" % exc)
    out.write("commands     : %s\n" % ", ".join(
        name[4:].replace("_", "-")
        for name in sorted(_COMMANDS)))
    return EXIT_OK


#: every implemented subcommand, for the self test and the tests
_COMMANDS = (
    "cmd_ls", "cmd_stat", "cmd_get", "cmd_put", "cmd_mirror", "cmd_tree",
    "cmd_mkdir", "cmd_rm", "cmd_rename", "cmd_chmod", "cmd_cat", "cmd_sites",
    "cmd_selftest",
)


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------
def _add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("target", nargs="?",
                        help="sftp://user@host:22 or a saved connection name")
    parser.add_argument("--saved", metavar="NAME",
                        help="use a connection from config.ini")
    parser.add_argument("--user", help="user name")
    parser.add_argument("--password", help="password (also BLUEBIRD_PASSWORD)")
    parser.add_argument("--key", dest="key", metavar="FILE",
                        help="private key file for SFTP")
    parser.add_argument("--protocol", choices=["ftp", "ftps", "sftp"],
                        help="force the protocol")
    parser.add_argument("--port", type=int, help="port")
    parser.add_argument("--timeout", type=float, default=30,
                        help="socket timeout in seconds (default 30)")
    parser.add_argument("--active", dest="passive", action="store_false",
                        default=None, help="use active mode for FTP")
    parser.add_argument("--verify-host-key", action="store_true",
                        help="refuse unknown SSH host keys")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="%s %s - command line FTP / FTPS / SFTP client"
                    % (__appname__, __version__),
        epilog="Run '%s COMMAND --help' for the options of one command."
               % PROGRAM)
    parser.add_argument("--version", action="version",
                        version="%s %s" % (__appname__, __version__))
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="no progress or summary output")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("ls", help="list a remote folder")
    _add_connection_options(p)
    p.add_argument("path", nargs="?", help="remote folder (default: home)")
    p.add_argument("-l", "--long", action="store_true",
                   help="permissions, size and date")
    p.add_argument("-a", "--all", action="store_true",
                   help="include hidden entries")
    p.add_argument("--json", action="store_true", help="machine readable")
    p.add_argument("--pattern", help="glob filter, e.g. '*.log'")
    p.set_defaults(handler=cmd_ls)

    p = sub.add_parser("stat", help="show one remote path's details")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True, help="remote path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_stat)

    p = sub.add_parser("get", help="download a file or folder")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True, help="remote path")
    p.add_argument("-d", "--dest", help="local file or folder")
    p.add_argument("-f", "--force", action="store_true",
                   help="overwrite existing local files")
    p.add_argument("-a", "--all", action="store_true",
                   help="include hidden entries when downloading a folder")
    p.set_defaults(handler=cmd_get)

    p = sub.add_parser("put", help="upload files or folders")
    _add_connection_options(p)
    p.add_argument("local", nargs="+", help="local path(s)")
    p.add_argument("-r", "--remote", help="target remote folder")
    p.add_argument("-f", "--force", action="store_true",
                   help="overwrite existing remote files")
    p.set_defaults(handler=cmd_put)

    p = sub.add_parser("mirror", help="download a tree into a local folder")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", help="remote folder (default: home)")
    p.add_argument("-d", "--dest", help="local folder (default: current)")
    p.add_argument("-f", "--force", action="store_true",
                   help="re-download files that already exist")
    p.add_argument("--delete", action="store_true",
                   help="remove local files that are gone from the server")
    p.add_argument("-a", "--all", action="store_true",
                   help="include hidden entries")
    p.add_argument("--pattern", help="glob filter, e.g. '*.log'")
    p.set_defaults(handler=cmd_mirror)

    p = sub.add_parser("tree", help="show the remote tree")
    _add_connection_options(p)
    p.add_argument("path", nargs="?")
    p.add_argument("-l", "--long", action="store_true", help="with sizes")
    p.add_argument("-a", "--all", action="store_true")
    p.add_argument("--max-depth", type=int, help="stop after N levels")
    p.set_defaults(handler=cmd_tree)

    p = sub.add_parser("mkdir", help="create remote folders")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True,
                   help="folder(s), comma separated")
    p.set_defaults(handler=cmd_mkdir)

    p = sub.add_parser("rm", help="delete remote paths")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True,
                   help="path(s), comma separated")
    p.add_argument("--recursive", action="store_true",
                   help="delete folders and their contents")
    p.set_defaults(handler=cmd_rm)

    p = sub.add_parser("rename", help="rename or move a remote path")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True, help="current path")
    p.add_argument("--to", required=True, help="new path")
    p.set_defaults(handler=cmd_rename)

    p = sub.add_parser("chmod", help="change remote permissions")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True)
    p.add_argument("mode", help="octal mode, e.g. 644")
    p.set_defaults(handler=cmd_chmod)

    p = sub.add_parser("cat", help="print a remote text file")
    _add_connection_options(p)
    p.add_argument("-r", "--remote", required=True)
    p.set_defaults(handler=cmd_cat)

    p = sub.add_parser("sites", help="list the saved connections")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_sites)

    p = sub.add_parser("selftest", help="report versions and locations")
    p.set_defaults(handler=cmd_selftest)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE

    report = Reporter(quiet=getattr(args, "quiet", False))
    handler = args.handler
    try:
        return handler(args, sys.stdout, report)
    except CliError as exc:
        report.error(str(exc))
        return EXIT_ERROR
    except KeyboardInterrupt:
        report.error("interrupted")
        return EXIT_ERROR
    except _session.SessionError as exc:
        report.error(_session.human_error(exc))
        return EXIT_ERROR
    except BrokenPipeError:
        return EXIT_OK


def entry() -> None:
    """Console-script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    entry()
