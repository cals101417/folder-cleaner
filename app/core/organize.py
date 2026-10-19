"""Plan and apply "sort loose files into folders" for a messy folder like Downloads.

Planning is a dry run: nothing moves until `apply` is called with the plan the user saw.
Only files sitting directly in the folder are touched; subfolders are left as they are.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from . import actions
from .rules import Guard, category_for, default_guard
from .scan import FileRecord, top_level

MODES = {"type": "By type", "date": "By month"}

SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
# Downloads still in progress. Moving them would break the download.
PARTIAL_EXTS = {".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp", ".!ut", ".!qb"}


@dataclass(frozen=True)
class Move:
    rec: FileRecord
    dst: str
    folder: str       # the destination folder name, e.g. "Images" or "2026-10"
    renamed: bool     # got a " (2)" suffix to avoid a clash


@dataclass
class Plan:
    root: str
    mode: str
    moves: list[Move] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (path, reason)

    @property
    def total_bytes(self) -> int:
        return sum(m.rec.size for m in self.moves)

    def counts(self) -> Counter:
        return Counter(m.folder for m in self.moves)


def folder_for(rec: FileRecord, mode: str) -> str:
    if mode == "date":
        return time.strftime("%Y-%m", time.localtime(rec.mtime))
    return category_for(rec.ext)


def _skip_reason(rec: FileRecord) -> str | None:
    name = rec.name.lower()
    if name in SKIP_NAMES:
        return "Windows uses this file to set up the folder."
    if rec.ext in PARTIAL_EXTS:
        return "It looks like a download that's still in progress."
    if name.startswith("~$"):
        return "It's a temporary file from an open Office document."
    if rec.hidden:
        return "It's a hidden or system file."
    return None


def plan(root: str, mode: str = "type", *, guard: Guard | None = None,
         records: list[FileRecord] | None = None) -> Plan:
    """Where each loose file would go. Name clashes get " (2)", " (3)"... never an overwrite."""
    if mode not in MODES:
        raise ValueError(mode)
    guard = guard or default_guard()
    root = guard.check_root(root)
    skipped: list[tuple[str, str]] = []
    if records is None:
        records, skipped = top_level(root, guard=guard)
    result = Plan(root=root, mode=mode, skipped=list(skipped))
    taken: set[str] = set()   # destinations already claimed by this plan (normcased)

    for rec in records:
        why = _skip_reason(rec)
        folder = folder_for(rec, mode)
        target_dir = os.path.join(root, folder)
        if why is None and os.path.lexists(target_dir) and not os.path.isdir(target_dir):
            why = (f"There's a file called “{folder}” where that folder should go. "
                   "Rename that file, then preview again.")
        if why:
            result.skipped.append((rec.path, why))
            continue
        wanted = os.path.join(target_dir, rec.name)
        dst = actions.unique_path(wanted, taken)
        taken.add(os.path.normcase(dst))
        result.moves.append(Move(rec, dst, folder, renamed=dst != wanted))
    return result


def apply(p: Plan, *, guard: Guard | None = None, journal: actions.Journal | None = None,
          progress: Callable[[actions.ActionProgress], None] | None = None,
          cancel: threading.Event | None = None) -> actions.Report:
    label = f"Organize {MODES[p.mode].lower()}"
    return actions.move([(m.rec, m.dst) for m in p.moves], label=label, root=p.root,
                        guard=guard, journal=journal, progress=progress, cancel=cancel)
