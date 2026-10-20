"""The only module that talks to git. Every call shells out to the `git` binary."""

import functools
import hashlib
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

MIN_GIT_VERSION = (2, 38)  # `git merge-tree --write-tree`


class GitError(Exception):
    pass


@dataclass(frozen=True)
class TreeEntry:
    path: str  # repo-relative, posix
    mode: str
    sha: str


@dataclass(frozen=True)
class MergeResult:
    tree: str | None  # None when the merge has conflicts
    conflicted_paths: tuple[str, ...]

    @property
    def conflicted(self) -> bool:
        return self.tree is None


def parse_git_version(output: str) -> tuple[int, ...]:
    match = re.match(r"git version (\d+)\.(\d+)\.(\d+)", output.strip())
    if match is None:
        raise GitError(f"cannot parse git version from {output!r}")
    return tuple(int(part) for part in match.groups())


def blob_sha(data: bytes) -> str:
    """The SHA git would give `data` as a blob, so worktree files share the blob cache."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@functools.cache
def _installed_git_version() -> tuple[int, ...]:
    result = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True)
    return parse_git_version(result.stdout)


def _require_git_version() -> None:
    version = _installed_git_version()
    if version < MIN_GIT_VERSION:
        found = ".".join(map(str, version))
        need = ".".join(map(str, MIN_GIT_VERSION))
        raise GitError(f"stalecheck needs git >= {need}; found {found}")


class Git:
    """Git operations rooted at a repository or worktree directory."""

    def __init__(self, cwd: Path) -> None:
        _require_git_version()
        self.cwd = cwd

    def _run(
        self, *args: str, input: bytes | None = None, ok_codes: Sequence[int] = (0,)
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(["git", *args], cwd=self.cwd, input=input, capture_output=True)
        if result.returncode not in ok_codes:
            stderr = result.stderr.decode(errors="replace").strip()
            raise GitError(f"git {' '.join(args)} failed ({result.returncode}): {stderr}")
        return result

    def _out(self, *args: str) -> str:
        return self._run(*args).stdout.decode().strip()

    def rev_parse(self, rev: str) -> str:
        return self._out("rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}")

    def common_dir(self) -> Path:
        return (self.cwd / self._out("rev-parse", "--git-common-dir")).resolve()

    def merge_base(self, a: str, b: str) -> str:
        return self._out("merge-base", a, b)

    def ls_tree(self, treeish: str) -> tuple[TreeEntry, ...]:
        """Every blob in the tree, recursively, sorted by path. Submodules are skipped."""
        out = self._run("ls-tree", "-r", "-z", "--full-tree", treeish).stdout
        entries = []
        for record in out.split(b"\0"):
            if not record:
                continue
            meta, path = record.split(b"\t", 1)
            mode, kind, sha = meta.decode().split(" ")
            if kind == "blob":
                entries.append(TreeEntry(path=path.decode(), mode=mode, sha=sha))
        return tuple(sorted(entries, key=lambda e: e.path))

    def read_blobs(self, shas: Iterable[str]) -> dict[str, bytes]:
        """Read many blobs with a single `git cat-file --batch`."""
        wanted = sorted(set(shas))
        if not wanted:
            return {}
        out = self._run("cat-file", "--batch", input="\n".join(wanted).encode() + b"\n").stdout
        blobs: dict[str, bytes] = {}
        pos = 0
        for sha in wanted:
            end = out.index(b"\n", pos)
            header = out[pos:end].decode().split(" ")
            if header[-1] == "missing":
                raise GitError(f"blob {sha} is missing")
            size = int(header[2])
            blobs[sha] = out[end + 1 : end + 1 + size]
            pos = end + 1 + size + 1
        return blobs

    def merge_tree(self, ours: str, theirs: str) -> MergeResult:
        result = self._run(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--no-messages",
            ours,
            theirs,
            ok_codes=(0, 1),
        )
        lines = result.stdout.decode().splitlines()
        if result.returncode == 0:
            return MergeResult(tree=lines[0], conflicted_paths=())
        return MergeResult(tree=None, conflicted_paths=tuple(sorted(set(lines[1:]) - {""})))

    def commit_tree(self, tree: str, parents: Sequence[str], message: str) -> str:
        parent_args = [arg for parent in parents for arg in ("-p", parent)]
        return self._out("commit-tree", tree, *parent_args, "-m", message)

    def update_ref_cas(self, ref: str, new: str, expected_old: str) -> bool:
        """Atomically move ref to new if it still points at expected_old.

        Returns False when the ref has moved; raises GitError on any other failure.
        """
        result = self._run("update-ref", ref, new, expected_old, ok_codes=(0, 128))
        if result.returncode == 0:
            return True
        current = self._run("rev-parse", "--verify", "--quiet", ref, ok_codes=(0, 1))
        if current.stdout.decode().strip() != expected_old:
            return False
        raise GitError(f"update-ref {ref} failed: {result.stderr.decode(errors='replace')}")

    def worktree_add(self, path: Path, start: str, branch: str | None = None) -> None:
        """Add a worktree at path; on a new branch when given, otherwise detached."""
        target = ["-b", branch] if branch is not None else ["--detach"]
        self._run("worktree", "add", "-q", *target, str(path), start)

    def worktree_remove(self, path: Path) -> None:
        self._run("worktree", "remove", "--force", str(path))

    def is_dirty(self) -> bool:
        return bool(self._run("status", "--porcelain").stdout.strip())
