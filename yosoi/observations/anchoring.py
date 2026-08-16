"""What makes an address durable, defined once for every modality.

`ref_id` is already modality-neutral — it hashes an anchor key, a shape, and a local path, and it
does not care which artifact those came from. What was NOT shared is the definition of an anchor
key, which lived inside `html_tree.py`. So source HTML earned identities and rendered DOM earned
none: the DOM pruner minted `/dom/node/<producer id>` and `ref_id` correctly refused every one of
them, measured as 0 identities across ten live pages.

Two implementations of "what identifies an element" would be two answers to the only question
identity asks, so this module owns the tiers and both modalities call it. What stays per-modality
is walking ancestry — lxml carries parent pointers and a `DomNode` tree does not — which is five
lines each and no part of the identity recipe.

The tiers, most to least intentional:

    id=…        a promise of uniqueness
    data-…=…    usually a deliberate hook
    class=…     a styling decision that happens to be unique here
    <first>=…   whatever the author chose to write first
    @{a=…&b=…} the first two attributes, when only their conjunction is unique
    tag:…       a tag occurring exactly once in the document

Nothing is enumerated. An allowlist of attribute names could only anchor what someone thought of
in advance, and the fallback tiers exist precisely so an element the author gave no conventional
hook still gets a durable address when the document happens to offer one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

TAG_KEY_PREFIX = 'tag:'
COMPOSITE_KEY_PREFIX = '@{'
COMPOSITE_KEY_SUFFIX = '}'
COMPOSITE_SEPARATOR = '&'
"""Marks an anchor keyed on a tag that occurs exactly once, e.g. `tag:title` → `//title`.

A colon cannot appear in the `name=value` form, so the two never collide — an element written
`<x tag="title">` yields `tag=title`, which is not `tag:title`.
"""

SAFE_TAG = re.compile(r'[A-Za-z_][\w.-]*')
"""A tag name that can be written as a path, and therefore used as an anchor.

Not every node in a rendered tree has one. A producer names a shadow root `#shadow-root`, which
is a real node and a real boundary but cannot be expressed as `//#shadow-root` — offering it as a
tag anchor minted a locator that failed to parse. Such nodes fall back to a positional address and
`ref_id` refuses them an identity, which is the honest outcome: the document offers no durable way
to name them.
"""

SKELETON_TAGS = frozenset({'html', 'head', 'body'})
"""Tags unique in every document and therefore identifying nothing.

