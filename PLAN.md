# PLAN.md: stalecheck

# Progress (agent: update after every milestone, commit with the code)

- [x] Day 1: foundations
- [ ] Day 2: snapshots and call graph
- [ ] Day 3: sessions and MCP read tracking
- [ ] Day 4: validation engine
- [ ] Day 5: landing and benchmark generator
- [ ] Day 6: baselines and results
- [ ] Day 7: polish and write-up

Current milestone notes / blockers:
- Day 1 done. Local git must be >= 2.38 (Apple git 2.39.5 is fine; an old /usr/local/bin/git 2.33 was shadowing it).
- Candidate revisions, decided 2026-10-19 to MEASURE FIRST and revise only if Day 6 numbers say so:
  1. Landing order: stalecheck is asymmetric (e.g. template 3 passes when A lands second, since R5 needs
     contract_changed). Evaluate every instance in both landing orders and report both.
  2. A body-only analog of R5 (call it R6, SUSPECT). Decide from the both-orders numbers.
  3. Class body_hash includes method bodies, so different-method edits in one class can fire R1;
     class contract includes public member names, so adding a method changes it. Make sure template 7
     sometimes uses methods of one class, so this is measured.
  4. Inferred reads via ambiguous (fan-out) edges are treated as direct; R5 over an ambiguous edge blocks.
  5. `Cls(...)` gives no edge to `Cls.__init__`, so constructor signature changes are invisible.
- Must resolve before Day 6 (benchmark validity, not a design tweak): strategy (f)'s test oracle must not be
  the hidden ground-truth suite, or (f) is perfect by construction. Plan: a separate visible suite per repo.

---

## 0. Rules for the coding agent

You are building `stalecheck`, a local, free, deterministic CLI and MCP server
that validates parallel AI-agent work at commit time using optimistic
concurrency control (OCC) over code symbols. It catches changes that
`git merge` accepts but that were built on stale reads.

- No LLM calls and no network access anywhere in the project. The benchmark
  uses scripted fake agents.
- Keep core logic (hashing, diffing, resolution, validation) as pure functions,
  separate from I/O. Write tests alongside each module.
- Commit after each milestone with `make check` green.
- Do not expand scope beyond the milestones. If something is ambiguous, pick
  the simplest option and append one line to `docs/decisions.md`.
- Do not guess library APIs. Pin `mcp` to the 1.x line (the MCP spec changed in
  July 2026), and read the installed tree-sitter and mcp docs or `help()`
  before writing code against them.
- Every claim in the README must be backed by a number produced by `make bench`.

## 1. Problem and thesis

Git compares what each branch *wrote*. It never compares what each branch
*depended on*.

Example. Two agents branch from the same commit.
- Agent A changes `apply_discount` in `pricing.py` from percent semantics
  (`price * (1 - pct/100)`) to fraction semantics (`price * (1 - pct)`).
- Agent B, working from the old version, adds `bulk_total()` in `bulk.py`
  calling `apply_discount(price, 15)`.

The diffs touch different files, so `git merge` reports no conflicts. The merged
code applies a 1400% discount. B's work was correct against the world it read,
and A changed that world while B worked. That is a stale read.

Thesis: model each agent session as a database transaction.
- **Read-set:** symbols the agent looked at, with the content hashes it observed.
- **Write-set:** symbols the agent changed, derived from a symbol-level diff.
- **Backward validation:** before landing, check that nothing in the read-set
  changed on trunk after the agent observed it. Land with an atomic
  compare-and-swap on the trunk ref.

This also catches write skew: A reads `f` and edits `g`, B reads `g` and edits
`f`. Neither writes what the other writes, but each acted on data the other changed.

## 2. Scope

In scope (v1): Python source only; symbol-level indexing with tree-sitter; a
name-based call graph; read tracking via an MCP server plus an inferred-read
fallback; a rules-based validator with an optional test-suite oracle; an atomic
`land` command; a benchmark with baselines.

Non-goals (v1): other languages, type inference, rename detection, any UI,
distributed operation, any LLM integration.

## 3. Stack

- Python 3.12, `uv`, `pytest`, `hypothesis`, `ruff`, `mypy`
- `tree-sitter` and `tree-sitter-python` (use the current Python bindings API;
  check the installed version)
