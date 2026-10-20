"""Command-line interface."""

from pathlib import Path

import typer

from stalecheck.db import connect, db_path
from stalecheck.gitutil import Git

app = typer.Typer(no_args_is_help=True, help="Validate parallel agent work against stale reads.")


@app.callback()
def main() -> None:
    """stalecheck: optimistic concurrency control over code symbols."""


@app.command()
def init() -> None:
    """Create the stalecheck database for the current repository."""
    path = db_path(Git(Path.cwd()))
    connect(path).close()
    typer.echo(f"initialized {path}")
