from pathlib import Path

import pytest
from typer.testing import CliRunner

from helpers import GitRepo
from stalecheck.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output


def test_init_creates_the_shared_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = GitRepo(tmp_path / "repo")
    repo.commit({"a.py": "A = 1\n"})
    monkeypatch.chdir(repo.path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (repo.path / ".git" / "stalecheck" / "db.sqlite").exists()
