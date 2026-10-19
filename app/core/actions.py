"""Recycle and move files, with a JSON journal so moves can be undone.

Safety rules, enforced here for every file:
  * Nothing is permanently deleted. Deletes go through send2trash only, and a file is
    refused up front if Windows would delete it outright instead of recycling it
    (drive without a Recycle Bin, bin turned off, or file bigger than the bin).
  * Protected paths are refused.
  * A file that changed since it was scanned (size or modified time) is skipped.
  * Moves never overwrite: a clash gets a " (2)" suffix.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ..config import APP_NAME
from .errors import CleanerError, friendly_os_error
from .rules import Guard, default_guard
from .scan import FileRecord

FLUSH_EVERY = 25  # journal writes during long batches, so a crash still leaves an undo trail


# ---------- reports ----------
@dataclass
class Report:
    kind: str                                  # "recycle" | "move" | "undo"
    done: list[dict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (path, reason)
    cancelled: bool = False
    batch_id: str | None = None

    @property
    def bytes_done(self) -> int:
        return sum(item.get("size", 0) for item in self.done)

    @property
    def done_paths(self) -> set[str]:
        return {item["src"] for item in self.done}


@dataclass(frozen=True)
class ActionProgress:
    done: int
    total: int
    path: str


# ---------- journal ----------
def journal_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "journal.json"


class Journal:
    """Every batch the app has run, newest last. Stored as JSON in %APPDATA%."""

    KEEP = 300  # batches

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else journal_path()
        self.batches: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            batches = data.get("batches", [])
            return batches if isinstance(batches, list) else []
        except FileNotFoundError:
            return []
        except (OSError, ValueError, AttributeError):
            try:  # keep the damaged file for inspection rather than overwrite it
                os.rename(self.path, self.path.with_name(f"journal.damaged-{int(time.time())}.json"))
            except OSError:
                pass
            return []

    def save(self) -> None:
        self.batches = self.batches[-self.KEEP:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"version": 1, "batches": self.batches}, indent=1),
                                 encoding="utf-8")
        except OSError as exc:
            raise CleanerError(f"Couldn't save the history file at {self.path}. "
                               f"{friendly_os_error(exc)}") from None

    def start(self, kind: str, label: str, root: str) -> dict:
        batch = {"id": uuid.uuid4().hex[:12], "kind": kind, "label": label, "root": root,
                 "time": datetime.now().isoformat(timespec="seconds"),
                 "items": [], "skipped": [], "created_dirs": [], "undone": False, "finished": False}
        self.batches.append(batch)
        self.save()
        return batch

    def get(self, batch_id: str) -> dict:
        for b in self.batches:
            if b["id"] == batch_id:
                return b
        raise CleanerError("That entry is no longer in the history.")

    def newest_first(self) -> list[dict]:
        return list(reversed(self.batches))


# ---------- checks ----------
def stale_reason(rec: FileRecord) -> str | None:
    """Why `rec` must not be touched because it changed since the scan, or None if it's unchanged."""
    try:
        st = os.stat(rec.path, follow_symlinks=False)
    except FileNotFoundError:
        return "It's gone already (moved or deleted since the scan)."
    except OSError as exc:
        return friendly_os_error(exc)
    if not stat.S_ISREG(st.st_mode):
        return "It's no longer a regular file, so it was left alone."
    if st.st_size != rec.size or st.st_mtime_ns != rec.mtime_ns:
        return "It changed since the scan, so it was left alone. Scan again to include it."
    return None


# Recycle Bin capacity per volume, cached for one batch.
_bin_cache: dict[str, int | None] = {}

DRIVE_FIXED = 3


def _win_volume_guid(path: str) -> str | None:
    import ctypes
    k32 = ctypes.windll.kernel32
    mount = ctypes.create_unicode_buffer(1024)
    if not k32.GetVolumePathNameW(path, mount, 1024):
        return None
    name = ctypes.create_unicode_buffer(128)
    if not k32.GetVolumeNameForVolumeMountPointW(mount.value, name, 128):
        return None
    value = name.value  # \\?\Volume{guid}\
    start, end = value.find("{"), value.find("}")
    return value[start:end + 1] if start != -1 and end != -1 else None


def _win_reg_dword(hive, key: str, value: str) -> int | None:
    import winreg
    try:
        with winreg.OpenKey(hive, key) as k:
            data, kind = winreg.QueryValueEx(k, value)
            return int(data) if kind == winreg.REG_DWORD else None
    except OSError:
        return None


