from hypothesis import given
from hypothesis import strategies as st

from stalecheck.symbols.extract import Symbol, extract


def _one(source: str, qname: str = "f") -> Symbol:
    return next(s for s in extract(source.encode()).symbols if s.qname_local == qname)


BASE = """
def f(price, pct=10):
    \"\"\"Apply a discount.\"\"\"
    rate = pct / 100
    total = price * (1 - rate)
    return total
"""


def test_signature_change_alters_contract_but_not_body() -> None:
    changed = BASE.replace("def f(price, pct=10):", "def f(price, pct: float = 0.1) -> float:")
    before, after = _one(BASE), _one(changed)
    assert before.contract_hash != after.contract_hash
    assert before.body_hash == after.body_hash


def test_decorator_change_alters_contract_but_not_body() -> None:
    before, after = _one(BASE), _one("@cache\n" + BASE.lstrip())
    assert before.contract_hash != after.contract_hash
    assert before.body_hash == after.body_hash


def test_async_change_alters_contract() -> None:
    assert _one(BASE).contract_hash != _one(BASE.replace("def f", "async def f")).contract_hash


def test_body_change_alters_body_but_not_contract() -> None:
    changed = BASE.replace("rate = pct / 100", "rate = pct")
    before, after = _one(BASE), _one(changed)
    assert before.body_hash != after.body_hash
    assert before.contract_hash == after.contract_hash


def test_docstring_change_alters_body() -> None:
    changed = BASE.replace("Apply a discount.", "Apply a fractional discount.")
    assert _one(BASE).body_hash != _one(changed).body_hash


def test_whitespace_inside_signature_does_not_alter_contract() -> None:
    changed = BASE.replace("def f(price, pct=10):", "def f(\n    price,\n    pct = 10,  # pct\n):")
    # The trailing comma is a token, so only whitespace and comments are compared here.
    changed = changed.replace("pct = 10,  # pct", "pct = 10  # pct")
    assert _one(BASE).contract_hash == _one(changed).contract_hash


def test_class_contract_tracks_bases_and_public_members() -> None:
    base = "class C(Base):\n    def m(self):\n        pass\n    def _p(self):\n        pass\n"
    c = _one(base, "C")
    assert c.contract_hash != _one(base.replace("(Base)", "(Other)"), "C").contract_hash
    assert c.contract_hash != _one(base.replace("def m", "def n"), "C").contract_hash
    assert c.contract_hash == _one(base.replace("def _p", "def _q"), "C").contract_hash


def test_const_contract_is_name_only() -> None:
    assert _one("X = 1\n", "X").contract_hash == _one("X = 2\n", "X").contract_hash
    assert _one("X = 1\n", "X").body_hash != _one("X = 2\n", "X").body_hash


def test_kind_is_part_of_contract() -> None:
    func = _one("def m(self):\n    pass\n", "m")
    method = _one("class C:\n    def m(self):\n        pass\n", "C.m")
    assert func.contract_hash != method.contract_hash
    assert func.body_hash == method.body_hash


_BODY_LINES = BASE.strip("\n").split("\n")[1:]
_fillers = st.sampled_from(["", "# note", "#", "# a: b = c", "   ", "\t# tabbed"])


@given(st.lists(st.tuples(st.integers(0, len(_BODY_LINES) - 1), _fillers), max_size=8))
def test_blank_lines_and_comments_do_not_alter_body_hash(
    inserts: list[tuple[int, str]],
) -> None:
    lines = list(_BODY_LINES)
    # Insert from the bottom so earlier indexes stay valid; insert after the docstring
    # line at the earliest so the docstring stays the first statement.
    for index, filler in sorted(inserts, reverse=True):
        lines.insert(index + 1, "    " + filler.strip() if filler.strip() else filler)
    source = "def f(price, pct=10):\n" + "\n".join(lines) + "\n"
    assert _one(source).body_hash == _one(BASE).body_hash
    assert _one(source).contract_hash == _one(BASE).contract_hash


@given(st.sampled_from(["  # trailing", "  #", "\t# x"]), st.integers(0, len(_BODY_LINES) - 1))
def test_trailing_comments_do_not_alter_body_hash(comment: str, index: int) -> None:
    lines = list(_BODY_LINES)
    lines[index] += comment
    source = "def f(price, pct=10):\n" + "\n".join(lines) + "\n"
    assert _one(source).body_hash == _one(BASE).body_hash
