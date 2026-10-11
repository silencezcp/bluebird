"""Background transfer queue.

A small pool of worker threads pulls :class:`~ftpclient.models.TransferItem`
objects out of the queue and runs them against a session.  How many may run at
once depends on the protocol, not just the preference:

* SFTP runs several at a time, each on its own channel of the one SSH
  connection;
* FTP runs exactly one, because its data connections are negotiated over a
  single control connection and concurrent transfers race for the data socket.
  That was measured: three of four parallel downloads came back truncated to
  64 KB with no error raised.  :attr:`~ftpclient.session.BaseSession
  .serial_transfers` says which applies.

No Qt widgets are touched from the worker threads: every result travels back
to the GUI thread through signals.
"""

from __future__ import annotations

import os
import posixpath
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from . import session as _session
from .core import Entry, TransferItem, format_size

#: transfers slower than this tick are still reported at least twice a second
REPORT_INTERVAL = 0.2

#: the largest number of simultaneous transfers the preference accepts
MAX_CONCURRENCY = 16


def describe_item(item: TransferItem) -> str:
    """The transfer pane's line for one item, as used in the log.

    The pane shows name, direction, size and status; the log keeps the same
    facts and adds both full paths, because that is what is needed to work out
    afterwards which file went where.  A single line, because the log folds
    multi-line messages onto one line anyway.
    """
    arrow = "->" if item.kind == "upload" else "<-"
    size = "folder" if item.is_dir else (
        format_size(int(item.size or 0)) or "unknown size")
    # source is always the local path for an upload and the remote path for a
    # download; target is the other end
    if item.kind == "upload":
        return "%s %s %s (%s)  local: %s  ->  remote: %s" % (
            item.kind.upper(), arrow, size, item.display_name,
            item.source, item.target)
    return "%s %s %s (%s)  remote: %s  ->  local: %s" % (
        item.kind.upper(), arrow, size, item.display_name,
        item.source, item.target)


def describe_result(item: TransferItem, elapsed: float) -> str:
    """How a finished transfer reads in the log."""
    if item.status == "done":
        done = int(item.transferred or item.size or 0)
        parts = [format_size(done) or "done"]
        if elapsed > 0.05:
            parts.append("%s/s" % (format_size(int(done / elapsed)) or "?"))
            parts.append("%.1f s" % elapsed)
        return ", ".join(parts)
    if item.status == "cancel":
        return "cancelled"
    return "failed"


class TransferWorker(QRunnable):
    """Runs a single :class:`TransferItem` to completion."""

    def __init__(self, manager: "TransferManager", item: TransferItem,
                 control: "_session.TransferControl") -> None:
        super(TransferWorker, self).__init__()
        self.manager = manager
        self.item = item
        self.control = control
        self.setAutoDelete(True)

    # -- progress -------------------------------------------------------
    def _progress(self, done: int, total: Optional[int]) -> None:
        item = self.item
        now = time.time()
        item.transferred = done
        if total:
            item.size = total
        elapsed = now - (item.started_at or now)
        if elapsed > 0.15:
            item.speed = done / elapsed
        if now - self.manager._last_report.get(item.uid, 0.0) >= REPORT_INTERVAL:
            self.manager._last_report[item.uid] = now
            self.manager.item_updated.emit(item.uid)

    # -- QRunnable ------------------------------------------------------
    def run(self) -> None:  # pragma: no cover - exercised via the GUI
        item = self.item
        manager = self.manager
        item.status = "active"
        item.started_at = time.time()
        item.speed = 0.0
        manager.item_updated.emit(item.uid)
        # the pane gains a row here, so the log gains a line: without this the
        # transfer list was visible on screen and nowhere on disk
        manager.log.emit("info", "Started: %s" % describe_item(item))
        try:
            if item.is_dir:
                self._run_directory()
            else:
                self._run_file()
            if item.status == "active":
                item.status = "done"
                item.transferred = item.size or item.transferred
            item.finished_at = time.time()
            item.speed = 0.0
        except _session.Cancelled:
            item.status = "cancel"
            item.message = "Cancelled"
            item.finished_at = time.time()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            item.status = "error"
            item.message = _session.human_error(exc)
            item.finished_at = time.time()
        finally:
            manager.item_updated.emit(item.uid)
            manager._worker_finished(item)

    # -- operations -----------------------------------------------------
    def _run_directory(self) -> None:
        item = self.item
        if item.kind == "upload":
            remote = item.target
            try:
                self.manager.session.mkdir(remote)
            except _session.SessionError:
                # already there (or the server hides it) - not fatal
                pass
        else:
            try:
                _session.ensure_local_dir(item.target)
            except _session.SessionError as exc:
                raise _session.SessionError(str(exc))
        item.transferred = 1
        item.size = 1
        self.manager.item_updated.emit(item.uid)

    def _run_file(self) -> None:
        item = self.item
        session = self.manager.session
        # Binary is the default; only an extension on the ASCII whitelist is
        # sent as text, because ASCII mode re-encodes line endings and must not
        # touch anything binary.
        session._set_transfer_type(self.manager.mode_for(item))
        if item.kind == "upload":
            if not os.path.isfile(item.source):
                raise _session.SessionError("Local file disappeared: %s" % item.source)
            session.upload_file(
                item.source, item.target, self._progress, self.control)
        else:
            _session.ensure_local_dir(os.path.dirname(item.target))
            session.download_file(
                item.source, item.target, self._progress, self.control)


