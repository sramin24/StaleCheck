"""Parse Python source with tree-sitter and extract Symbol records."""

from collections.abc import Iterator
from dataclasses import dataclass

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from stalecheck.symbols.hashing import body_hash, contract_hash

_LANGUAGE = Language(tree_sitter_python.language())


@dataclass(frozen=True)
class Symbol:
    qname_local: str  # dotted name within its file, e.g. "Cart.total"
    kind: str  # "function" | "method" | "class" | "const"
    contract_hash: str
    body_hash: str
    start_byte: int
    end_byte: int


@dataclass(frozen=True)
class FileIndex:
    symbols: tuple[Symbol, ...]  # in source order; a later redefinition replaces an earlier one


def extract(source: bytes) -> FileIndex:
    tree = Parser(_LANGUAGE).parse(source)
    found: dict[str, Symbol] = {}
    for symbol in _module_symbols(tree.root_node):
        found.pop(symbol.qname_local, None)
        found[symbol.qname_local] = symbol
    return FileIndex(symbols=tuple(found.values()))


def _module_symbols(module: Node) -> Iterator[Symbol]:
    for child in module.named_children:
        if child.type == "expression_statement":
            const = _const(child)
            if const is not None:
                yield const
        else:
            yield from _definition(child, prefix="", in_class=False)


def _definition(node: Node, prefix: str, in_class: bool) -> Iterator[Symbol]:
    """Yield the symbol for a (possibly decorated) def or class, plus nested class members."""
    outer = node
    decorators: list[Node] = []
    if node.type == "decorated_definition":
        decorators = [c for c in node.named_children if c.type == "decorator"]
        definition = node.child_by_field_name("definition")
        if definition is None:
            return
        node = definition
    if node.type not in ("function_definition", "class_definition"):
        return
    name = _field_text(node, "name")
    qname = prefix + name
    body = node.child_by_field_name("body")
    leaves = _leaves(body) if body is not None else iter(())
    decorator_parts = [f"decorator:{_tokens(d)}" for d in decorators]

    if node.type == "function_definition":
        kind = "method" if in_class else "function"
        parts = [kind, name, f"async:{_is_async(node)}"]
        parts += _optional_part(node, "type_parameters", "type_params")
        parameters = node.child_by_field_name("parameters")
        if parameters is not None:
            parts += [f"param:{_tokens(p)}" for p in parameters.named_children if not p.is_extra]
        parts += _optional_part(node, "return_type", "returns")
        yield _symbol(qname, kind, parts + decorator_parts, leaves, outer)
        return

    members = _class_member_names(body) if body is not None else []
    parts = ["class", name]
    parts += _optional_part(node, "type_parameters", "type_params")
    parts += _optional_part(node, "superclasses", "bases")
    parts += [f"member:{m}" for m in sorted(set(members)) if not m.startswith("_")]
    yield _symbol(qname, "class", parts, leaves, outer)
    if body is not None:
        for child in body.named_children:
            yield from _definition(child, prefix=qname + ".", in_class=True)


def _const(statement: Node) -> Symbol | None:
    assignment = statement.named_children[0] if statement.named_child_count == 1 else None
    if assignment is None or assignment.type != "assignment":
        return None
    target = assignment.child_by_field_name("left")
    if target is None or target.type != "identifier":
        return None
    name = _text(target)
    return _symbol(name, "const", ["const", name], _leaves(assignment), assignment)


def _class_member_names(body: Node) -> list[str]:
    names: list[str] = []
    for child in body.named_children:
        node = (
            child.child_by_field_name("definition")
            if child.type == "decorated_definition"
            else child
        )
        if node is None:
            continue
        if node.type in ("function_definition", "class_definition"):
            names.append(_field_text(node, "name"))
        elif node.type == "expression_statement" and node.named_child_count == 1:
            assignment = node.named_children[0]
            target = (
                assignment.child_by_field_name("left") if assignment.type == "assignment" else None
            )
            if target is not None and target.type == "identifier":
                names.append(_text(target))
    return names


def _symbol(
    qname: str, kind: str, parts: list[str], leaves: Iterator[tuple[str, bytes]], span: Node
) -> Symbol:
    return Symbol(
        qname_local=qname,
        kind=kind,
        contract_hash=contract_hash(parts),
        body_hash=body_hash(leaves),
        start_byte=span.start_byte,
        end_byte=span.end_byte,
    )


def _leaves(node: Node) -> Iterator[tuple[str, bytes]]:
    """Yield (type, text) for every token under node in order, skipping comments and
    line continuations (tree-sitter marks both as "extra")."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current.is_extra:
            continue
        if current.child_count == 0:
            yield current.type, current.text or b""
        else:
            stack.extend(reversed(current.children))


def _tokens(node: Node) -> str:
    """Source text of node normalized to its tokens, so whitespace and comments don't count."""
    return " ".join(text.decode("utf-8", "backslashreplace") for _, text in _leaves(node))


def _optional_part(node: Node, field: str, label: str) -> list[str]:
    child = node.child_by_field_name(field)
    return [f"{label}:{_tokens(child)}"] if child is not None else []


def _is_async(function: Node) -> bool:
    return any(c.type == "async" for c in function.children)


def _field_text(node: Node, field: str) -> str:
    child = node.child_by_field_name(field)
    return _text(child) if child is not None else ""


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", "backslashreplace")
