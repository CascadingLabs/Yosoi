"""Anchor-subtree hashing for hash-free re-scrape recomputation (CAS-18 stretch).

Goal: when a page is re-scraped, decide whether each cached selector is
still valid *without* invoking the discovery LLM. We do this by capturing
two hashes per selector at cache-write time:

* ``anchor_hash_partial`` — structure-only (tags + attribute *names* +
  selector-relevant attribute values). Stable across value-only edits.
* ``anchor_hash_full`` — structure + normalized text. Sensitive to any
  textual change.

On re-scrape:

* ``partial`` matches → the selector still points at the same structural
  shape. Skip discovery, jump straight to extraction.
* ``partial`` differs → fall through to the existing cache + discovery
  path, since the page restructure invalidates our cached selector.

This module *only* provides the hash primitives + the canonicalization
they depend on. Wiring the hashes into ``SelectorStorage`` cache keys is
the next step (kept out of the spike to limit blast radius).

Versioning: the canonicalization scheme is identified by
``CANON_VERSION``. Bumping it forces every cached entry to recompute on
next access — Plan: store the version alongside each hash so reads can
detect mismatch.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from lxml import etree

# Bumped any time the canonicalization rules change in a way that would
# invalidate previously-stored hashes.
CANON_VERSION = 1

# Attributes that contribute to ``anchor_hash_partial`` *values* rather
# than just attribute names. These are the attributes the selector engine
# actually uses to disambiguate matches; values matter here. Anything
# outside this set is hashed as "name only" (presence + key, not value).
_SELECTOR_VALUE_ATTRS = frozenset({'class', 'id', 'name', 'type', 'role'})

# HTML5 structural markers used to bound the anchor subtree. The smallest
# ancestor of a selector match containing one of these markers is the
# anchor — small enough to localize edits, big enough to be stable across
# minor sibling reshuffles.
_STRUCTURAL_TAGS = frozenset(
    {
        'article',
        'aside',
        'form',
        'header',
        'footer',
        'main',
        'nav',
        'section',
        'table',
    }
)


@dataclass(frozen=True)
class AnchorHashes:
    """Hashes captured for one selector's anchor subtree.

    Attributes:
        partial: Structure-only fingerprint. Stable across value-only edits.
        full: Structure + text fingerprint. Sensitive to any textual change.
        version: ``CANON_VERSION`` snapshot — read sites compare to detect
            stale entries when the canonicalization scheme changes.
    """

    partial: str
    full: str
    version: int = CANON_VERSION


_WHITESPACE_RE = re.compile(r'[ \t\r\n]+')


def normalize_text(text: str | None) -> str:
    """Canonical text representation used by ``anchor_hash_full``.

    Whitespace runs collapse to a single space and the result is stripped.
    Empty / whitespace-only input returns ``''``. This matches the
    whitespace policy ``compact_whitespace`` applies in tier-1.
    """
    if not text:
        return ''
    return _WHITESPACE_RE.sub(' ', text).strip()


def _canonical_attrs(el: etree._Element, *, with_values: bool) -> str:
    """Return a deterministic attribute fingerprint for one element.

    With ``with_values=False``, only attribute *names* are emitted —
    that's the structural fingerprint. With ``with_values=True``, the
    selector-relevant attributes (class/id/name/type/role) carry their
    values too, since those are the bits the selector engine actually
    uses. Names are always sorted so attribute reordering can't change
    the hash.
    """
    parts: list[str] = []
    for name in sorted(el.attrib):
        value = el.attrib[name]
        if with_values and name in _SELECTOR_VALUE_ATTRS:
            # Class is order-independent in CSS — sort tokens so
            # ``"a b"`` and ``"b a"`` hash the same.
            if name == 'class':
                value = ' '.join(sorted(value.split()))
            parts.append(f'{name}={value}')
        else:
            parts.append(name)
    return '|'.join(parts)


def _localname(tag: object) -> str:
    if not isinstance(tag, str):
        return ''
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag


def find_anchor_subtree(match: etree._Element) -> etree._Element:
    """Return the smallest structural ancestor of *match* (or *match* itself).

    Walks up parents; returns the first node carrying an ``id`` attribute
    or an HTML5 structural tag (``<article>``, ``<section>``, ``<form>``,
    ``<table>``, ``<main>``, etc.). Falls back to ``match`` itself when no
    structural ancestor exists.
    """
    node: etree._Element | None = match
    while node is not None:
        if 'id' in node.attrib:
            return node
        if _localname(node.tag) in _STRUCTURAL_TAGS:
            return node
        node = node.getparent()
    return match


def _walk(el: etree._Element, *, with_text: bool, with_values: bool) -> str:
    """Pre-order serialize *el* into a canonical string for hashing.

    Tag local names + sorted attrs (with or without values per flags) +
    optionally normalized text. Children walk recursively. Comments and
    PIs are skipped — they carry no structural meaning.
    """
    if not isinstance(el.tag, str):
        return ''
    parts: list[str] = [_localname(el.tag), '[', _canonical_attrs(el, with_values=with_values), ']']
    if with_text:
        text = normalize_text(el.text)
        if text:
            parts.append(f'#{text}')
    for child in el:
        parts.append(_walk(child, with_text=with_text, with_values=with_values))
        if with_text:
            tail = normalize_text(child.tail)
            if tail:
                parts.append(f'#{tail}')
    return '(' + ''.join(parts) + ')'


def hash_subtree(el: etree._Element, *, kind: str) -> str:
    """Compute the partial or full hash for an anchor subtree.

    Args:
        el: Anchor subtree root.
        kind: ``'partial'`` (structure + selector-attr values, no text) or
            ``'full'`` (everything ``partial`` covers + normalized text).

    Returns:
        A 16-character hex digest. Truncated SHA-256 — collision risk is
        negligible at the cardinality of one anchor per selector per page,
        and a short digest keeps cache keys readable.
    """
    if kind == 'partial':
        canon = _walk(el, with_text=False, with_values=True)
    elif kind == 'full':
        canon = _walk(el, with_text=True, with_values=True)
    else:  # pragma: no cover - guarded by the literal arg type at the call sites
        raise ValueError(f'unknown hash kind: {kind!r}')
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()[:16]


def compute_anchor_hashes(match: etree._Element) -> AnchorHashes:
    """Convenience helper: find the anchor subtree and hash it both ways."""
    anchor = find_anchor_subtree(match)
    return AnchorHashes(
        partial=hash_subtree(anchor, kind='partial'),
        full=hash_subtree(anchor, kind='full'),
    )
