# CLAUDE.md

## What this project is
`stalecheck` is a local, free, deterministic CLI and MCP server that validates
parallel AI-agent work at commit time. It treats each agent session as a
transaction: it records read-sets and write-sets at the code-symbol level
(tree-sitter) and runs optimistic backward validation before work lands.
It catches changes that `git merge` accepts but that were built on stale reads.

The full spec is in `PLAN.md`. Read it before starting any milestone.
Progress is tracked in the checklist at the top of `PLAN.md`.

## Workflow
1. At the start of a session, read `PLAN.md` and find the first unchecked milestone.
2. Work on that milestone only. Do not start later milestones early.
3. Write tests alongside each module, not after.
4. Run `make check` before every commit. It must be green.
5. When a milestone's acceptance criteria are met, tick its box in `PLAN.md`
   and commit with a message like `milestone 3: sessions and MCP read tracking`.
6. If a decision is ambiguous, choose the simplest option and append one line
   to `docs/decisions.md` (what you chose and why). Do not stop to ask unless
   you are truly blocked.

## Commands
```
uv sync                 # install dependencies
make check              # ruff + type check + pytest (must pass before commits)
make test               # pytest only
make bench              # run the benchmark with seed 0, write bench/results/
uv run stalecheck --help
```
Create the Makefile in milestone 1 with exactly these targets.

## Hard constraints
- No LLM calls and no network access anywhere in the code or tests.
  The benchmark uses scripted fake agents.
- Python 3.12. Dependencies: tree-sitter, tree-sitter-python, mcp (pinned 1.x),
  typer, hypothesis, pytest, ruff. Do not add others without logging why in
  `docs/decisions.md`.
- No git library. All git access goes through `src/stalecheck/gitutil.py`,
  which shells out to the `git` binary. Require git >= 2.38 and assert it.
- Never check files out just to index them. Read blobs with `git cat-file --batch`.
- Do not guess library APIs. For tree-sitter and the MCP SDK, check the
  installed version's docs or `help()` first. Both have changed recently.
- Session IDs come from the `STALECHECK_SESSION` environment variable, never
  from MCP tool arguments.

## Code conventions
- Keep core logic pure and separate from I/O. `symbols/hashing.py`,
  `symbols/callgraph.py` resolution, and `validate.py` take plain data in and
  return plain data out. Only `gitutil.py`, `db.py`, `sessions.py`, `land.py`,
  and `mcp_server.py` touch the outside world.
- Use dataclasses (frozen where possible) for Symbol, Finding, Report, and snapshots.
- Type-annotate everything and keep the type checker clean.
- Every validation finding must carry its rule ID (R0-R5), the affected qnames,
  and the old and new hashes, so reports are explainable.
- Make benchmark and test runs deterministic: fixed seeds, no wall-clock
  dependence, no reliance on dict ordering or filesystem listing order.

## Testing requirements
- Each rule R0-R5 has its own unit test using hand-built snapshots.
- Hypothesis property tests: adding blank lines or comments must not change
  `body_hash`; a signature change must change `contract_hash` but not `body_hash`.
- One test must drive a scripted agent through the real MCP server over stdio.
- One test must simulate trunk moving mid-landing and confirm the
  compare-and-swap retry path works.
- Tests that need git create temporary repos under pytest's `tmp_path`.
  Never touch the developer's own repo.

## Honesty rules (important)
- Every claim in the README must be backed by a number produced by `make bench`.
- If stalecheck performs poorly on a scenario class, report that in the results
  and the README's limitations section. Do not tune the benchmark to hide it.
- Do not describe the contract/body hash split or the direct/incidental read
  weighting as established techniques. They are design choices being evaluated.

## Out of scope for v1
Languages other than Python, type inference, rename detection, any UI,
distributed operation, and any LLM integration. If you find yourself wanting
one of these, add a note to the roadmap section of `PLAN.md` instead.