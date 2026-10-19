"""What the app may touch (protected paths) and how results are filtered.

Protection is not user-overridable in v0.1. `Guard.from_environment()` builds the
real rules; tests build a `Guard` around a temp folder instead.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache

from .errors import CleanerError

# ---------- protected paths ----------
# Folder names that are off-limits wherever they appear.
ANY_LEVEL_NAMES = {"appdata", "$recycle.bin", "system volume information"}
# Folder names that are off-limits directly under a drive root (C:\Windows, D:\Program Files, ...).
TOP_LEVEL_NAMES = {"windows", "programdata"}
TOP_LEVEL_PREFIXES = ("program files",)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_drive_root(n: str) -> bool:
    return os.path.dirname(n) == n


@dataclass
class Guard:
    trees: list[str] = field(default_factory=list)      # off-limits along with everything inside
    exact: list[str] = field(default_factory=list)      # off-limits as a whole (e.g. the profile root)
    any_names: set[str] = field(default_factory=lambda: set(ANY_LEVEL_NAMES))
    top_names: set[str] = field(default_factory=lambda: set(TOP_LEVEL_NAMES))
    top_prefixes: tuple[str, ...] = TOP_LEVEL_PREFIXES
    drive_roots: bool = True

    def __post_init__(self):
        # (normalized for comparing, as written for messages)
        self._trees = [(_norm(t), os.path.normpath(t)) for t in self.trees if t]
        self._exact = {_norm(e) for e in self.exact if e}

    @classmethod
    def from_environment(cls) -> "Guard":
        env = os.environ.get
        trees = [env("SystemRoot"), env("windir"), env("ProgramFiles"), env("ProgramFiles(x86)"),
                 env("ProgramW6432"), env("ProgramData"), env("APPDATA"), env("LOCALAPPDATA")]
        home = os.path.expanduser("~")
        exact = [home, env("USERPROFILE"), os.path.dirname(home)]  # C:\Users\me and C:\Users
        if sys.platform == "win32":
            trees.append(r"C:\Windows")
        return cls(trees=[t for t in trees if t], exact=[e for e in exact if e])

    @staticmethod
    def _system(shown: str) -> str:
        return (f"{shown} is a system folder, so MJC Folder Cleaner never touches it. "
                "Pick a folder with your own files instead.")

    # A path inside a tree, or equal to an exact entry, is refused.
    def _reason_for(self, path: str) -> str | None:
        n = _norm(path)
        if self.drive_roots and _is_drive_root(n):
            return ("That's the top of a whole drive. Pick a folder on it instead, "
                    "like Downloads or Documents.")
        if n in self._exact:
            return ("That folder holds your whole user account. Pick a folder inside it instead, "
                    "like Downloads or Documents.")
        for t, shown in self._trees:
            if n == t or n.startswith(t.rstrip(os.sep) + os.sep):
                return self._system(shown)
        drive, rest = os.path.splitdrive(os.path.normpath(os.path.abspath(path)))
        parts = [p for p in rest.split(os.sep) if p]
        for i, part in enumerate(parts):
            low = part.lower()
            if low in self.any_names or (i == 0 and (low in self.top_names
                                                      or low.startswith(self.top_prefixes))):
                return self._system(drive + os.sep + os.sep.join(parts[: i + 1]))
        return None

    def reason(self, path: str) -> str | None:
        """Why `path` is off-limits, or None. Checks the path as given and with links resolved."""
        why = self._reason_for(path)
        if why:
            return why
        try:
            real = os.path.realpath(path)
        except (OSError, ValueError):
            return None
        return self._reason_for(real) if _norm(real) != _norm(path) else None

    def is_protected(self, path: str) -> bool:
        return self.reason(path) is not None

    def check_root(self, path: str) -> str:
        """Validate a folder the user picked. Returns it absolute, or raises CleanerError."""
        if not path:
            raise CleanerError("Pick a folder first.")
        path = os.path.abspath(path)
        why = self.reason(path)
        if why:
            raise CleanerError(why)
        if not os.path.isdir(path):
            raise CleanerError("That folder doesn't exist anymore. Pick another folder.")
        return path


@lru_cache(maxsize=1)
def default_guard() -> Guard:
    return Guard.from_environment()


# ---------- code projects ----------
# Files inside a code project belong to its tools: every project needs its own full copy, so
# "duplicate" files there aren't waste, and moving or recycling them breaks builds.
# Only strong markers count, so a stray requirements.txt in Downloads doesn't make it a project.
PROJECT_FILES = {".git", ".hg", ".svn", "package.json", "pyproject.toml", "cargo.toml", "go.mod",
                 "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "pubspec.yaml",
                 "deno.json", "angular.json"}
PROJECT_SUFFIXES = (".sln", ".csproj", ".vbproj", ".fsproj", ".vcxproj", ".xcodeproj", ".xcworkspace")
# Folders a developer tool fills and manages, wherever they appear.
MANAGED_DIRS = {"node_modules", ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "site-packages",
                ".tox", ".gradle", ".next", ".nuxt", ".angular", ".dart_tool", ".parcel-cache",
                "bower_components", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".terraform"}


def project_marker(names) -> str | None:
    """The first name in a folder listing that marks the folder as a code project, or None."""
    for name in names:
        low = name.lower()
        if low in PROJECT_FILES or low.endswith(PROJECT_SUFFIXES):
            return name
    return None


def is_managed_dir(name: str) -> bool:
    return name.lower() in MANAGED_DIRS


@dataclass(frozen=True)
class CodeProject:
    root: str
    marker: str        # e.g. "package.json", or "node_modules" for a managed folder
    managed: bool      # True when `root` is a tool-managed folder like node_modules

    def describe(self) -> str:
        if self.managed:
            return f"{self.marker} folder (managed by a developer tool)"
        return f"code project (it contains {self.marker})"


def enclosing_project(path: str) -> CodeProject | None:
    """The code project `path` is in (or is), looking at the path and its parent folders.

    Drive roots, the user folder and its parent are never treated as projects, so a stray
    package.json in C:\\Users\\me doesn't turn every file on the PC into "code".
    """
    home = os.path.expanduser("~")
    skip = {_norm(home), _norm(os.path.dirname(home))}
    probe = os.path.abspath(path)
    while True:
        n = _norm(probe)
        if _is_drive_root(n) or n in skip:
            return None
        name = os.path.basename(probe)
        if is_managed_dir(name):
            return CodeProject(probe, name, True)
        try:
            marker = project_marker(os.listdir(probe))
        except OSError:
            marker = None
        if marker:
            return CodeProject(probe, marker, False)
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent


# ---------- file types ----------
CATEGORIES: dict[str, set[str]] = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff",
               ".svg", ".ico", ".raw", ".cr2", ".nef", ".arw", ".dng", ".psd", ".avif"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".xls", ".xlsx", ".ods",
                  ".csv", ".ppt", ".pptx", ".odp", ".epub", ".pages", ".numbers", ".key", ".json",
                  ".xml", ".html", ".htm"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".zst", ".cab"},
    "Installers": {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".iso", ".img",
                   ".dmg", ".pkg", ".apk", ".bat", ".cmd", ".reg"},
    "Video": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v", ".flv", ".mpg", ".mpeg", ".3gp"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".mid"},
}
OTHER = "Other"
CATEGORY_NAMES = list(CATEGORIES) + [OTHER]
_EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


def category_for(ext: str) -> str:
    return _EXT_TO_CATEGORY.get(ext.lower(), OTHER)


# ---------- filters ----------
SECONDS_PER_MONTH = 30.4375 * 86400


@dataclass(frozen=True)
class Filters:
    min_mb: float | None = None
    older_than_months: float | None = None
    category: str | None = None   # one of CATEGORY_NAMES, or None for all types

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.min_mb, self.older_than_months, self.category))

    def matcher(self, now: float | None = None):
        """A fast predicate over FileRecords."""
        min_bytes = int(self.min_mb * 1024 * 1024) if self.min_mb is not None else None
        cutoff_ns = None
        if self.older_than_months is not None:
            cutoff_ns = int(((now or time.time()) - self.older_than_months * SECONDS_PER_MONTH) * 1e9)
        cat = self.category

        def match(rec) -> bool:
            if min_bytes is not None and rec.size <= min_bytes:
                return False
            if cutoff_ns is not None and rec.mtime_ns >= cutoff_ns:
                return False
            if cat is not None and category_for(rec.ext) != cat:
                return False
            return True

        return match


def parse_filters(min_mb: str, older_than_months: str, category: str | None) -> Filters:
    """Turn the Overview filter boxes into Filters. Blank boxes mean 'no limit'."""

    def number(text: str, what: str, example: str) -> float | None:
        text = (text or "").strip().replace(",", "")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            raise CleanerError(f"“{text}” isn't a number. Type {what}, like {example}, "
                               "or leave the box empty.") from None
        if value < 0:
            raise CleanerError(f"Use a positive number for {what}.")
        return value

    cat = category if category in CATEGORY_NAMES else None
    return Filters(number(min_mb, "a size in MB", "100"),
                   number(older_than_months, "a number of months", "12"), cat)
