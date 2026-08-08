"""Pure HTML tree primitives shared by source-HTML pruning and inspection.

These live outside `pruning/` because the inspector needs the *same* notion of shape and
key that the pruner emitted — a second implementation is how an address stops resolving to
the thing it was minted for. `pruning/_shared.py` is deliberately modality-free, so HTML
semantics get their own home here.

Nothing in this module mutates a tree, performs I/O, or calls a model.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lxml.etree import _Element, _ElementTree

METADATA_CONTENT = frozenset({'base', 'link', 'meta', 'noscript', 'script', 'style', 'template', 'title'})
"""The HTML specification's *metadata content* category.

This is the one enumerated set in the module, and it is enumerated because the spec closes
it — it is not a guess about which declarations matter. It partitions a document exactly:
metadata content belongs to the declaration reducer, everything else to the structure
reducer, and nothing is claimed by both or by neither.
"""

NON_CONTENT_TAGS = METADATA_CONTENT
"""What the structure reducer skips: precisely what the declaration reducer takes."""

_DIGEST_BYTES = 8


class HtmlParseError(ValueError):
    """Raised when canonical HTML bytes cannot be parsed into a document tree."""


def parse(data: bytes) -> tuple[_Element, _ElementTree]:
    """Parse canonical bytes into a root element and the tree that addresses it."""
    from lxml import etree
    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(data)
    except etree.ParserError as exc:
        raise HtmlParseError(f'source HTML evidence could not be parsed: {exc}') from exc
    return root, root.getroottree()


def content_children(element: _Element) -> list[_Element]:
    """Return the element children that carry content, in document order."""
    return [child for child in element if isinstance(child.tag, str) and child.tag not in NON_CONTENT_TAGS]


SignatureCache = dict[int, 'tuple[_Element, str]']
"""Memo for skeleton signatures. The element is kept ALIVE alongside its digest on purpose.

lxml hands out a fresh Python proxy per access and frees it when the last reference drops,
so `id()` is only unique among *live* proxies — CPython reuses the address immediately. A
plain `dict[int, str]` therefore returns another element's shape once the first is collected,
which silently merges differently-shaped siblings into one bogus region. Holding the element
pins the id for the cache's lifetime.
"""


def skeleton_signature(element: _Element, cache: SignatureCache | None = None) -> str:
    """Return a structural signature that ignores content — the shape, not what fills it.

    Two subtrees share a signature iff they have the same tag shape. This is the primitive
    that lets 10,000 rows collapse to one exemplar without assuming anything about what the
    rows contain. Memoised because a large table would otherwise recompute every subtree
    once per ancestor.
    """
    if cache is None:
        cache = {}
    key = id(element)
    memo = cache.get(key)
    if memo is not None:
        return memo[1]
    parts = [str(element.tag), *(skeleton_signature(child, cache) for child in content_children(element))]
    digest = hashlib.blake2b('|'.join(parts).encode(), digest_size=_DIGEST_BYTES).hexdigest()
    cache[key] = (element, digest)
    return digest


def node_label(element: _Element) -> str:
    """Return a scannable `tag#id.class` label.

    Classes and ids are kept deliberately. Stripping them was the single worst-performing
    representation measured in NEXT-EVAL (arXiv:2505.17125), and they are the raw material
    Yosoi selectors are made of.
    """
    tag = str(element.tag)
    identifier = element.get('id')
    classes = (element.get('class') or '').split()
    label = tag
    if identifier:
        label += f'#{identifier}'
    if classes:
        label += f'.{classes[0]}'
    return label


def own_text(element: _Element) -> str:
    """Return the element's own visible text, whitespace-collapsed."""
    return ' '.join((element.text or '').split())


def subtree_text(element: _Element) -> str:
    """Return the element's whole visible text, whitespace-collapsed."""
    return ' '.join(element.text_content().split())


def text_digest(value: str) -> str:
    """Return a short stable digest for keying a member by its content."""
    return hashlib.blake2b(value.encode(), digest_size=_DIGEST_BYTES).hexdigest()


def candidate_keys(element: _Element) -> list[str]:
    """Return content keys for one element, most durable first.

    An `id` beats a `data-*` attribute beats a text digest. Ordinals are deliberately absent
    — a position is not a key, and treating it as one is what breaks after a scroll.
    """
    keys: list[str] = []
    identifier = element.get('id')
    if identifier:
        keys.append(f'id={identifier}')
    keys.extend(
        f'{name}={element.get(name)}'
        for name in sorted(str(name) for name in element.attrib)
        if name.startswith('data-')
    )
    text = subtree_text(element)
    if text:
        keys.append(f'text:{text_digest(text)}')
    return keys


def assign_member_keys(siblings: list[_Element]) -> list[str | None]:
    """Return the most durable UNIQUE key per sibling, or None where nothing is unique.

    Uniqueness is checked rather than assumed: a key matching two rows is not an address,
    and emitting one would make `expand` resolve to the wrong record.

    Computed for the whole group at once and counted in a single pass — the obvious
    per-element formulation is quadratic, which is exactly the shape that dies on the
    10,000-row table this reducer exists for.
    """
    from collections import Counter

    per_sibling = [candidate_keys(sibling) for sibling in siblings]
    frequency: Counter[str] = Counter(key for keys in per_sibling for key in keys)
    return [next((key for key in keys if frequency[key] == 1), None) for keys in per_sibling]


def matches_key(element: _Element, key: str) -> bool:
    """Return whether an element carries the given content key."""
    return key in candidate_keys(element)


__all__ = [
    'METADATA_CONTENT',
    'NON_CONTENT_TAGS',
    'HtmlParseError',
    'SignatureCache',
    'assign_member_keys',
    'candidate_keys',
    'content_children',
    'matches_key',
    'node_label',
    'own_text',
    'parse',
    'skeleton_signature',
    'subtree_text',
    'text_digest',
]
