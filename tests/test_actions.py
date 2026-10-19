import os
import sys
import time

import pytest

from app.core import actions
from app.core.actions import Journal
from app.core.errors import CleanerError
from app.core.rules import Guard
from app.core.scan import scan
from tests.conftest import no_bin_problem, write


def recycle(records, guard, journal, trash, **kw):
    return actions.recycle(records, label="Test", root="", guard=guard, journal=journal,
                           trash=trash, bin_check=kw.pop("bin_check", no_bin_problem), **kw)


def test_recycle_sends_files_to_the_bin_and_journals_them(tmp_path, guard, journal, fake_bin):
    write(tmp_path / "data" / "a.txt", "aaa")
    write(tmp_path / "data" / "b.txt", "bb")
    files = scan(str(tmp_path / "data"), guard=guard).files
    report = recycle(files, guard, journal, fake_bin)
    assert report.bytes_done == 5 and not report.skipped
    assert not (tmp_path / "data" / "a.txt").exists()
    assert len(list(fake_bin.dir.iterdir())) == 2
    saved = Journal(journal.path).batches[-1]
    assert saved["kind"] == "recycle" and len(saved["items"]) == 2 and saved["finished"]


def test_stale_files_are_skipped_and_reported(tmp_path, guard, journal, fake_bin):
    changed = write(tmp_path / "data" / "changed.txt", "before")
    write(tmp_path / "data" / "gone.txt", "bye")
    keep = write(tmp_path / "data" / "fine.txt", "ok")
    files = {f.name: f for f in scan(str(tmp_path / "data"), guard=guard).files}
    changed.write_text("after, and longer")
    os.rename(tmp_path / "data" / "gone.txt", tmp_path / "moved.txt")
    report = recycle(files.values(), guard, journal, fake_bin)
    assert [os.path.basename(p) for p in report.done_paths] == ["fine.txt"]
    reasons = {os.path.basename(p): why for p, why in report.skipped}
    assert "changed since the scan" in reasons["changed.txt"]
    assert "gone already" in reasons["gone.txt"]
    assert changed.exists() and not keep.exists()


def test_same_size_but_touched_file_is_stale(tmp_path, guard, journal, fake_bin):
    path = write(tmp_path / "data" / "same.txt", "1234", mtime=1_000_000)
    files = scan(str(tmp_path / "data"), guard=guard).files
    path.write_text("5678")
    os.utime(path, (2_000_000, 2_000_000))
    report = recycle(files, guard, journal, fake_bin)
    assert not report.done and path.exists()


def test_protected_paths_are_refused(tmp_path, journal, fake_bin):
    write(tmp_path / "Windows" / "explorer.exe", "x")
    open_guard = Guard(trees=[], exact=[], any_names=set(), top_names=set(), top_prefixes=())
    files = scan(str(tmp_path / "Windows"), guard=open_guard).files
    strict = Guard(trees=[str(tmp_path / "Windows")], any_names=set(), top_names=set(), top_prefixes=())
    report = recycle(files, strict, journal, fake_bin)
    assert not report.done and "system folder" in report.skipped[0][1]
    assert (tmp_path / "Windows" / "explorer.exe").exists() and not fake_bin.calls


def test_files_windows_would_delete_for_good_are_refused(tmp_path, guard, journal, fake_bin):
    write(tmp_path / "data" / "huge.iso", "x")
    files = scan(str(tmp_path / "data"), guard=guard).files
    report = recycle(files, guard, journal, fake_bin, bin_check=lambda p, s: "too big for the bin")
    assert not report.done and report.skipped[0][1] == "too big for the bin"
    assert not fake_bin.calls


def test_trash_failure_is_reported_not_raised(tmp_path, guard, journal):
    write(tmp_path / "data" / "locked.txt", "x")
    files = scan(str(tmp_path / "data"), guard=guard).files

    def broken(path):
        raise OSError(32, "in use")

    report = recycle(files, guard, journal, broken)
    assert not report.done and "Recycle Bin" in report.skipped[0][1]


