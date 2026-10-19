"""Folder size tree and top-N largest files/folders."""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .scan import FileRecord, ScanResult


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@dataclass
class SizeTree:
    root: str
    total: dict[str, int] = field(default_factory=dict)      # folder -> bytes, including subfolders
    count: dict[str, int] = field(default_factory=dict)      # folder -> files, including subfolders
    children: dict[str, list[str]] = field(default_factory=dict)

    def size_of(self, folder: str) -> int:
        return self.total.get(folder, 0)


def build_tree(scan: ScanResult) -> SizeTree:
    tree = SizeTree(root=scan.root)
    total, count, children = tree.total, tree.count, tree.children
    for folder in scan.folders:
        total[folder] = 0
        count[folder] = 0
        children[folder] = []
    for rec in scan.files:
        folder = os.path.dirname(rec.path)
        if folder in total:
            total[folder] += rec.size
            count[folder] += 1
    # Children before parents: deepest folders first, then roll each one up into its parent.
    for folder in sorted(scan.folders, key=lambda f: f.count(os.sep), reverse=True):
        if folder == scan.root:
            continue
        parent = os.path.dirname(folder)
        if parent in total:
            total[parent] += total[folder]
            count[parent] += count[folder]
            children[parent].append(folder)
    return tree


def largest_files(files: Iterable[FileRecord], n: int = 20,
                  match: Callable[[FileRecord], bool] | None = None,
                  under: str | None = None) -> list[FileRecord]:
    if under is not None:
        prefix = under.rstrip(os.sep) + os.sep
        files = (f for f in files if f.path.startswith(prefix))
    if match is not None:
        files = (f for f in files if match(f))
    return heapq.nlargest(n, files, key=lambda f: f.size)


def largest_folders(tree: SizeTree, parent: str | None = None, n: int = 20) -> list[tuple[str, int, int]]:
    """The biggest direct subfolders of `parent` as (path, bytes, file_count)."""
    kids = tree.children.get(parent or tree.root, [])
    top = heapq.nlargest(n, kids, key=lambda f: tree.total.get(f, 0))
    return [(f, tree.total.get(f, 0), tree.count.get(f, 0)) for f in top]


def remove_files(scan: ScanResult, gone: set[str]) -> None:
    """Drop records that were recycled or moved so the views can refresh without a rescan."""
    if gone:
        scan.files = [f for f in scan.files if f.path not in gone]