- `mcp` 1.x (FastMCP, stdio transport)
- `typer` for the CLI; stdlib `sqlite3`, `subprocess`, `hashlib`, `dataclasses`
- No git library. `gitutil.py` shells out to `git`. Require git >= 2.38
  (`git merge-tree --write-tree`) and assert the version at startup.

## 4. Repo layout

```
stalecheck/
  pyproject.toml  Makefile  README.md  CLAUDE.md  PLAN.md
  docs/design.md  docs/decisions.md
  src/stalecheck/
    cli.py          # typer commands
    gitutil.py      # rev-parse, ls-tree, cat-file --batch, worktree, merge-tree, commit-tree, update-ref
    db.py           # sqlite schema + helpers (WAL mode, busy_timeout)
    symbols/
      extract.py    # tree-sitter -> Symbol records
      hashing.py    # contract_hash, body_hash
      callgraph.py  # raw refs + name-based resolution
    snapshot.py     # build/load per-commit symbol table + edges; worktree indexing
    sessions.py     # session lifecycle, recorded + inferred reads
    validate.py     # rules engine (pure)
    land.py         # validate + atomic CAS landing
    mcp_server.py   # read-tracking tools
    report.py       # human + JSON output
  bench/
    generator.py    # builds repos + scripted agents + hidden tests
    baselines.py    # git-only, file-lock, symbol-lock
    run.py          # runs all strategies, writes results.md + results.csv
    results/
  tests/
```

Makefile targets (exactly): `check` (ruff, mypy, pytest), `test`, `bench`
(seed 0, writes `bench/results/`).

## 5. Core data model

### 5.1 Symbol identity

`qname = "<repo-relative posix path>::<dotted name>"`, for example
`pricing.py::apply_discount` or `models.py::Cart.total`.

Extract:
- top-level functions and classes
- methods (including nested classes, dotted)
- module-level assignments, as kind `const` (name = assigned target; skip tuple unpacking)

Cross-file moves and renames are out of scope; they appear as a removal plus an addition.

### 5.2 Hashes

Both are SHA-256 over a canonical byte string.

- `contract_hash`:
  - function/method: kind, name, parameter list (names, default values as source
    text, annotations as source text), return annotation, decorators as source text
  - class: bases as source text plus the sorted names of public members
  - const: name only
- `body_hash`: the ordered sequence of (node type, leaf text) over the symbol's
  subtree, excluding comments and whitespace. Docstrings are included.
  Formatting-only and comment-only edits must not change it.

### 5.3 SQLite schema

Database location: `<git-common-dir>/stalecheck/db.sqlite`, so all worktrees
share it. Enable WAL and set a busy timeout.

```sql
CREATE TABLE blob_symbols(
  blob_sha TEXT, qname_local TEXT, kind TEXT,
  contract_hash TEXT, body_hash TEXT, start_byte INT, end_byte INT,
  PRIMARY KEY(blob_sha, qname_local));
CREATE TABLE blob_refs(
  blob_sha TEXT, caller_local TEXT, ref_text TEXT, ref_kind TEXT);
CREATE TABLE blob_imports(
  blob_sha TEXT, local_name TEXT, target_module TEXT, target_name TEXT);
CREATE TABLE snap_symbols(
  commit_sha TEXT, qname TEXT, kind TEXT, path TEXT,
  contract_hash TEXT, body_hash TEXT, PRIMARY KEY(commit_sha, qname));
CREATE TABLE snap_edges(
  commit_sha TEXT, caller TEXT, callee TEXT, ambiguous INT);
CREATE TABLE sessions(
  id TEXT PRIMARY KEY, name TEXT, base_commit TEXT, branch TEXT,
  worktree TEXT, status TEXT, created_at TEXT);
CREATE TABLE reads(
  id INTEGER PRIMARY KEY, session_id TEXT, qname TEXT,
  kind TEXT,                      -- 'direct' | 'incidental'
  obs_contract_hash TEXT, obs_body_hash TEXT, ts TEXT);
CREATE TABLE validations(
  id INTEGER PRIMARY KEY, session_id TEXT, trunk_commit TEXT, head_commit TEXT,
  verdict TEXT, report_json TEXT, ts TEXT);
```

### 5.4 Snapshots and caching

