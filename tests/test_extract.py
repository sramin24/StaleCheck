from stalecheck.symbols.extract import extract


def _kinds(source: str) -> dict[str, str]:
    return {s.qname_local: s.kind for s in extract(source.encode()).symbols}


def test_extracts_top_level_functions_classes_methods_and_consts() -> None:
    source = """
import os

LIMIT = 10
RATE: float = 0.5

def apply_discount(price, pct):
    return price * (1 - pct / 100)

async def fetch():
    pass

@dataclass
class Cart(Base):
    items = []

    def total(self):
        return sum(self.items)

    @property
    def empty(self):
        return not self.items

    class Line:
        def subtotal(self):
            return 0
"""
    assert _kinds(source) == {
        "LIMIT": "const",
        "RATE": "const",
        "apply_discount": "function",
        "fetch": "function",
        "Cart": "class",
        "Cart.total": "method",
        "Cart.empty": "method",
        "Cart.Line": "class",
        "Cart.Line.subtotal": "method",
    }


def test_skips_tuple_unpacking_attribute_targets_and_nested_functions() -> None:
    source = """
A, B = 1, 2
obj.attr = 3
items[0] = 4
COUNT += 1

def outer():
    def inner():
        pass
    return inner
"""
    assert _kinds(source) == {"outer": "function"}


def test_symbol_byte_range_covers_decorators() -> None:
    source = b"x = 1\n@dec\ndef f():\n    pass\n"
    (const, fn) = extract(source).symbols
    assert source[fn.start_byte : fn.end_byte] == b"@dec\ndef f():\n    pass"
    assert source[const.start_byte : const.end_byte] == b"x = 1"


def test_symbols_are_in_source_order() -> None:
    names = [s.qname_local for s in extract(b"def b(): pass\ndef a(): pass\n").symbols]
    assert names == ["b", "a"]


def test_later_redefinition_wins() -> None:
    (sym,) = extract(b"def f():\n    return 1\n\ndef f():\n    return 2\n").symbols
    assert sym.qname_local == "f"
    (only_second,) = extract(b"def f():\n    return 2\n").symbols
    assert sym.body_hash == only_second.body_hash
