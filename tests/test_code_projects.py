"""Code projects (repos, node_modules, venvs) are left alone by Duplicates and Organize."""

import os

import pytest

from app.core import dupes, organize
from app.core.errors import CleanerError
from app.core.rules import enclosing_project, project_marker
from app.core.scan import scan
from tests.conftest import write

SAME = b"identical bytes " * 100


@pytest.fixture
def documents(tmp_path):
    d = tmp_path / "Documents"
    # a JS project with its own node_modules
    write(d / "Projects" / "shop" / "package.json", "{}")
    write(d / "Projects" / "shop" / "src" / "util.js", SAME)
    write(d / "Projects" / "shop" / "node_modules" / "ajv" / "errors.js", SAME)
    # a second project with the same file
    write(d / "Projects" / "blog" / ".git" / "HEAD", "ref: refs/heads/main")
    write(d / "Projects" / "blog" / "lib" / "util.js", SAME)
    # a stray node_modules and venv outside any project
    write(d / "old-stuff" / "node_modules" / "x" / "errors.js", SAME)
    write(d / "old-stuff" / ".venv" / "Lib" / "site.py", SAME)
    # ordinary personal files: these are real duplicates
    write(d / "notes.txt", SAME)
    write(d / "Backup" / "notes.txt", SAME)
    return d


def test_scan_finds_projects_and_tags_their_files(documents, guard):
    result = scan(str(documents), guard=guard)
    roots = {os.path.relpath(p, documents): pr.marker for p, pr in result.projects.items()}
    assert roots == {
        os.path.join("Projects", "shop"): "package.json",
        os.path.join("Projects", "blog"): ".git",
        os.path.join("old-stuff", "node_modules"): "node_modules",
        os.path.join("old-stuff", ".venv"): ".venv",
    }
    tagged = {os.path.relpath(f.path, documents): bool(f.project) for f in result.files}
    assert tagged[os.path.join("Projects", "shop", "node_modules", "ajv", "errors.js")]
    assert tagged[os.path.join("Projects", "blog", "lib", "util.js")]
    assert not tagged["notes.txt"] and not tagged[os.path.join("Backup", "notes.txt")]
    assert result.project_of(str(documents / "Projects" / "shop" / "src")).marker == "package.json"
    assert result.project_of(str(documents / "Backup")) is None


def test_duplicates_ignore_files_in_code_projects(documents, guard):
    result = dupes.find_duplicates(scan(str(documents), guard=guard).files)
    assert [sorted(r.name for r in g.files) for g in result.groups] == [["notes.txt", "notes.txt"]]
    assert result.in_projects == 7   # every file under the four project roots, markers included


def test_scanning_inside_a_project_treats_everything_as_code(documents, guard):
    result = scan(str(documents / "Projects" / "shop" / "src"), guard=guard)
    assert all(f.project for f in result.files)
    assert dupes.find_duplicates(result.files).groups == []


def test_duplicates_skip_small_files(tmp_path, guard):
    write(tmp_path / "a.bin", b"x" * 500)
    write(tmp_path / "b.bin", b"x" * 500)
    write(tmp_path / "c.bin", b"y" * 5000)
    write(tmp_path / "d.bin", b"y" * 5000)
    files = scan(str(tmp_path), guard=guard).files
    result = dupes.find_duplicates(files, min_size=1000)
    assert [sorted(r.name for r in g.files) for g in result.groups] == [["c.bin", "d.bin"]]
    assert result.too_small == 2
    assert len(dupes.find_duplicates(files).groups) == 2


def test_organize_refuses_a_project_folder(documents, guard):
    with pytest.raises(CleanerError, match="code project .*package.json"):
        organize.plan(str(documents / "Projects" / "shop"), guard=guard)
    with pytest.raises(CleanerError, match="inside shop"):
        organize.plan(str(documents / "Projects" / "shop" / "src"), guard=guard)
    with pytest.raises(CleanerError, match="node_modules folder"):
        organize.plan(str(documents / "old-stuff" / "node_modules"), guard=guard)
    organize.plan(str(documents / "Backup"), guard=guard)   # ordinary folders are fine


def test_weak_markers_do_not_make_a_project(tmp_path):
    write(tmp_path / "Downloads" / "requirements.txt", "requests")
    write(tmp_path / "Downloads" / "setup.py", "")
    assert enclosing_project(str(tmp_path / "Downloads")) is None
    assert project_marker(["App.sln", "readme.md"]) == "App.sln"
