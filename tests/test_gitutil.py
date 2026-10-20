import hashlib
import subprocess
from pathlib import Path

import pytest

from helpers import GitRepo
from stalecheck.gitutil import Git, GitError, TreeEntry, blob_sha, parse_git_version


def test_parses_git_versions() -> None:
    assert parse_git_version("git version 2.39.5 (Apple Git-154)") == (2, 39, 5)
    assert parse_git_version("git version 2.45.1.windows.1") == (2, 45, 1)
    with pytest.raises(GitError):
        parse_git_version("not git")


def test_rejects_old_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("stalecheck.gitutil._installed_git_version", lambda: (2, 33, 0))
    with pytest.raises(GitError, match="2.38"):
        Git(tmp_path)


def test_blob_sha_matches_git(tmp_path: Path) -> None:
    data = b"def f():\n    return 1\n"
    (tmp_path / "f.py").write_bytes(data)
    expected = subprocess.run(
        ["git", "hash-object", "f.py"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert blob_sha(data) == expected
    assert blob_sha(data) != hashlib.sha1(data).hexdigest()


def test_lists_tree_and_reads_blobs_in_bulk(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    commit = repo.commit({"b.py": "B = 1\n", "pkg/a.py": "A = 1\n", "pkg/c.txt": "x\n"})
    git = Git(repo.path)
    entries = git.ls_tree(commit)
    assert [e.path for e in entries] == ["b.py", "pkg/a.py", "pkg/c.txt"]
    assert all(isinstance(e, TreeEntry) and e.mode == "100644" for e in entries)
    blobs = git.read_blobs([e.sha for e in entries])
    assert blobs == {e.sha: (repo.path / e.path).read_bytes() for e in entries}


def test_read_blobs_handles_binary_and_empty_content(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    (repo.path / "bin.dat").write_bytes(b"\x00\n\xff\n")
    (repo.path / "empty.py").write_bytes(b"")
    commit = repo.commit({})
    git = Git(repo.path)
    blobs = git.read_blobs(e.sha for e in git.ls_tree(commit))
    assert sorted(blobs.values()) == [b"", b"\x00\n\xff\n"]


def test_read_blobs_rejects_missing_objects(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    repo.commit({"a.py": "A = 1\n"})
    with pytest.raises(GitError, match="missing"):
        Git(repo.path).read_blobs(["0" * 40])


def test_commit_shas_are_reproducible(tmp_path: Path) -> None:
    first = GitRepo(tmp_path / "one").commit({"a.py": "A = 1\n"})
    second = GitRepo(tmp_path / "two").commit({"a.py": "A = 1\n"})
    assert first == second


def test_rev_parse_and_merge_base(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    base = repo.commit({"a.py": "A = 1\n"})
    repo.git("checkout", "-q", "-b", "side")
    side = repo.commit({"b.py": "B = 1\n"})
    repo.git("checkout", "-q", "main")
    main = repo.commit({"a.py": "A = 2\n"})
    git = Git(repo.path)
    assert git.rev_parse("side") == side
    assert git.merge_base(main, side) == base
    with pytest.raises(GitError):
        git.rev_parse("no-such-branch")


def _diverge(
    repo: GitRepo, main_files: dict[str, str], side_files: dict[str, str]
) -> tuple[str, str]:
    repo.commit({"a.py": "A = 1\n\n\n\nB = 1\n"})
    repo.git("checkout", "-q", "-b", "side")
    side = repo.commit(side_files)
    repo.git("checkout", "-q", "main")
    return repo.commit(main_files), side


def test_merge_tree_clean(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    main, side = _diverge(repo, {"a.py": "A = 2\n\n\n\nB = 1\n"}, {"a.py": "A = 1\n\n\n\nB = 2\n"})
    result = Git(repo.path).merge_tree(main, side)
    assert not result.conflicted and result.conflicted_paths == ()
    assert result.tree is not None
    merged = Git(repo.path).read_blobs([Git(repo.path).ls_tree(result.tree)[0].sha])
    assert list(merged.values()) == [b"A = 2\n\n\n\nB = 2\n"]


def test_merge_tree_conflict(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    main, side = _diverge(repo, {"a.py": "A = 2\n\n\n\nB = 1\n"}, {"a.py": "A = 3\n\n\n\nB = 1\n"})
    result = Git(repo.path).merge_tree(main, side)
    assert result.conflicted and result.tree is None
    assert result.conflicted_paths == ("a.py",)


def test_commit_tree_and_compare_and_swap(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    main, side = _diverge(repo, {"a.py": "A = 2\n\n\n\nB = 1\n"}, {"a.py": "A = 1\n\n\n\nB = 2\n"})
    repo.git("checkout", "-q", "--detach")
    git = Git(repo.path)
    tree = git.merge_tree(main, side).tree
    assert tree is not None
    merge = git.commit_tree(tree, [main, side], "land side")
    assert repo.git("rev-list", "--parents", "-n1", merge).split() == [merge, main, side]
    assert not git.update_ref_cas("refs/heads/main", merge, expected_old=side)
    assert git.rev_parse("main") == main
    assert git.update_ref_cas("refs/heads/main", merge, expected_old=main)
    assert git.rev_parse("main") == merge


def test_worktrees_share_the_common_dir(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    base = repo.commit({"a.py": "A = 1\n"})
    git = Git(repo.path)
    wt = tmp_path / "wt"
    git.worktree_add(wt, branch="agent-a", start=base)
    assert git.rev_parse("agent-a") == base
    assert Git(wt).common_dir() == git.common_dir() == (repo.path / ".git").resolve()
    assert not Git(wt).is_dirty()
    (wt / "a.py").write_text("A = 2\n")
    assert Git(wt).is_dirty()
    git.worktree_remove(wt)
    assert not wt.exists()


def test_detached_worktree(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "repo")
    base = repo.commit({"a.py": "A = 1\n"})
    wt = tmp_path / "detached"
    git = Git(repo.path)
    git.worktree_add(wt, start=base)
    assert Git(wt).rev_parse("HEAD") == base
    git.worktree_remove(wt)
