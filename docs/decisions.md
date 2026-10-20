# Decisions

One line per ambiguous choice: what was chosen and why.

- 2026-10-19 Day 1: Build backend is hatchling (build-time only, not a runtime dependency); mypy is a dev dependency because PLAN.md section 3 and `make check` require it, though CLAUDE.md's list omits it.
- 2026-10-19 Day 1: `body_hash` covers only the `body` field (the function or class block); for a const it covers the whole assignment. Hashing the full subtree would include parameters and break "a signature change must not change body_hash".
- 2026-10-19 Day 1: Body leaves skip every node tree-sitter marks `is_extra` (comments and backslash line continuations); whitespace never appears as a token. Trailing commas and redundant parentheses are tokens, so "formatting-invariant" means whitespace, comments and line wrapping only.
- 2026-10-19 Day 1: Contract parts (parameters, return annotation, bases, decorators) are compared as token text, so whitespace and comments inside a signature do not change `contract_hash`.
- 2026-10-19 Day 1: Every contract includes the symbol kind; function contracts also include `async` and PEP 695 type parameters, since both change how callers must call it.
- 2026-10-19 Day 1: A class's "public members" are the non-underscore names of its methods, nested classes and class-level assignments.
- 2026-10-19 Day 1: Only direct children of the module (and of class bodies) are symbols; definitions under module-level `if`/`try` are skipped. Simplest reading of "top-level".
- 2026-10-19 Day 1: A redefined name keeps only the later definition (Python semantics); a chained assignment `a = b = 1` yields only the outer target `a`; a bare annotation `X: int` is a const.
- 2026-10-19 Day 1: Tests pin GIT_AUTHOR/COMMITTER name, email and date and ignore global/system git config, so commit SHAs reproduce across runs.
- 2026-10-19 Day 1: `Git.update_ref_cas` returns False only when the ref no longer equals the expected old value, and raises on any other update-ref failure.
