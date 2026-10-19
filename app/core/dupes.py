"""Exact duplicate detection: same size, then same first 64 KB, then same full content.

Hashing uses BLAKE2b from the standard library. Zero-byte files are skipped, and
cloud placeholders (online-only files) are never read, so nothing gets downloaded.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .errors import Cancelled, CleanerError, friendly_os_error
from .scan import FileRecord

PARTIAL_BYTES = 64 * 1024
CHUNK = 1024 * 1024
QUICK_THREADS = 8   # stage 2 only; whole-file hashing stays sequential so spinning disks don't thrash


@dataclass
class DupeGroup:
    size: int
    files: list[FileRecord]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)


@dataclass
class DupeResult:
    groups: list[DupeGroup] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    online_only: int = 0
    compared: int = 0     # files that had at least one same-size partner
    in_projects: int = 0  # files left out because they belong to a code project
    too_small: int = 0    # files left out for being under min_size
    min_size: int = 1

    @property
    def wasted(self) -> int:
        return sum(g.wasted for g in self.groups)


@dataclass(frozen=True)
class DupeProgress:
    stage: str      # "quick" or "full"
    done: int       # files (quick) or bytes (full)
    total: int


def _hash(path: str, limit: int | None, cancel: threading.Event | None,
          tick: Callable[[int], None] | None = None) -> bytes:
    h = hashlib.blake2b(digest_size=20)
    remaining = limit
    with open(path, "rb", buffering=0) as fh:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Duplicate search cancelled.")
            want = CHUNK if remaining is None else min(CHUNK, remaining)
            if want <= 0:
                break
            data = fh.read(want)
            if not data:
                break
            h.update(data)
            if remaining is not None:
                remaining -= len(data)
            if tick is not None:
                tick(len(data))
    return h.digest()


def _regroup(groups: Iterable[list[FileRecord]], key: Callable[[FileRecord], bytes],
             skipped: list, threads: int = 1) -> list[list[FileRecord]]:
    """Split each group by `key`, keeping only buckets with 2+ files.

    With threads > 1 the keys are computed in parallel. Opening a file is the slow part on
    Windows (antivirus hooks), and it releases the GIL, so a few threads help a lot.
    """
    groups = list(groups)

    def safe_key(rec: FileRecord):
        try:
            return key(rec)
        except OSError as exc:
            return exc

    flat = [rec for g in groups for rec in g]
    if threads > 1 and len(flat) > 64:
        with ThreadPoolExecutor(threads) as pool:
            keys = list(pool.map(safe_key, flat, chunksize=32))
    else:
        keys = [safe_key(rec) for rec in flat]

    out, i = [], 0
    for group in groups:
        buckets: dict[bytes, list[FileRecord]] = defaultdict(list)
        for rec in group:
            k = keys[i]
            i += 1
            if isinstance(k, OSError):
                skipped.append((rec.path, friendly_os_error(k)))
            else:
                buckets[k].append(rec)
        out.extend(b for b in buckets.values() if len(b) > 1)
    return out


def find_duplicates(files: Iterable[FileRecord], *, min_size: int = 1,
                    progress: Callable[[DupeProgress], None] | None = None,
                    cancel: threading.Event | None = None) -> DupeResult:
    """Groups of identical files. Files inside code projects are never candidates: each
    project needs its own copy, so recycling one would break it."""
    result = DupeResult(min_size=max(1, min_size))

    # Stage 1: only same-size files can match.
    by_size: dict[int, list[FileRecord]] = defaultdict(list)
    for rec in files:
        if rec.size == 0:
            continue
        if rec.project:
            result.in_projects += 1
            continue
        if rec.size < result.min_size:
            result.too_small += 1
            continue
        if rec.online_only:
            result.online_only += 1
            continue
        by_size[rec.size].append(rec)
    candidates = [g for g in by_size.values() if len(g) > 1]
    result.compared = sum(len(g) for g in candidates)

    # Stage 2: hash the first 64 KB (in parallel; it's mostly file-open time).
    done = 0
    lock = threading.Lock()

    def quick(rec: FileRecord) -> bytes:
        nonlocal done
        digest = _hash(rec.path, PARTIAL_BYTES, cancel)
        with lock:
            done += 1
            report = done % 50 == 0
        if progress is not None and report:
            progress(DupeProgress("quick", done, result.compared))
        return digest

    groups = _regroup(candidates, quick, result.skipped, threads=QUICK_THREADS)

    # Stage 3: hash whole files, but only those bigger than what stage 2 already read.
    small = [g for g in groups if g[0].size <= PARTIAL_BYTES]
    large = [g for g in groups if g[0].size > PARTIAL_BYTES]
    total_bytes = sum(r.size for g in large for r in g)
    hashed = 0
    last_report = 0

    def tick(n: int) -> None:
        nonlocal hashed, last_report
        hashed += n
        if progress is not None and hashed - last_report >= 8 * CHUNK:
            last_report = hashed
            progress(DupeProgress("full", hashed, total_bytes))

    groups = small + _regroup(large, lambda r: _hash(r.path, None, cancel, tick), result.skipped)
    if progress is not None:
        progress(DupeProgress("full", total_bytes, total_bytes))

    result.groups = sorted((DupeGroup(g[0].size, sorted(g, key=lambda r: r.path.lower()))
                            for g in groups), key=lambda g: g.wasted, reverse=True)
    return result


# ---------- which copy to keep ----------
KEEP_POLICIES = {
    "oldest": ("Keep oldest", lambda r: (r.mtime_ns, len(r.path), r.path.lower())),
    "newest": ("Keep newest", lambda r: (-r.mtime_ns, len(r.path), r.path.lower())),
    "shortest": ("Keep shortest path", lambda r: (len(r.path), r.mtime_ns, r.path.lower())),
}


def keeper(group: DupeGroup, policy: str = "oldest") -> FileRecord:
    return min(group.files, key=KEEP_POLICIES[policy][1])


def default_marks(groups: Iterable[DupeGroup], policy: str = "oldest") -> set[str]:
    """Paths pre-selected for the Recycle Bin: every copy except the one the policy keeps."""
    marks = set()
    for g in groups:
        keep = keeper(g, policy)
        marks.update(r.path for r in g.files if r is not keep)
    return marks


def can_mark(group: DupeGroup, marks: set[str], path: str) -> bool:
    """True if marking `path` still leaves at least one copy in the group unmarked."""
    return sum(1 for r in group.files if r.path in marks or r.path == path) < len(group.files)


def selected_for_removal(groups: Iterable[DupeGroup], marks: set[str]) -> list[FileRecord]:
    """The marked files, refusing if any group would lose every copy."""
    chosen = []
    for g in groups:
        picked = [r for r in g.files if r.path in marks]
        if len(picked) >= len(g.files):
            raise CleanerError(f"Keep at least one copy of {g.files[0].name}. "
                               "Untick one of its copies and try again.")
        chosen.extend(picked)
    return chosen


def display_folder(path: str, root: str) -> str:
    rel = os.path.relpath(os.path.dirname(path), root)
    return "(top folder)" if rel == "." else rel
