"""Walk a folder and collect file records.

Never follows symlinks or junctions (no loops, no wandering onto other drives),
skips protected folders, and counts unreadable entries instead of failing.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .errors import Cancelled, CleanerError, friendly_os_error
from .rules import Guard, default_guard

# Windows file attribute bits (st_file_attributes)
HIDDEN = 0x2
SYSTEM = 0x4
_ONLINE_ONLY = 0x1000 | 0x40000 | 0x400000   # offline, recall-on-open, recall-on-data-access (OneDrive etc.)

PROGRESS_EVERY = 0.1  # seconds between progress callbacks


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    size: int
    mtime_ns: int
    attrs: int = 0

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1].lower()

    @property
    def mtime(self) -> float:
        return self.mtime_ns / 1e9

    @property
    def hidden(self) -> bool:
        return bool(self.attrs & (HIDDEN | SYSTEM))

    @property
    def online_only(self) -> bool:
        """A cloud placeholder: reading it would download it."""
        return bool(self.attrs & _ONLINE_ONLY)


@dataclass
class ScanResult:
    root: str
    files: list[FileRecord] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)          # every folder read, root first
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    links_skipped: int = 0
    protected_skipped: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass(frozen=True)
class ScanProgress:
    files: int
    bytes: int
    folder: str


def record_for(entry: os.DirEntry) -> FileRecord:
    st = entry.stat(follow_symlinks=False)
    return FileRecord(entry.path, st.st_size, st.st_mtime_ns, getattr(st, "st_file_attributes", 0))


def _is_link(entry: os.DirEntry) -> bool:
    return entry.is_symlink() or entry.is_junction()


def scan(root: str, *, guard: Guard | None = None,
         progress: Callable[[ScanProgress], None] | None = None,
         cancel: threading.Event | None = None) -> ScanResult:
    """Every regular file under `root`. Raises CleanerError for a refused root, Cancelled on cancel."""
    guard = guard or default_guard()
    root = guard.check_root(root)
    started = last = time.monotonic()
    result = ScanResult(root=root)
    files, total, seen = result.files, 0, 0
    stack = [root]

    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Scan cancelled.")
        folder = stack.pop()
        try:
            it = os.scandir(folder)
        except OSError as exc:
            result.skipped.append((folder, friendly_os_error(exc)))
            continue
        result.folders.append(folder)
        subfolders = []
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as exc:  # the listing itself broke part-way
                    result.skipped.append((folder, friendly_os_error(exc)))
                    break
                try:
                    if _is_link(entry):
                        result.links_skipped += 1
                    elif entry.is_dir(follow_symlinks=False):
                        if guard.is_protected(entry.path):
                            result.protected_skipped.append(entry.path)
                        else:
                            subfolders.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        rec = record_for(entry)
                        files.append(rec)
                        total += rec.size
                except OSError as exc:
                    result.skipped.append((entry.path, friendly_os_error(exc)))

                seen += 1
                if seen & 255 == 0:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Scan cancelled.")
                    now = time.monotonic()
                    if progress is not None and now - last >= PROGRESS_EVERY:
                        last = now
                        progress(ScanProgress(len(files), total, folder))
        stack.extend(reversed(sorted(subfolders, key=str.lower)))

    result.seconds = time.monotonic() - started
    if progress is not None:
        progress(ScanProgress(len(files), total, root))
    return result


def top_level(root: str, *, guard: Guard | None = None) -> tuple[list[FileRecord], list[tuple[str, str]]]:
    """Files sitting directly in `root` (not in subfolders). Returns (records, skipped)."""
    guard = guard or default_guard()
    root = guard.check_root(root)
    records, skipped = [], []
    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if not _is_link(entry) and entry.is_file(follow_symlinks=False):
                        records.append(record_for(entry))
                except OSError as exc:
                    skipped.append((entry.path, friendly_os_error(exc)))
    except OSError as exc:
        raise CleanerError(f"Couldn't read that folder. {friendly_os_error(exc)}") from None
    records.sort(key=lambda r: r.name.lower())
    return records, skipped
