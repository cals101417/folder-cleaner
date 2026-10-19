import os

import pytest

from app.core import dupes
from app.core.errors import CleanerError
from app.core.scan import scan
from tests.conftest import write

KB = 1024


def names(group):
    return sorted(os.path.relpath(r.path, os.path.dirname(os.path.dirname(r.path))) for r in group.files)


def test_exact_duplicates_are_grouped(tmp_path, guard):
    body = os.urandom(200 * KB)
    write(tmp_path / "a" / "photo.jpg", body)
    write(tmp_path / "b" / "photo copy.jpg", body)
    write(tmp_path / "c" / "unique.jpg", os.urandom(200 * KB))
    result = dupes.find_duplicates(scan(str(tmp_path), guard=guard).files)
    assert len(result.groups) == 1
    assert sorted(r.name for r in result.groups[0].files) == ["photo copy.jpg", "photo.jpg"]
    assert result.wasted == 200 * KB


def test_same_size_different_content_is_not_a_duplicate(tmp_path, guard):
    write(tmp_path / "x.bin", b"A" * 5000)
    write(tmp_path / "y.bin", b"B" * 5000)
    assert dupes.find_duplicates(scan(str(tmp_path), guard=guard).files).groups == []


def test_files_that_differ_only_after_the_first_64kb_are_not_duplicates(tmp_path, guard):
    head = os.urandom(64 * KB)
    write(tmp_path / "one.iso", head + b"tail-one" * 1000)
    write(tmp_path / "two.iso", head + b"tail-two" * 1000)
    write(tmp_path / "three.iso", head + b"tail-one" * 1000)
    result = dupes.find_duplicates(scan(str(tmp_path), guard=guard).files)
    assert [sorted(r.name for r in g.files) for g in result.groups] == [["one.iso", "three.iso"]]


def test_zero_byte_files_are_skipped(tmp_path, guard):
    write(tmp_path / "empty1.txt", b"")
    write(tmp_path / "empty2.txt", b"")
    result = dupes.find_duplicates(scan(str(tmp_path), guard=guard).files)
    assert result.groups == [] and result.compared == 0


def test_small_identical_files_and_group_order(tmp_path, guard):
    write(tmp_path / "s1.txt", "same")
    write(tmp_path / "s2.txt", "same")
    write(tmp_path / "s3.txt", "same")
    big = os.urandom(300 * KB)
    write(tmp_path / "b1.bin", big)
    write(tmp_path / "b2.bin", big)
    groups = dupes.find_duplicates(scan(str(tmp_path), guard=guard).files).groups
    assert [len(g.files) for g in groups] == [2, 3]          # most reclaimable space first
    assert groups[1].wasted == 2 * 4


def test_unreadable_file_is_counted_not_fatal(tmp_path, guard, monkeypatch):
    write(tmp_path / "a.txt", "dup")
    write(tmp_path / "b.txt", "dup")
    write(tmp_path / "c.txt", "dup")
    files = scan(str(tmp_path), guard=guard).files
    real_hash = dupes._hash

    def flaky(path, *a, **kw):
        if path.endswith("c.txt"):
            raise PermissionError(13, "Access is denied")
        return real_hash(path, *a, **kw)

    monkeypatch.setattr(dupes, "_hash", flaky)
    result = dupes.find_duplicates(files)
    assert len(result.groups) == 1 and len(result.groups[0].files) == 2
    assert result.skipped[0][0].endswith("c.txt")


@pytest.fixture
def group(tmp_path, guard):
    write(tmp_path / "newest.txt", "dup", mtime=3_000_000)
    write(tmp_path / "deep" / "folder" / "oldest.txt", "dup", mtime=1_000_000)
    write(tmp_path / "mid.txt", "dup", mtime=2_000_000)
    return dupes.find_duplicates(scan(str(tmp_path), guard=guard).files).groups[0]


def test_keep_policies(group):
    assert dupes.keeper(group, "oldest").name == "oldest.txt"
    assert dupes.keeper(group, "newest").name == "newest.txt"
    assert dupes.keeper(group, "shortest").name == "mid.txt"
    marks = dupes.default_marks([group], "oldest")
    assert sorted(os.path.basename(p) for p in marks) == ["mid.txt", "newest.txt"]


def test_must_keep_at_least_one_copy(group):
    marks = dupes.default_marks([group], "oldest")
    keeper = dupes.keeper(group, "oldest").path
    assert not dupes.can_mark(group, marks, keeper)
    assert len(dupes.selected_for_removal([group], marks)) == 2
    with pytest.raises(CleanerError, match="Keep at least one copy"):
        dupes.selected_for_removal([group], marks | {keeper})
