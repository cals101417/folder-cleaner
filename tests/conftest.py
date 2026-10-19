import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.actions import Journal  # noqa: E402
from app.core.rules import Guard  # noqa: E402


def write(path: Path, data: bytes | str = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def guard(tmp_path) -> Guard:
    """Real rules, but scoped to the temp folder (which itself lives under AppData on Windows)."""
    return Guard(trees=[str(tmp_path / "Windows")], exact=[str(tmp_path / "home")],
                 any_names={"$recycle.bin"}, top_names=set(), top_prefixes=())


@pytest.fixture
def journal(tmp_path) -> Journal:
    return Journal(tmp_path / "state" / "journal.json")


@pytest.fixture
def fake_bin(tmp_path):
    """Stands in for send2trash: moves the file into tmp/bin so tests never touch the real bin."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = []

    def trash(path: str) -> None:
        calls.append(path)
        os.rename(path, bin_dir / f"{len(calls)}-{os.path.basename(path)}")

    trash.calls = calls
    trash.dir = bin_dir
    return trash


def no_bin_problem(path: str, size: int):
    return None