Anchoring to `//body` passes a uniqueness check and buys nothing: the tail below it is the same
positional chain a root-absolute path would have used. Excluding them keeps `is_anchored` from
becoming trivially true for every element on the page.
"""


def structural_keys(tag: str, attributes: Sequence[tuple[str, str]]) -> list[str]:
    """Return the attribute-borne keys for one element, most durable first.

    Attributes only, never text: these are the keys an ANCHOR may use, and an anchor whose
    identity moves when a sentence is reworded is not an anchor. `attributes` must be in the
    author's own source order — the last tier is "whatever was written first", which is the only
    statement of identity available on an element carrying no conventional hook.
    """
    keys: list[str] = []
    values = dict(attributes)
    identifier = values.get('id')
    if identifier:
        keys.append(f'id={identifier}')
    keys.extend(
        f'{name}={values[name]}' for name in sorted(values) if name.startswith('data-') and SAFE_TAG.fullmatch(name)
    )
    classes = values.get('class')
    if classes and classes.split():
        keys.append(f'class={" ".join(classes.split())}')
    first = next(iter(attributes), None)
    if first is not None and SAFE_TAG.fullmatch(first[0]):
        candidate = f'{first[0]}={first[1]}'
        if candidate not in keys:
            keys.append(candidate)
    return keys


def composite_anchor_key(attributes: Sequence[tuple[str, str]]) -> str | None:
    """Return a key joining the first two usable attributes, or None if it cannot round-trip."""
    pairs = [(name, value) for name, value in attributes if name and value][:2]
    if len(pairs) < 2:
        return None
    if any(not SAFE_TAG.fullmatch(name) or COMPOSITE_SEPARATOR in value for name, value in pairs):
        return None
    body = COMPOSITE_SEPARATOR.join(f'{name}={value}' for name, value in pairs)
    return f'{COMPOSITE_KEY_PREFIX}{body}{COMPOSITE_KEY_SUFFIX}'


def composite_anchor_parts(key: str) -> tuple[tuple[str, str], ...]:
    """Parse one composite key into ordered attribute pairs, returning empty on malformed input."""
    if not key.startswith(COMPOSITE_KEY_PREFIX) or not key.endswith(COMPOSITE_KEY_SUFFIX):
        return ()
    parts: list[tuple[str, str]] = []
    for item in key[len(COMPOSITE_KEY_PREFIX) : -len(COMPOSITE_KEY_SUFFIX)].split(COMPOSITE_SEPARATOR):
        name, separator, value = item.partition('=')
        if not separator or not name or not value:
            return ()
        parts.append((name, value))
    return tuple(parts) if len(parts) >= 2 else ()


def anchor_keys(tag: str, attributes: Sequence[tuple[str, str]]) -> list[str]:
    """Return every key an anchor may use, most durable first, including the tag tier.

    The tag tier is one `structural_keys` deliberately excludes: `<title>` carries no attributes
    at all, so without it a title could only ever be addressed positionally — and a title is not
    a thing a diff should lose track of.
    """
    keys = structural_keys(tag, attributes)
    composite = composite_anchor_key(attributes)
    if composite is not None and composite not in keys:
        keys.append(composite)
    if tag not in SKELETON_TAGS and SAFE_TAG.fullmatch(tag):
        keys.append(f'{TAG_KEY_PREFIX}{tag}')
    return keys


def anchor_tier(key: str) -> str:
    """Return which durability tier an anchor key came from, for measurement."""
    if key.startswith(COMPOSITE_KEY_PREFIX):
        return 'composite'
    if key.startswith(TAG_KEY_PREFIX):
        return 'tag'
    name = key.partition('=')[0]
    if name == 'id':
        return 'id'
    if name.startswith('data-'):
        return 'data'
    if name == 'class':
        return 'class'
    return 'attribute'


def build_census(elements: Iterable[tuple[str, Sequence[tuple[str, str]]]]) -> dict[str, int]:
    """Count every anchor key in a document, so uniqueness is checked rather than assumed.

    Built once per document and consulted per element: the per-element formulation is quadratic,
    which is the shape that dies on the pages this package exists for.
    """
    census: Counter[str] = Counter()
    for tag, attributes in elements:
        census.update(anchor_keys(tag, attributes))
    return census


LOCATOR_RESERVED = ('"', '#', '|')
"""Characters an anchor value cannot contain, because the locator grammar uses them.

`"` delimits an attribute value in the path, `#` separates a path from its qualifiers, and `|`
separates segments. A key carrying one of them cannot round-trip: an anchor on
`href="#/active"` — an ordinary TodoMVC filter link — produced
`//*[@href="#/active"]#anchor=…`, which parses as a path of `//*[@href="` and a qualifier of
`/active"]#anchor`. Found via a live DOM capture, but the grammar is shared, so any HTML page with
a fragment link was one anchor tier away from the same failure.

Rejected rather than escaped, matching how `"` was already handled: the element falls back to a
positional address and `ref_id` declines it an identity, which is honest about what the page
offered rather than inventing an encoding the resolver would have to guess at.
"""


def usable_anchor(tag: str, attributes: Sequence[tuple[str, str]], census: dict[str, int]) -> str | None:
    """Return this element's most durable document-unique key, or None if it has none."""
    for key in anchor_keys(tag, attributes):
        if census.get(key) == 1 and not any(character in key for character in LOCATOR_RESERVED):
            return key
    return None


__all__ = [
    'COMPOSITE_KEY_PREFIX',
    'COMPOSITE_KEY_SUFFIX',
    'COMPOSITE_SEPARATOR',
    'LOCATOR_RESERVED',
    'SAFE_TAG',
    'SKELETON_TAGS',
    'TAG_KEY_PREFIX',
    'anchor_keys',
    'anchor_tier',
    'build_census',
    'composite_anchor_key',
    'composite_anchor_parts',
    'structural_keys',
    'usable_anchor',
]
