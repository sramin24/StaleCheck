import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_git_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Keep git away from the developer's config and make commit SHAs reproducible."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "stalecheck-test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@stalecheck.invalid")
        monkeypatch.setenv(f"GIT_{role}_DATE", "2026-01-01T00:00:00+0000")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "STALECHECK_SESSION"):
        monkeypatch.delenv(name, raising=False)