class TransferManager(QObject):
    """Owns the queue, the worker pool and the pause/resume state."""

    item_updated = pyqtSignal(int)          # transfer uid
    item_added = pyqtSignal(int)
    item_finished = pyqtSignal(int)         # settled: done, error or skipped
    queue_changed = pyqtSignal()
    stats_changed = pyqtSignal()
    log = pyqtSignal(str, str)              # level, message
    all_finished = pyqtSignal()

    def __init__(self, session: _session.BaseSession, settings: Any,
                 parent: QObject = None) -> None:
        super(TransferManager, self).__init__(parent)
        self.session = session
        self.settings = settings
        self.items: List[TransferItem] = []
        self._controls: Dict[int, _session.TransferControl] = {}
        self._last_report: Dict[int, float] = {}
        self._lock = threading.RLock()
        self._active = 0
        self._paused = False
        self._stopped = False
        self._pool = QThreadPool(self)
        # the pool must be able to run everything the preference can ask for
        self._pool.setMaxThreadCount(MAX_CONCURRENCY)
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        self.total_bytes = 0
        self.done_bytes = 0

    # -- queue management ----------------------------------------------
    def concurrency(self) -> int:
        try:
            value = int(self.settings.get("transfers", "concurrency", 5) or 5)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(MAX_CONCURRENCY, value))

    def retries(self) -> int:
        try:
            return max(0, int(self.settings.get("transfers", "retries", 5) or 0))
        except (TypeError, ValueError):
            return 0

    def ascii_extensions(self) -> "set":
        """The extensions that may cross in ASCII mode, lower case, dotted."""
        raw = str(self.settings.get("transfers", "ascii_extensions", "") or "")
        out = set()
        for token in raw.replace(",", " ").split():
            token = token.strip().lower()
            if not token:
                continue
            if not token.startswith("."):
                token = "." + token
            out.add(token)
        return out

    def mode_for(self, item: Any) -> str:
        """``"ascii"`` for a whitelisted text extension, else ``"binary"``.

        Binary is the default on purpose: it is byte exact.  ASCII is only ever
        used for a file whose extension is on the list, because it re-encodes
        line endings.
        """
        if getattr(item, "is_dir", False):
            return "binary"
        name = str(getattr(item, "source", "") or getattr(item, "target", ""))
        lowered = name.lower()
        for extension in self.ascii_extensions():
            if lowered.endswith(extension):
                return "ascii"
        return "binary"

    def enqueue(self, items: List[TransferItem]) -> int:
        if not items:
            return 0
        with self._lock:
            for item in items:
                self.items.append(item)
                self.total_bytes += int(item.size or 0)
        for item in items:
            self.item_added.emit(item.uid)
        # everything the pane is about to show is written down as well, so a
        # batch is identifiable from the log alone.  Only the paths are
        # recorded; the outcome arrives when each file settles.
        for item in items:
            arrow = "->" if item.kind == "upload" else "<-"
            kind = "folder" if item.is_dir else (
                format_size(int(item.size or 0)) or "unknown size")
            self.log.emit("info", "Queued %s %s %s  (%s -> %s)"
                          % (item.kind, arrow, kind, item.source, item.target))
        self.queue_changed.emit()
        self.stats_changed.emit()
        return len(items)

    def clear_finished(self) -> None:
        with self._lock:
            keep = [i for i in self.items
                    if i.status in ("queued", "starting", "active")]
            removed = [i for i in self.items if i not in keep]
            self.items = keep
        for item in removed:
            self._last_report.pop(item.uid, None)
            self._controls.pop(item.uid, None)
        self.queue_changed.emit()
        self.stats_changed.emit()

    def clear_all(self) -> None:
        self.cancel_all()
        with self._lock:
            self.items = []
            self._controls.clear()
            self._last_report.clear()
            self.total_bytes = 0
            self.done_bytes = 0
        self.queue_changed.emit()
        self.stats_changed.emit()

    def remove(self, uids: List[int]) -> None:
        with self._lock:
            for uid in uids:
                control = self._controls.pop(uid, None)
                if control is not None:
                    control.cancel()
                self.items = [i for i in self.items if i.uid != uid]
                self._last_report.pop(uid, None)
        self.queue_changed.emit()
        self.stats_changed.emit()

    # -- transport control ---------------------------------------------
    def pause(self) -> None:
        self._paused = True
        with self._lock:
            for control in self._controls.values():
                control.pause()
        self.stats_changed.emit()

    def resume(self) -> None:
        self._paused = False
        with self._lock:
            for control in self._controls.values():
                control.resume()
        self.stats_changed.emit()

    @property
    def paused(self) -> bool:
        return self._paused

    def cancel(self, uid: int) -> None:
        cancelled_now = False
        with self._lock:
            control = self._controls.get(uid)
            item = self.item_by_id(uid)
            if control is not None:
                control.cancel()
            elif item is not None and item.status == "queued":
                item.status = "cancel"
                item.message = "Cancelled"
                cancelled_now = True
        self.item_updated.emit(uid)
        if cancelled_now:
            self.item_finished.emit(uid)
        self.stats_changed.emit()

    def cancel_all(self) -> None:
        cancelled: List[int] = []
        with self._lock:
            controls = list(self._controls.values())
            for item in self.items:
                if item.status == "queued":
                    item.status = "cancel"
                    item.message = "Cancelled"
                    cancelled.append(item.uid)
        for control in controls:
            control.cancel()
        self.queue_changed.emit()
        for uid in cancelled:
            self.item_finished.emit(uid)
        self.stats_changed.emit()

    def retry(self, uids: Optional[List[int]] = None) -> None:
        with self._lock:
            for item in self.items:
                if uids and item.uid not in uids:
                    continue
                if item.status in ("error", "cancel", "skipped"):
                    item.status = "queued"
                    item.message = ""
                    item.transferred = 0
                    item.speed = 0.0
        self.queue_changed.emit()
        self.stats_changed.emit()

    # -- introspection -------------------------------------------------
    def item_by_id(self, uid: int) -> Optional[TransferItem]:
        for item in self.items:
            if item.uid == uid:
                return item
        return None

    def pending(self) -> int:
        return sum(1 for i in self.items
                   if i.status in ("queued", "starting", "active"))

    def active(self) -> int:
        return sum(1 for i in self.items if i.status == "active")

    def failed(self) -> int:
        return sum(1 for i in self.items if i.status == "error")

    def done(self) -> int:
        return sum(1 for i in self.items if i.status == "done")

    def summary(self) -> str:
        from .i18n import T
        return T("%d queued / %d active / %d done / %d failed") % (
            sum(1 for i in self.items if i.status == "queued"),
            self.active(), self.done(), self.failed())

    # -- pump ----------------------------------------------------------
    def _pump(self) -> None:
        if self._stopped or self._paused:
            return
        limit = self.concurrency()
        # FTP cannot run two transfers at once on one control connection: they
        # race for the single data socket and the file arrives truncated with no
        # error.  The preference still applies to SFTP, which parallelises
        # safely, so the limit is clamped here rather than ignored by the GUI.
        if getattr(self.session, "serial_transfers", False):
            limit = 1
        started: List[Tuple[TransferItem, _session.TransferControl]] = []
        with self._lock:
            while self._active < limit:
                item = None
                for candidate in self.items:
                    if candidate.status == "queued":
                        item = candidate
                        break
                if item is None:
                    break
                # claim the item while still holding the lock so two pumps
                # (or a retry) can never pick the same item twice
                item.status = "starting"
                control = _session.TransferControl()
                if self._paused:
                    control.pause()
                self._controls[item.uid] = control
                self._active += 1
                started.append((item, control))
        for item, control in started:
            worker = TransferWorker(self, item, control)
            self._pool.start(worker)
        if started:
            self.queue_changed.emit()

    def _worker_finished(self, item: TransferItem) -> None:
        retry = False
        with self._lock:
            self._active = max(0, self._active - 1)
            self._controls.pop(item.uid, None)
            self._last_report.pop(item.uid, None)
            if item.status == "error" and item.retries < self.retries():
                item.retries += 1
                item.status = "queued"
                item.transferred = 0
                item.message = "retrying (%d)" % item.retries
                retry = True
            settled = not retry and item.status in ("done", "error", "skipped")
        self.item_updated.emit(item.uid)
        self.queue_changed.emit()
        self.stats_changed.emit()
        if retry:
            self.log.emit("warn", "Retrying (%d/%d) %s - %s"
                          % (item.retries, self.retries(),
                             item.display_name, item.message))
        elif item.status in ("done", "cancel", "error"):
            elapsed = (item.finished_at or 0.0) - (item.started_at or 0.0)
            level = {"done": "success", "cancel": "warn"}.get(
                item.status, "error")
            detail = describe_result(item, elapsed)
            if item.status == "error" and item.message:
                detail = "%s - %s" % (detail, item.message)
            self.log.emit(level, "%s %s - %s" % (
                {"done": "Finished", "cancel": "Cancelled"}.get(
                    item.status, "Failed"),
                item.display_name, detail))
        if settled:
            # reported only once the item will not be retried any more
            self.item_finished.emit(item.uid)
        if not retry and self.pending() == 0:
            self.all_finished.emit()

    def shutdown(self) -> None:
        self._stopped = True
        self._timer.stop()
        self.cancel_all()
        try:
            self._pool.waitForDone(4000)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Expanding a selection into queue items