- Parse each git blob once and cache by blob SHA (`blob_symbols`, `blob_refs`,
  `blob_imports`).
- Build a commit snapshot by listing the tree (`git ls-tree -r`), loading cached
  blob data (read missing blobs in bulk with `git cat-file --batch`), then
  resolving references into `snap_symbols` and `snap_edges`.
- Never check files out to index them.
- Worktree files are indexed from disk. Compute the key as the git blob SHA
  (sha1 of `"blob <len>\0" + bytes`), so the cache is shared with committed blobs.

### 5.5 Call-graph resolution (name-based, over-approximate)

- A bare name resolves to a same-module symbol first, then through the import map.
- `self.m` resolves to the enclosing class's method `m`.
- `Class.m` and `module.f` resolve through imports.
- Any other `x.m` fans out to every project symbol named `m` and is marked `ambiguous=1`.
- References to non-project names are ignored.
- An edge means "caller references callee".

## 6. Components

### 6.1 Sessions

`session start --name A --branch agent-a [--base HEAD] [--worktree PATH]`:
creates the branch and a git worktree (`git worktree add -b`), records
`base_commit` (resolved SHA), and prints the session ID.

Validation uses the session branch tip as `head`. Agents must commit their work;
`validate` warns if the worktree is dirty.

### 6.2 MCP read tracking

- Server command: `stalecheck serve --worktree PATH`. The session ID comes from
  env `STALECHECK_SESSION`, never from tool arguments.
- Tools:
  - `list_symbols(path)`: names and kinds only; records nothing.
  - `read_symbol(qname)`: returns source text; records a **direct** read.
  - `find_callers(qname)` and `find_callees(qname)`: record the queried symbol
    as **direct** and the returned symbols as **incidental**.
  - `read_file(path)`: returns the file; records every symbol in it as **incidental**.