def test_move_never_overwrites_and_undo_puts_files_back(tmp_path, guard, journal):
    src = tmp_path / "data"
    write(src / "a.txt", "loose a")
    write(src / "b.txt", "loose b")
    write(src / "Sorted" / "a.txt", "already here")
    files = {f.name: f for f in scan(str(src), guard=guard).files if f.folder == str(src)}
    moves = [(files["a.txt"], str(src / "Sorted" / "a.txt")),
             (files["b.txt"], str(src / "New" / "Deep" / "b.txt"))]
    report = actions.move(moves, label="Test", root=str(src), guard=guard, journal=journal)
    assert not report.skipped
    assert (src / "Sorted" / "a.txt").read_text() == "already here"
    assert (src / "Sorted" / "a (2).txt").read_text() == "loose a"
    assert (src / "New" / "Deep" / "b.txt").exists()

    undo = actions.undo(report.batch_id, journal=Journal(journal.path), guard=guard)
    assert not undo.skipped and len(undo.done) == 2
    assert (src / "a.txt").read_text() == "loose a"
    assert (src / "b.txt").read_text() == "loose b"
    assert (src / "Sorted" / "a.txt").read_text() == "already here"
    assert not (src / "New").exists()          # folders the move created are tidied when empty
    assert Journal(journal.path).get(report.batch_id)["undone"]
    with pytest.raises(CleanerError, match="already been undone"):
        actions.undo(report.batch_id, journal=Journal(journal.path), guard=guard)


def test_undo_never_overwrites_a_new_file(tmp_path, guard, journal):
    src = tmp_path / "data"
    write(src / "a.txt", "original")
    rec = scan(str(src), guard=guard).files[0]
    report = actions.move([(rec, str(src / "Docs" / "a.txt"))], label="T", root=str(src),
                          guard=guard, journal=journal)
    write(src / "a.txt", "a new file with the same name")
    undo = actions.undo(report.batch_id, journal=journal, guard=guard)
    assert not undo.done and "original spot" in undo.skipped[0][1]
    assert (src / "a.txt").read_text() == "a new file with the same name"
    assert (src / "Docs" / "a.txt").read_text() == "original"


def test_move_skips_stale_files(tmp_path, guard, journal):
    path = write(tmp_path / "data" / "a.txt", "v1")
    rec = scan(str(tmp_path / "data"), guard=guard).files[0]
    path.write_text("version two")
    report = actions.move([(rec, str(tmp_path / "data" / "X" / "a.txt"))], label="T",
                          root="", guard=guard, journal=journal)
    assert not report.done and path.exists()


def test_recycle_batches_cannot_be_auto_undone(tmp_path, guard, journal, fake_bin):
    write(tmp_path / "data" / "a.txt")
    report = recycle(scan(str(tmp_path / "data"), guard=guard).files, guard, journal, fake_bin)
    with pytest.raises(CleanerError, match="Restore"):
        actions.undo(report.batch_id, journal=journal, guard=guard)


def test_damaged_journal_is_set_aside(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text("{not json")
    assert Journal(path).batches == []
    assert list(tmp_path.glob("journal.damaged-*.json"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin")
def test_real_recycle_bin(tmp_path, guard, journal):
    """One end-to-end run through send2trash and the capacity check (a 1-byte file)."""
    write(tmp_path / "data" / f"mjc-folder-cleaner-test-{time.time_ns()}.txt", "x")
    files = scan(str(tmp_path / "data"), guard=guard).files
    report = actions.recycle(files, label="Test", root="", guard=guard, journal=journal)
    assert len(report.done) == 1, report.skipped
    assert not os.path.exists(files[0].path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Recycle Bin")
def test_bin_check_refuses_files_bigger_than_the_bin(tmp_path):
    path = write(tmp_path / "x.bin", "x")
    assert actions.recycle_bin_problem(str(path), 1) is None
    assert "bigger than" in actions.recycle_bin_problem(str(path), 10 ** 15)
