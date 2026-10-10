"""Background transfer queue.

A small pool of worker threads pulls :class:`~ftpclient.models.TransferItem`
objects out of the queue and runs them against a session.  The session is
guarded by its own re-entrant lock, so several workers may share one
connection as long as the protocol tolerates it (SFTP does; FTP is serialised
by the queue's concurrency setting).

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
from .models import Entry, TransferItem

#: transfers slower than this tick are still reported at least twice a second
REPORT_INTERVAL = 0.2


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
        if item.kind == "upload":
            if not os.path.isfile(item.source):
                raise _session.SessionError("Local file disappeared: %s" % item.source)
            self.manager.session.upload_file(
                item.source, item.target, self._progress, self.control)
        else:
            _session.ensure_local_dir(os.path.dirname(item.target))
            self.manager.session.download_file(
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
        self._pool.setMaxThreadCount(4)
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._pump)
        self._timer.start()
        self.total_bytes = 0
        self.done_bytes = 0

    # -- queue management ----------------------------------------------
    def concurrency(self) -> int:
        try:
            value = int(self.settings.get("transfers", "concurrency", 2) or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(4, value))

    def retries(self) -> int:
        try:
            return max(0, int(self.settings.get("transfers", "retries", 2) or 0))
        except (TypeError, ValueError):
            return 0

    def enqueue(self, items: List[TransferItem]) -> int:
        if not items:
            return 0
        with self._lock:
            for item in items:
                self.items.append(item)
                self.total_bytes += int(item.size or 0)
        for item in items:
            self.item_added.emit(item.uid)
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