- Content is served from the worktree. Record the contract and body hashes
  **observed in the worktree at read time** (not the base commit's hashes).
- Always record. Self-written symbols are filtered at validation time (6.4).
- Provide a `.mcp.json` example in the README.

### 6.3 Inferred reads (fallback for agents that bypass MCP)

For every symbol in the write-set that is `modified` or `added`, take its callees
at head (one hop). Treat each as a **direct** read with observed hashes from the
**base** snapshot. Validation uses the union of recorded and inferred reads.

### 6.4 Validation (`validate.py`, pure)

Inputs: base, trunk and head snapshots; the reads; an optional test result.

```
base_c       = merge-base(trunk_tip, head)
trunk_delta  = symbol_diff(base_c, trunk_tip)
write_set    = symbol_diff(base_c, head)       # added | removed | modified,
                                               # with contract_changed / body_changed flags
reads        = recorded ∪ inferred, minus any qname in write_set
```

| Rule | Condition | Severity |
|---|---|---|
| R0 textual | `git merge-tree --write-tree trunk head` reports conflicts | BLOCK |
| R1 divergent edit | qname in both write_set and trunk_delta, and head hashes differ from trunk hashes (includes concurrent additions with different hashes, and modify-vs-remove). Identical changes on both sides are not a conflict. | BLOCK |
| R2 stale read, contract/removal | read symbol's contract hash on trunk differs from the observed one, or the symbol is gone on trunk; read is direct | BLOCK (WARN if incidental) |
| R3 stale read, body only | contract equal but body hash differs from observed; read is direct | SUSPECT |
| R4 soft stale read | body hash differs; read is incidental | INFO |
| R5 reverse impact | a symbol you changed has `contract_changed`, and trunk_delta added or modified a caller of it (per the trunk snapshot's edges) that is not in your write_set | BLOCK |

Notes:
- Stale means: observed hash differs from the trunk-tip hash. If the agent merged
  trunk before reading, observed equals trunk and nothing fires.
- Always evaluate every rule, even after R0 fires, so the report is complete.
- Verdict is the maximum severity. Unresolved SUSPECT is reported as WARN.
- **SUSPECT escalation:** with `--run-tests CMD`, build the speculative merge
  commit (`git merge-tree --write-tree` then `git commit-tree`), check it out in
  a temporary detached `git worktree`, and run CMD with a timeout. A failure
  upgrades each SUSPECT to BLOCK. A pass downgrades them to INFO with a note.
  Skip escalation when R0 fired (no merged tree exists). Always remove the
  temporary worktree.
- Each finding records: rule ID, affected qnames, old and new hashes, and a
  one-line human explanation.

### 6.5 Landing (`land.py`)

1. Resolve trunk tip `T` and run validation. Stop if the verdict is BLOCK, or
   WARN without `--allow-warn`.
2. Build the merge: `git merge-tree --write-tree T head` gives a tree, then
   `git commit-tree <tree> -p T -p head -m ...`.
3. `git update-ref refs/heads/<trunk> <new> <T>`. The old-value argument makes
   this an atomic compare-and-swap.
4. If it fails because trunk moved, go back to step 1. Cap retries (default 5).
5. Record the validation and update `sessions.status`.

Assume the trunk branch is not checked out in any worktree (document this).
Benchmark repos keep trunk unchecked-out for this reason.

### 6.6 CLI

```
stalecheck init
stalecheck session start --name A --branch agent-a [--base HEAD] [--worktree PATH]
stalecheck session list
stalecheck serve --worktree PATH            # MCP over stdio; env STALECHECK_SESSION
stalecheck diff-symbols REV1 REV2 [--json]
stalecheck validate SESSION [--trunk main] [--run-tests "pytest -q"] [--json]
stalecheck land SESSION [--trunk main] [--run-tests CMD] [--allow-warn]
stalecheck bench run [--n 200] [--seed 0]
```

Exit codes: 0 = PASS or INFO, 1 = WARN, 2 = BLOCK. Human-readable output is the
default and `--json` gives machine output. Every BLOCK or WARN message names the
symbol, the rule, and what changed.

## 7. Benchmark (the credibility core)

Each scenario instance contains: a base repo, scripted edits and reads for
agents A and B, and a **hidden pytest suite that fails on the merged tree if and
only if there is a real semantic conflict**. That gives ground truth without an
LLM or manual labeling. For the textual-conflict template there is no merged
tree, so the label is conflict by definition.

Names, constants, and file layouts are randomized per instance from the seed.

| # | Template | Ground truth |
|---|---|---|
| 1 | Both edit the same lines of one function | conflict (textual) |
| 2 | A changes a function's signature; B adds a new caller using the old signature | conflict |
| 3 | A changes behavior with the same signature (the discount example); B adds a caller relying on old behavior | conflict |
| 4 | Write skew: two symbols with a cross-symbol invariant; A reads one and edits the other, B the reverse | conflict |
| 5 | A optimizes the body of a function B reads; behavior unchanged | benign |
| 6 | A makes a comment or formatting-only change to a function B reads | benign |
| 7 | A and B edit different functions in the same file | benign |
| 8 | Both add a symbol with the same name and different bodies | conflict |
| 9 | A removes a function B newly calls | conflict |
| 10 | Both append entries to a module-level registry at non-adjacent positions (git merges cleanly) | benign |

Template 10 is an expected false positive for symbol-level strategies, because
both agents modify the same `const` symbol. Keep it in, and report it.

Strategies compared:
- (a) git-only: flag if `merge-tree` reports conflicts
- (b) file-lock: flag if write-sets touch the same file
- (c) symbol-lock: flag if write-sets overlap at symbol level (the Wit-style baseline)
- (d) stalecheck contract-only (R0, R1, R2, R5)
- (e) stalecheck full rules, no tests (SUSPECT treated as flagged)
- (f) stalecheck full rules + test oracle

Positive class = real conflict; "flagged" = predicted positive. Report
precision, recall, F1 overall; **per-template recall**; and the **flag rate on
benign templates (5, 6, 7, 10)**. Write `bench/results/results.md` and a CSV.
Use a fixed seed so results reproduce.

Also include one end-to-end test that drives a scripted agent through the real
MCP server over stdio, to prove recorded reads work over the protocol.

## 8. Milestones and acceptance criteria

### Day 1: foundations
- Scaffold: `pyproject.toml`, uv, ruff, mypy, pytest, Makefile, `docs/decisions.md`.
- `gitutil.py` (with the git version assertion) and `db.py`.
- `symbols/extract.py` and `symbols/hashing.py`.
- Acceptance:
  - Golden tests for extraction (functions, classes, nested classes, methods, consts).
  - Hypothesis test: inserting blank lines and comments between statements does
    not change `body_hash`.
  - A signature change alters `contract_hash` but not `body_hash`.
  - A body-only change alters `body_hash` but not `contract_hash`.

### Day 2: snapshots and call graph
- `symbols/callgraph.py`, `snapshot.py` (including worktree indexing and blob caching).
- `diff-symbols` CLI.
- Acceptance:
  - A 200-file synthetic repo snapshots successfully, and a second build hits
    the cache (assert no re-parsing).
  - `diff-symbols` reports added, removed, and modified symbols correctly,
    including `contract_changed` and `body_changed` flags.
  - Resolution tests cover bare names, `self.m`, imports, and the ambiguous fan-out case.

### Day 3: sessions and MCP read tracking
- `sessions.py`, `mcp_server.py` (five tools), inferred reads.
- Acceptance:
  - An integration test starts the server over stdio, calls `read_symbol`, and
    finds the recorded row with the observed hashes.
  - `read_file` records incidental reads. `find_callers` records direct plus incidental.
  - `session start` creates the branch and worktree.
  - Inferred reads are produced for callees of written symbols.

### Day 4: validation engine
- `validate.py` (R0-R5), `report.py`, CLI `validate`, test-oracle escalation.
- Acceptance:
  - A unit test per rule using hand-built snapshots, including the negative case for each.
  - Self-written symbols are excluded from R2-R4.
  - The discount example yields SUSPECT (WARN), and escalates to BLOCK when the
    test command fails.
  - Exit codes match section 6.6.

### Day 5: landing and benchmark generator
- `land.py` with CAS, and `bench/generator.py` with templates 1-10 and scripted agents.
- Acceptance:
  - Two concurrent `land` attempts yield exactly one immediate success and one
    re-validation against the new trunk.
  - A retry test simulates trunk moving between steps 1 and 3.
  - Every template generates a repo whose hidden test fails or passes as the
    ground-truth table states.

### Day 6: baselines and results
- `bench/baselines.py`, `bench/run.py`, first results table.
- Acceptance:
  - `make bench` reproduces identical results with seed 0 and writes the results files.
  - Investigate every template where stalecheck underperforms. **Record failures
    honestly** in the results and the limitations section. Do not tune the
    benchmark to hide them.

### Day 7: polish and write-up
- README: thesis, the discount example, an architecture diagram (ASCII or
  mermaid), the results table, a limitations section, and the `.mcp.json` example.
- `docs/design.md`: OCC, backward validation, write skew, and why git cannot see these conflicts.
- `examples/demo.sh`: a scripted end-to-end demo.
- Acceptance: from a fresh clone, `uv sync && make check && make bench` succeeds.

## 9. Known limitations (state these in the README)

- Body-only semantic changes (for example a unit change) are invisible to the
  contract hash. They surface only as SUSPECT on direct reads, confirmed only
  when a test oracle exists. Without tests, expect a notable false-positive rate
  on benign body edits. Measure it and report it.
- Reads that bypass MCP are not recorded. The inferred-read fallback covers only
  callees of written symbols.
- The call graph is name-based. It can miss edges (dynamic dispatch) and add
  spurious ones (name fan-out).
- No rename detection. Python only.
- Whole-const symbols (registries, config dicts) produce false positives when
  two agents edit different entries.
- The contract/body split and the direct/incidental weighting are design choices
  to be validated by the benchmark, not established techniques. Revise them if
  the numbers say so.

## 10. Roadmap (do not build in v1)

- v2: type-aware resolution via pyright or LSP; a behavioral-contract hash
  (docstring plus annotations) to catch more body-only changes; entry-level
  tracking for registry consts; TypeScript support.
- v3: wound-wait scheduling so repeatedly aborted agents are not starved; a live
  dashboard; an experiment with real coding agents on shared tasks comparing
  conflict rates with and without stalecheck.

## 11. Definition of done

- `make check` is green (lint, types, tests).
- `stalecheck bench run` regenerates a results table covering all six strategies.
- The README opens with the discount example, shows honest per-template numbers,
  and has a limitations section.
- Each rule R0-R5 has a unit test. The CAS retry path and the end-to-end MCP
  path each have a test.