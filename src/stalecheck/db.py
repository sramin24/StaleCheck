"""SQLite storage, shared by every worktree of a repository."""

import sqlite3
from pathlib import Path

from stalecheck.gitutil import Git

BUSY_TIMEOUT_MS = 30_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS blob_symbols(
  blob_sha TEXT, qname_local TEXT, kind TEXT,
  contract_hash TEXT, body_hash TEXT, start_byte INT, end_byte INT,
  PRIMARY KEY(blob_sha, qname_local));
CREATE TABLE IF NOT EXISTS blob_refs(
  blob_sha TEXT, caller_local TEXT, ref_text TEXT, ref_kind TEXT);
CREATE TABLE IF NOT EXISTS blob_imports(
  blob_sha TEXT, local_name TEXT, target_module TEXT, target_name TEXT);
CREATE TABLE IF NOT EXISTS snap_symbols(
  commit_sha TEXT, qname TEXT, kind TEXT, path TEXT,
  contract_hash TEXT, body_hash TEXT, PRIMARY KEY(commit_sha, qname));
CREATE TABLE IF NOT EXISTS snap_edges(
  commit_sha TEXT, caller TEXT, callee TEXT, ambiguous INT);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, name TEXT, base_commit TEXT, branch TEXT,
  worktree TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS reads(
  id INTEGER PRIMARY KEY, session_id TEXT, qname TEXT,
  kind TEXT,
  obs_contract_hash TEXT, obs_body_hash TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS validations(
  id INTEGER PRIMARY KEY, session_id TEXT, trunk_commit TEXT, head_commit TEXT,
  verdict TEXT, report_json TEXT, ts TEXT);
"""


def db_path(git: Git) -> Path:
    return git.common_dir() / "stalecheck" / "db.sqlite"


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database at path, in WAL mode with a busy timeout."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn
