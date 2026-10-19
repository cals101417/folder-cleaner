import os
import sys
import threading

import pytest

from app.core.errors import Cancelled, CleanerError
from app.core.scan import scan, top_level
from app.core.sizes import build_tree, human_size, largest_files, largest_folders, remove_files
from app.core.rules import parse_filters
from tests.conftest import write


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    write(root / "a.txt", b"a" * 10)
    write(root / "big" / "movie.mp4", b"m" * 5000)
    write(root / "big" / "deeper" / "clip.mp4", b"c" * 3000)
    write(root / "small" / "note.txt", b"n" * 100)
    write(root / "small" / "empty.txt", b"")
    return root


def test_scan_collects_every_file(tree, guard):
    result = scan(str(tree), guard=guard)
    names = sorted(f.name for f in result.files)
    assert names == ["a.txt", "clip.mp4", "empty.txt", "movie.mp4", "note.txt"]
    assert result.total_size == 10 + 5000 + 3000 + 100
    assert result.root == str(tree)
    assert {os.path.basename(f) for f in result.folders} == {"data", "big", "deeper", "small"}


def test_size_tree_and_top_lists(tree, guard):
    result = scan(str(tree), guard=guard)
    t = build_tree(result)
    assert t.total[str(tree)] == 8110
    assert t.total[str(tree / "big")] == 8000
    assert t.count[str(tree / "big")] == 2
    top = largest_folders(t)
    assert [os.path.basename(p) for p, _s, _c in top] == ["big", "small"]
    assert [os.path.basename(p) for p, _s, _c in largest_folders(t, str(tree / "big"))] == ["deeper"]
    assert [f.name for f in largest_files(result.files, 2)] == ["movie.mp4", "clip.mp4"]
    assert [f.name for f in largest_files(result.files, 5, under=str(tree / "small"))] == ["note.txt", "empty.txt"]


def test_filters(tree, guard):
    old = 1_500_000_000  # 2017
    os.utime(tree / "a.txt", (old, old))
    files = scan(str(tree), guard=guard).files
    by_type = parse_filters("", "", "Video").matcher()
    assert sorted(f.name for f in files if by_type(f)) == ["clip.mp4", "movie.mp4"]
    older = parse_filters("", "12", None).matcher()
    assert [f.name for f in files if older(f)] == ["a.txt"]
    bigger = parse_filters("0.004", "", None).matcher()   # ~4 KB
    assert [f.name for f in files if bigger(f)] == ["movie.mp4"]
    with pytest.raises(CleanerError, match="isn't a number"):
        parse_filters("lots", "", None)


def test_remove_files_updates_totals(tree, guard):
    result = scan(str(tree), guard=guard)
    remove_files(result, {str(tree / "big" / "movie.mp4")})
    assert build_tree(result).total[str(tree / "big")] == 3000


def test_scan_refuses_protected_root(tmp_path, guard):
    (tmp_path / "Windows").mkdir()
    with pytest.raises(CleanerError, match="system folder"):
        scan(str(tmp_path / "Windows"), guard=guard)
    (tmp_path / "home").mkdir()
    with pytest.raises(CleanerError, match="whole user account"):
        scan(str(tmp_path / "home"), guard=guard)


def test_scan_skips_protected_subfolders(tmp_path, guard):
    write(tmp_path / "Windows" / "system.dll")
    write(tmp_path / "mine.txt")
    result = scan(str(tmp_path), guard=guard)
    assert [f.name for f in result.files] == ["mine.txt"]
    assert result.protected_skipped == [str(tmp_path / "Windows")]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_scan_never_follows_junctions(tmp_path, guard):
    import _winapi
    elsewhere = tmp_path / "elsewhere"
    write(elsewhere / "far.txt")
    root = tmp_path / "root"
    write(root / "here.txt")
    _winapi.CreateJunction(str(elsewhere), str(root / "jump"))
    _winapi.CreateJunction(str(root), str(root / "loop"))   # would recurse forever if followed
    result = scan(str(root), guard=guard)
    assert [f.name for f in result.files] == ["here.txt"]
    assert result.links_skipped == 2


def test_scan_never_follows_symlinks(tmp_path, guard):
    write(tmp_path / "target" / "far.txt")
    root = tmp_path / "root"
    write(root / "here.txt")
    try:
        os.symlink(tmp_path / "target", root / "dirlink", target_is_directory=True)
        os.symlink(tmp_path / "target" / "far.txt", root / "filelink.txt")
    except OSError:
        pytest.skip("creating symlinks needs Developer Mode or admin on Windows")
    result = scan(str(root), guard=guard)
    assert [f.name for f in result.files] == ["here.txt"]
    assert result.links_skipped == 2


def test_scan_counts_unreadable_folders(tree, guard, monkeypatch):
    real = os.scandir
    locked = str(tree / "small")

    def flaky(path):
        if str(path) == locked:
            raise PermissionError(13, "Access is denied")
        return real(path)

    monkeypatch.setattr("app.core.scan.os.scandir", flaky)
    result = scan(str(tree), guard=guard)
    assert len(result.files) == 3
    assert result.skipped[0][0] == locked
    assert "wouldn't allow access" in result.skipped[0][1]


def test_scan_cancels(tmp_path, guard):
    for i in range(600):
        write(tmp_path / f"d{i % 30}" / f"f{i}.bin")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        scan(str(tmp_path), guard=guard, cancel=cancel)


def test_scan_cancels_mid_way_from_progress(tmp_path, guard, monkeypatch):
    monkeypatch.setattr("app.core.scan.PROGRESS_EVERY", 0)
    for i in range(2000):
        write(tmp_path / f"d{i % 10}" / f"f{i}.bin")
    cancel = threading.Event()
    seen = []

    def progress(p):
        seen.append(p.files)
        cancel.set()

    with pytest.raises(Cancelled):
        scan(str(tmp_path), guard=guard, progress=progress, cancel=cancel)
    assert seen and seen[0] < 2000


def test_top_level_only_lists_loose_files(tree, guard):
    records, skipped = top_level(str(tree), guard=guard)
    assert [r.name for r in records] == ["a.txt"]
    assert skipped == []


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024 ** 3) == "5.0 GB"
    assert human_size(3 * 1024 ** 4) == "3072.0 GB"
