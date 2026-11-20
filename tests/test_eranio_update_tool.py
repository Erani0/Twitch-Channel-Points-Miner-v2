import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INIT = "TwitchChannelPointsMiner/__init__.py"
BASE = "TwitchChannelPointsMiner/eranio/V3_BASE"
IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.org"]


def git(folder, *args):
    result = subprocess.run(
        ["git", *IDENTITY, *args],
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write(folder, name, text):
    path = Path(folder) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def repos(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git fehlt")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-b", "master")
    write(upstream, INIT, 'x = 1\n__version__ = "3.22.0"  # x-release-please-version\n')
    git(upstream, "add", "-A")
    git(upstream, "commit", "-m", "basis")
    first = git(upstream, "rev-parse", "--short=7", "HEAD")
    fork = tmp_path / "fork"
    git(tmp_path, "clone", str(upstream), "fork")
    write(fork, INIT, 'x = 1\n__version__ = "3.0.0"  # x-release-please-version\n')
    write(fork, BASE, f"3.22.0 {first}\n")
    write(
        fork,
        "tools/update_from_v3.py",
        (ROOT / "tools" / "update_from_v3.py").read_text(encoding="utf-8"),
    )
    git(fork, "add", "-A")
    git(fork, "commit", "-m", "eigene Version")
    git(fork, "remote", "add", "v3", str(upstream))
    write(upstream, INIT, 'x = 2\n__version__ = "3.23.0"  # x-release-please-version\n')
    write(upstream, "neu.txt", "neu\n")
    git(upstream, "add", "-A")
    git(upstream, "commit", "-m", "neue Funktion")
    return fork, upstream


def update(fork, *extra):
    return subprocess.run(
        [sys.executable, "tools/update_from_v3.py", "--no-tests", *extra],
        cwd=fork,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
        },
    )


def test_update_merges_into_its_own_branch_and_keeps_the_own_version(repos):
    fork, upstream = repos
    original = git(fork, "rev-parse", "--abbrev-ref", "HEAD")
    before = git(fork, "rev-parse", original)
    notes = fork.parent / "notes.txt"
    result = update(fork, "--notes-out", str(notes))
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(fork, "rev-parse", "--abbrev-ref", "HEAD") == "update/v3-3.23.0"
    assert "x = 2" in (fork / INIT).read_text(encoding="utf-8")
    assert '__version__ = "3.0.0"' in (fork / INIT).read_text(encoding="utf-8")
    assert (fork / "neu.txt").is_file()
    assert (fork / BASE).read_text(encoding="utf-8").startswith("3.23.0 ")
    assert "neue Funktion" in notes.read_text(encoding="utf-8")
    assert git(fork, "rev-parse", original) == before
    assert "Übernahme nach master" in result.stdout


def test_update_reports_an_up_to_date_base_and_refuses_a_dirty_tree(repos):
    fork, upstream = repos
    assert update(fork).returncode == 0
    again = update(fork)
    assert again.returncode == 3 and "aktuell" in again.stdout
    write(fork, "lose.txt", "x")
    assert update(fork).returncode == 2


def test_update_stops_on_conflicts_outside_the_version_line(repos):
    fork, upstream = repos
    write(fork, "neu.txt", "anders\n")
    git(fork, "add", "-A")
    git(fork, "commit", "-m", "eigene Datei")
    result = update(fork)
    assert result.returncode == 1 and "neu.txt" in result.stdout
    assert git(fork, "rev-parse", "--abbrev-ref", "HEAD") != "update/v3-3.23.0"
    assert git(fork, "branch", "--list", "update/*") == ""