def _win_bin_limit(path: str) -> int | None:
    """Largest file (bytes) this volume's Recycle Bin accepts, or 0 if it deletes everything outright."""
    import winreg
    pol = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        if _win_reg_dword(hive, pol, "NoRecycleFiles") == 1:
            return 0
    guid = _win_volume_guid(path)
    bucket = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket"
    if guid:
        key = bucket + "\\Volume\\" + guid
        if _win_reg_dword(winreg.HKEY_CURRENT_USER, key, "NukeOnDelete") == 1:
            return 0
        mb = _win_reg_dword(winreg.HKEY_CURRENT_USER, key, "MaxCapacity")
        if mb:
            return mb * 1024 * 1024
    # Not configured yet: assume the smallest common Windows default (5% of the drive).
    import shutil
    try:
        return int(shutil.disk_usage(path).total * 0.05)
    except OSError:
        return None


def recycle_bin_problem(path: str, size: int) -> str | None:
    """Why Windows would permanently delete this file instead of recycling it, or None if it's safe."""
    if sys.platform != "win32":
        return None
    import ctypes
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") != DRIVE_FIXED:
        return ("It's on a USB stick or network drive, which has no Recycle Bin. "
                "MJC Folder Cleaner only deletes to the Recycle Bin, so it left this file alone.")
    key = drive.lower()
    if key not in _bin_cache:
        try:
            _bin_cache[key] = _win_bin_limit(path)
        except OSError:
            _bin_cache[key] = None
    limit = _bin_cache[key]
    if limit == 0:
        return ("The Recycle Bin is turned off for this drive, so Windows would delete it for good. "
                "Turn the Recycle Bin on (right-click it > Properties) and try again.")
    if limit is not None and size > limit:
        return ("It's bigger than this drive's Recycle Bin can hold, so Windows would delete it "
                "for good. Make the bin bigger (right-click it > Properties) or delete it yourself.")
    return None


def _default_trash(path: str) -> None:
    from send2trash import send2trash
    send2trash(path)


# ---------- recycle ----------
def recycle(records: Iterable[FileRecord], *, label: str, root: str,
            guard: Guard | None = None, journal: Journal | None = None,
            trash: Callable[[str], None] | None = None,
            bin_check: Callable[[str, int], str | None] | None = None,
            progress: Callable[[ActionProgress], None] | None = None,
            cancel: threading.Event | None = None) -> Report:
    """Send files to the Recycle Bin, one at a time, re-checking each first."""
    guard = guard or default_guard()
    journal = journal or Journal()
    trash = trash or _default_trash
    bin_check = bin_check or recycle_bin_problem
    _bin_cache.clear()
    records = list(records)
    report = Report("recycle")
    batch = journal.start("recycle", label, root)
    report.batch_id = batch["id"]

    for i, rec in enumerate(records):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        if progress is not None:
            progress(ActionProgress(i, len(records), rec.path))
        why = guard.reason(rec.path) or stale_reason(rec) or bin_check(rec.path, rec.size)
        if why is None:
            try:
                trash(rec.path)
            except OSError as exc:
                why = f"Couldn't send it to the Recycle Bin. {friendly_os_error(exc)}"
            except Exception as exc:  # send2trash raises its own types on some failures
                why = f"Couldn't send it to the Recycle Bin ({exc})."
            else:
                if os.path.lexists(rec.path):
                    why = "Windows didn't move it to the Recycle Bin. Try again, or delete it yourself."
        if why:
            report.skipped.append((rec.path, why))
            batch["skipped"].append([rec.path, why])
        else:
            item = {"src": rec.path, "size": rec.size}
            report.done.append(item)
            batch["items"].append(item)
        if (i + 1) % FLUSH_EVERY == 0:
            journal.save()

    batch["finished"] = True
    journal.save()
    return report


# ---------- move ----------
def unique_path(path: str, taken: set[str] | None = None) -> str:
    """`path`, or `name (2).ext`, `name (3).ext`... whichever is free on disk and not in `taken`."""
    taken = taken or set()
    folder, name = os.path.split(path)
    stem, ext = split_ext(name)
    candidate, n = path, 2
    while os.path.lexists(candidate) or os.path.normcase(candidate) in taken:
        candidate = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return candidate


