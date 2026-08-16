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

from yosoi.observations import anchoring

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

    parser = lxml_html.HTMLParser()
    try:
        root = lxml_html.fromstring(data, parser=parser)
    except etree.ParserError as exc:
        raise HtmlParseError(f'source HTML evidence could not be parsed: {exc}') from exc
    if any(entry.type_name == 'ERR_RESOURCE_LIMIT' for entry in parser.error_log):
        raise HtmlParseError('source HTML evidence exceeds the parser depth limit; refusing a truncated tree')
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


TAG_KEY_PREFIX = anchoring.TAG_KEY_PREFIX
"""Re-exported from the shared anchoring module, which owns the identity recipe."""


def _attributes(element: _Element) -> list[tuple[str, str]]:
    """Return attributes in the author's source order, as the anchor tiers require."""
    return [(str(name), str(value)) for name, value in element.attrib.items()]


def structural_keys(element: _Element) -> list[str]:
    """Return this element's attribute-borne anchor keys, most durable first."""
    return anchoring.structural_keys(str(element.tag), _attributes(element))


SKELETON_TAGS = anchoring.SKELETON_TAGS
"""Re-exported from the shared anchoring module."""


def anchor_keys(element: _Element) -> list[str]:
    """Return every key an anchor may use for this element, most durable first."""
    return anchoring.anchor_keys(str(element.tag), _attributes(element))


def anchor_tier(key: str) -> str:
    """Return which durability tier an anchor key came from, for measurement."""
    return anchoring.anchor_tier(key)


def candidate_keys(element: _Element) -> list[str]:
    """Return content keys for one element, most durable first.

    An `id` beats a `data-*` attribute beats a class beats a text digest. Ordinals are
    deliberately absent — a position is not a key, and treating it as one is what breaks after
    a scroll.
    """
    keys = structural_keys(element)
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


def anchor_census(root: _Element) -> dict[str, int]:
    """Count every anchor key in the document, so uniqueness is checked and not assumed."""
    return anchoring.build_census(
        (str(element.tag), _attributes(element)) for element in root.iter() if isinstance(element.tag, str)
    )


def nearest_anchor(element: _Element, census: dict[str, int]) -> tuple[_Element, str] | None:
    """Return the nearest ancestor-or-self carrying a document-unique key, and that key.

    This is what makes an address survive edits ABOVE it. A root-absolute path is positional
    at every step — insert one section near the top of the document and `div[2]` names
    something else, so every reference beneath it silently changes meaning. Addressing from
    the nearest durable ancestor confines that blast radius to the anchor's own subtree.

    Returns None when the document offers nothing durable on the way up, in which case the
    caller must fall back to a positional path and say so.
    """
    current: _Element | None = element
    while current is not None and isinstance(current.tag, str):
        key = anchoring.usable_anchor(str(current.tag), _attributes(current), census)
        if key is not None:
            return current, key
        current = current.getparent()
    return None


def matches_key(element: _Element, key: str) -> bool:
    """Return whether an element carries the given content key."""
    return key in candidate_keys(element)


__all__ = [
    'METADATA_CONTENT',
    'NON_CONTENT_TAGS',
    'TAG_KEY_PREFIX',
    'HtmlParseError',
    'SignatureCache',
    'anchor_census',
    'anchor_keys',
    'anchor_tier',
    'assign_member_keys',
    'candidate_keys',
    'content_children',
    'matches_key',
    'nearest_anchor',
    'node_label',
    'own_text',
    'parse',
    'skeleton_signature',
    'structural_keys',
    'subtree_text',
    'text_digest',
]
