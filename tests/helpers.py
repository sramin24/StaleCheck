"""Shared test helpers. Repos live under pytest's tmp_path, never the developer's repo."""

import subprocess
from pathlib import Path


class GitRepo:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.path, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def write(self, files: dict[str, str]) -> None:
        for name, content in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

    def commit(self, files: dict[str, str], message: str = "change") -> str:
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")
