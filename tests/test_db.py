from pathlib import Path

from helpers import GitRepo
from stalecheck.db import connect, db_path
from stalecheck.gitutil import Git

TABLES = {
    "blob_symbols",
    "blob_refs",
    "blob_imports",
    "snap_symbols",
    "snap_edges",
    "sessions",
    "reads",
    "validations",
}


def test_connect_creates_schema_in_wal_mode_with_busy_timeout(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "db.sqlite"
    conn = connect(path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == TABLES
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_connect_is_idempotent_and_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with connect(path) as conn:
        conn.execute("INSERT INTO sessions(id, name) VALUES ('s1', 'A')")
    assert connect(path).execute("SELECT name FROM sessions").fetchall() == [("A",)]


def test_db_lives_in_git_common_dir_shared_by_worktrees(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    base = repo.commit({"a.py": "A = 1\n"})
    Git(repo.path).worktree_add(tmp_path / "wt", start=base, branch="agent-a")
    expected = (repo.path / ".git" / "stalecheck" / "db.sqlite").resolve()
    assert db_path(Git(repo.path)) == db_path(Git(tmp_path / "wt")) == expected
