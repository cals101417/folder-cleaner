import os
import re
import sys
from pathlib import Path

import pytest

from app.core import actions, organize
from app.core.errors import CleanerError
from app.core.rules import Guard, category_for
from tests.conftest import write

CORE = Path(__file__).resolve().parents[1] / "app" / "core"


@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "Downloads"
    write(d / "photo.jpg", "new photo", mtime=1_700_000_000)
    write(d / "PHOTO (2).JPG", "another", mtime=1_700_000_000)
    write(d / "report.pdf", "pdf")
    write(d / "setup.exe", "exe")
    write(d / "backup.tar.gz", "tgz")
    write(d / "mystery.xyz", "?")
    write(d / "movie.mp4.crdownload", "half a movie")
    write(d / "desktop.ini", "[.ShellClassInfo]")
    write(d / "Images" / "photo.jpg", "old photo already sorted")
    write(d / "Images" / "photo (2).jpg", "also already sorted")
    write(d / "Archives" / "backup.tar.gz", "older backup")
    write(d / "Projects" / "keep.txt", "subfolders are left alone")
    return d


def test_plan_by_type_resolves_name_clashes(downloads, guard):
    plan = organize.plan(str(downloads), "type", guard=guard)
    where = {m.rec.name: os.path.relpath(m.dst, downloads) for m in plan.moves}
    assert where == {
        "photo.jpg": os.path.join("Images", "photo (3).jpg"),
        "PHOTO (2).JPG": os.path.join("Images", "PHOTO (2) (2).JPG"),   # case-insensitive clash
        "report.pdf": os.path.join("Documents", "report.pdf"),
        "setup.exe": os.path.join("Installers", "setup.exe"),
        "backup.tar.gz": os.path.join("Archives", "backup (2).tar.gz"),
        "mystery.xyz": os.path.join("Other", "mystery.xyz"),
    }
    skipped = {os.path.basename(p): why for p, why in plan.skipped}
    assert "still in progress" in skipped["movie.mp4.crdownload"]
    assert "desktop.ini" in skipped
    assert plan.counts()["Images"] == 2


def test_plan_resolves_clashes_within_the_plan(tmp_path, guard):
    """Two sources heading for the same new name: the second gets " (2)" even though
    neither exists on disk yet."""
    from app.core.scan import scan
    d = tmp_path / "d"
    write(d / "one" / "a.txt", "1", mtime=1_700_000_000)
    write(d / "two" / "a.txt", "2", mtime=1_700_000_000)
    records = sorted(scan(str(d), guard=guard).files, key=lambda r: r.path)
    plan = organize.plan(str(d), "date", guard=guard, records=records)
    month = os.path.join(str(d), "2023-11")
    assert [m.dst for m in plan.moves] == [os.path.join(month, "a.txt"), os.path.join(month, "a (2).txt")]
    assert [m.renamed for m in plan.moves] == [False, True]


def test_plan_is_a_dry_run(downloads, guard):
    before = sorted(p.name for p in downloads.iterdir())
    organize.plan(str(downloads), "type", guard=guard)
    assert sorted(p.name for p in downloads.iterdir()) == before


def test_apply_then_undo(downloads, guard, journal):
    plan = organize.plan(str(downloads), "type", guard=guard)
    report = organize.apply(plan, guard=guard, journal=journal)
    assert len(report.done) == 6 and not report.skipped
    assert (downloads / "Images" / "photo (3).jpg").read_text() == "new photo"
    assert (downloads / "Images" / "photo.jpg").read_text() == "old photo already sorted"
    assert (downloads / "Other" / "mystery.xyz").exists()
    assert journal.batches[-1]["label"] == "Organize by type"

    actions.undo(report.batch_id, journal=journal, guard=guard)
    assert (downloads / "photo.jpg").read_text() == "new photo"
    assert (downloads / "backup.tar.gz").read_text() == "tgz"
    assert not (downloads / "Other").exists() and not (downloads / "Documents").exists()
    assert (downloads / "Images" / "photo.jpg").exists()   # pre-existing folders stay


def test_a_file_blocking_a_category_folder_is_skipped(tmp_path, guard):
    d = tmp_path / "d"
    write(d / "Images", "a file, not a folder")
    write(d / "cat.png", "meow")
    plan = organize.plan(str(d), "type", guard=guard)
    assert all(m.rec.name != "cat.png" for m in plan.moves)
    assert any("cat.png" in p and "Rename that file" in why for p, why in plan.skipped)


def test_categories():
    assert category_for(".JPG") == "Images"
    assert category_for(".msi") == "Installers"
    assert category_for(".weird") == "Other"


# ---------- protected paths ----------
def test_guard_rules(tmp_path):
    g = Guard(trees=[str(tmp_path / "Windows")], exact=[str(tmp_path / "home")],
              any_names={"settingsdata"}, top_names=set(), top_prefixes=())
    assert str(tmp_path / "Windows") in g.reason(str(tmp_path / "Windows" / "System32" / "x.dll"))
    assert g.reason(str(tmp_path / "home"))
    assert g.reason(str(tmp_path / "home" / "Documents")) is None
    assert g.reason(str(tmp_path / "other" / "SettingsData" / "Roaming"))
    assert g.reason(os.path.abspath(os.sep))   # a drive root
    with pytest.raises(CleanerError, match="whole drive"):
        g.check_root(os.path.abspath(os.sep))


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows paths")
@pytest.mark.parametrize("path", [
    r"C:\Windows", r"C:\Windows\System32", r"C:\Program Files", r"C:\Program Files (x86)\App",
    r"C:\ProgramData", r"C:\\", "~", "~/AppData", "~/AppData/Local/Temp", r"D:\Program Files\Steam",
])
def test_real_protected_paths_are_refused(path):
    g = Guard.from_environment()
    assert g.reason(os.path.expanduser(path)), path


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows paths")
def test_normal_user_folders_are_allowed():
    g = Guard.from_environment()
    for sub in ("Downloads", "Documents", "Pictures", r"Desktop\Old stuff"):
        assert g.reason(os.path.join(os.path.expanduser("~"), sub)) is None, sub


# ---------- the no-permanent-delete rule ----------
FORBIDDEN = [r"\bos\.remove\b", r"\bos\.unlink\b", r"\.unlink\(", r"\bshutil\.rmtree\b",
             r"\brmtree\b", r"\bshutil\.move\b", r"\bos\.replace\b", r"\bos\.removedirs\b",
             r"\bos\.truncate\b", r"\bshutil\.copy"]


def test_core_never_calls_permanent_delete():
    offenders = []
    for path in CORE.glob("*.py"):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            for pattern in FORBIDDEN:
                if re.search(pattern, code):
                    offenders.append(f"{path.name}:{no}: {line.strip()}")
    assert offenders == []


def test_only_actions_deletes_and_only_via_send2trash():
    for path in CORE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name != "actions.py":
            assert "send2trash" not in text and "rmdir" not in text, path.name
    text = (CORE / "actions.py").read_text(encoding="utf-8")
    assert text.count("os.rmdir(") == 1   # empty-folder tidy in undo; rmdir can't delete contents


def test_core_has_no_ui_imports():
    for path in CORE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(tkinter|customtkinter|tkinterdnd2)|\bfrom \.\.ui\b",
                             text, re.M), path.name