_DOUBLE_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")


def split_ext(name: str) -> tuple[str, str]:
    low = name.lower()
    for ext in _DOUBLE_EXTS:
        if low.endswith(ext) and len(name) > len(ext):
            return name[: -len(ext)], name[-len(ext):]
    stem, ext = os.path.splitext(name)
    return stem, ext


def _make_dirs(folder: str, created: list[str]) -> None:
    missing = []
    probe = folder
    while not os.path.isdir(probe):
        missing.append(probe)
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    os.makedirs(folder, exist_ok=True)
    created.extend(reversed(missing))


def move(moves: Iterable[tuple[FileRecord, str]], *, label: str, root: str,
         guard: Guard | None = None, journal: Journal | None = None,
         progress: Callable[[ActionProgress], None] | None = None,
         cancel: threading.Event | None = None) -> Report:
    """Move each file to its destination. Never overwrites; never copies-then-deletes."""
    guard = guard or default_guard()
    journal = journal or Journal()
    moves = list(moves)
    report = Report("move")
    batch = journal.start("move", label, root)
    report.batch_id = batch["id"]

    for i, (rec, dst) in enumerate(moves):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        if progress is not None:
            progress(ActionProgress(i, len(moves), rec.path))
        why = guard.reason(rec.path) or guard.reason(dst) or stale_reason(rec)
        final = None
        if why is None:
            try:
                _make_dirs(os.path.dirname(dst), batch["created_dirs"])
                final = unique_path(dst)
                os.rename(rec.path, final)   # same-drive rename; fails rather than overwrite on Windows
            except OSError as exc:
                why = friendly_os_error(exc)
                if getattr(exc, "winerror", None) == 17:  # ERROR_NOT_SAME_DEVICE
                    why = "It can't be moved to another drive. Pick a folder on the same drive."
        if why:
            report.skipped.append((rec.path, why))
            batch["skipped"].append([rec.path, why])
        else:
            item = {"src": rec.path, "dst": final, "size": rec.size, "mtime_ns": rec.mtime_ns}
            report.done.append(item)
            batch["items"].append(item)
        if (i + 1) % FLUSH_EVERY == 0:
            journal.save()

    batch["finished"] = True
    journal.save()
    return report


# ---------- undo ----------
RECYCLE_UNDO_HELP = ("Files sent to the Recycle Bin can't be put back automatically. Open the "
                     "Recycle Bin, select them, then right-click and choose Restore.")


def undo(batch_id: str, *, journal: Journal | None = None, guard: Guard | None = None,
         progress: Callable[[ActionProgress], None] | None = None) -> Report:
    """Move every file in a move batch back where it came from (newest move first)."""
    guard = guard or default_guard()
    journal = journal or Journal()
    batch = journal.get(batch_id)
    if batch["kind"] == "recycle":
        raise CleanerError(RECYCLE_UNDO_HELP)
    if batch.get("undone"):
        raise CleanerError("That batch has already been undone.")

    report = Report("undo", batch_id=batch_id)
    items = list(reversed(batch["items"]))
    for i, item in enumerate(items):
        if progress is not None:
            progress(ActionProgress(i, len(items), item["dst"]))
        src, dst = item["src"], item["dst"]
        why = guard.reason(src) or guard.reason(dst)
        if why is None:
            rec = FileRecord(dst, item["size"], item.get("mtime_ns", 0))
            if not os.path.lexists(dst):
                why = "It's no longer where it was moved to, so it couldn't be put back."
            elif os.path.lexists(src):
                why = "Something new is already at its original spot, so it was left where it is."
            elif "mtime_ns" in item and stale_reason(rec):
                why = "It changed after it was moved, so it was left where it is."
        if why is None:
            try:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                os.rename(dst, src)
            except OSError as exc:
                why = friendly_os_error(exc)
        if why:
            report.skipped.append((dst, why))
        else:
            report.done.append({"src": dst, "dst": src, "size": item["size"]})

    # Tidy folders the batch created, but only if they're empty now (rmdir can't delete contents).
    for folder in reversed(batch.get("created_dirs", [])):
        try:
            os.rmdir(folder)
        except OSError:
            pass

    batch["undone"] = True
    batch["undone_at"] = datetime.now().isoformat(timespec="seconds")
    batch["undo_skipped"] = [list(s) for s in report.skipped]
    journal.save()
    return report
