"""Content hashes for symbols.

Pure functions over plain data. The tree walking that produces their inputs lives in
``extract.py``. Every part is length-prefixed before hashing so that no two different
inputs can produce the same byte stream.
"""

import hashlib
from collections.abc import Iterable


def _feed(digest: "hashlib._Hash", data: bytes) -> None:
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def contract_hash(parts: Iterable[str]) -> str:
    """Hash a symbol's contract, given as ordered, labelled parts (e.g. ``"param:a : int"``)."""
    digest = hashlib.sha256()
    for part in parts:
        _feed(digest, part.encode("utf-8", "backslashreplace"))
    return digest.hexdigest()


def body_hash(leaves: Iterable[tuple[str, bytes]]) -> str:
    """Hash a symbol's body, given as the ordered (node type, leaf text) pairs of its tokens.

    Callers must already have dropped comments and other non-semantic tokens; whitespace
    never appears as a token.
    """
    digest = hashlib.sha256()
    for node_type, text in leaves:
        _feed(digest, node_type.encode())
        _feed(digest, text)
    return digest.hexdigest()