# ---------------------------------------------------------------------------

def _remote_join(directory: str, name: str) -> str:
    base = (directory or "").rstrip("/")
    if not base:
        base = ""
    return (base + "/" + name) if base else name


def plan_downloads(session: _session.BaseSession, remote_dir: str,
                   entries: List[Entry], local_dir: str,
                   follow_symlinks: bool = False) -> List[TransferItem]:
    """Turn a remote selection into download queue items (recursive)."""
    items: List[TransferItem] = []
    for entry in entries:
        if entry.is_parent:
            continue
        if entry.name in (".", ".."):
            continue
        remote_path = _remote_join(remote_dir, entry.name)
        local_path = os.path.join(local_dir, entry.name)
        if entry.is_dir:
            items.append(TransferItem("download", remote_path, local_path,
                                      size=0, is_dir=True))
            if entry.is_link and not follow_symlinks:
                continue
            try:
                children = session.listdir(remote_path)
            except _session.SessionError:
                continue
            items.extend(plan_downloads(session, remote_path, children,
                                        local_path, follow_symlinks))
        else:
            items.append(TransferItem("download", remote_path, local_path,
                                      size=entry.size))
    return items


def plan_uploads(local_paths: List[str], remote_dir: str,
                 sizes: Optional[Dict[str, int]] = None) -> List[TransferItem]:
    """Turn local paths into upload queue items (recursive)."""
    items: List[TransferItem] = []
    for path in local_paths:
        items.extend(_plan_upload(path, remote_dir, sizes or {}))
    return items


def _plan_upload(path: str, remote_dir: str,
                 sizes: Dict[str, int]) -> List[TransferItem]:
    name = os.path.basename(path.rstrip("/\\")) or path
    target = _remote_join(remote_dir, name)
    if os.path.isdir(path):
        result = [TransferItem("upload", path, target, size=0, is_dir=True)]
        try:
            for child in sorted(os.listdir(path)):
                result.extend(_plan_upload(os.path.join(path, child), target, sizes))
        except OSError:
            pass
        return result
    size = sizes.get(path)
    if size is None:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
    return [TransferItem("upload", path, target, size=size)]
