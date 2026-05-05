"""Tier-1 transforms: always-safe drops/strips.

Each transform mutates the lxml tree in place and returns the number of
nodes/attrs it touched, so the orchestrator can roll them up into a
``transform_count`` Langfuse attribute.

Safety bar: a transform belongs in tier 1 only if it can never change the
selector/text content the LLM cares about. Anything that *transforms* (vs
drops) belongs in tier 2.
"""

from __future__ import annotations

import re

from lxml import etree

# Framework attribute name patterns. Stored as a precompiled regex per AGENTS.md
# guidance on perf-sensitive paths and to keep ``set`` membership checks fast.
_FRAMEWORK_ATTR_PREFIXES: tuple[str, ...] = (
    'data-v-',  # Vue scoped style attributes (data-v-abc123)
    '_ngcontent-',  # Angular view encapsulation
    '_nghost-',  # Angular host encapsulation
    'ng-',  # Older Angular (ng-app, ng-if, ng-repeat...)
    'data-react',  # data-reactroot, data-react-helmet, etc.
    'data-svelte',
    ':',  # Vue/Alpine bindings (:class, :value)
    '@',  # Vue/Alpine event listeners (@click)
    'x-',  # Alpine.js directives (x-data, x-show)
    'wire:',  # Livewire
    'hx-',  # htmx
)

# Inline style and event handlers. Event handlers are everything matching
# ``on[a-z]+`` (onclick, onload, onmouseover, onerror, ...). Inline `style=`
# is dropped because it bloats tokens and never affects selector logic.
_EVENT_HANDLER_RE = re.compile(r'^on[a-z]+$')


def drop_scripts(root: etree._Element) -> int:
    """Drop ``<script>`` tags except JSON-LD and ``application/json`` payloads.

    JSON-LD often carries the canonical structured data the LLM wants
    (article body, product price, breadcrumbs). ``application/json``
    blocks are the conventional escape hatch sites use for hydration
    payloads which tier-2 ``cap_hydration_json`` then handles.
    """
    dropped = 0
    for script in list(root.iter('script')):
        script_type = (script.get('type') or '').strip().lower()
        if script_type in ('application/ld+json', 'application/json'):
            continue
        # Empty type, ``text/javascript``, ``module``, ``text/babel`` etc → drop.
        parent = script.getparent()
        if parent is not None:
            parent.remove(script)
            dropped += 1
    return dropped


def drop_comments(root: etree._Element) -> int:
    """Drop every ``<!-- ... -->`` HTML comment node."""
    dropped = 0
    for comment in list(root.iter(etree.Comment)):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)
            dropped += 1
    return dropped


def _is_framework_attr(name: str) -> bool:
    """Return True if attribute name matches a known framework decoration."""
    if name == 'style':
        return True
    if name == 'data-reactroot':
        return True
    if _EVENT_HANDLER_RE.match(name):
        return True
    return any(name.startswith(prefix) for prefix in _FRAMEWORK_ATTR_PREFIXES)


def strip_framework_attrs(root: etree._Element) -> int:
    """Remove framework decoration attrs and inline styles/event handlers.

    Targets:
      * ``style="..."`` (never used in selectors)
      * ``on*`` event handlers (``onclick``, ``onload`` ...)
      * Vue ``data-v-*``, ``:foo``, ``@bar``
      * Angular ``_ngcontent-*``, ``_nghost-*``, ``ng-*``
      * React ``data-reactroot`` / ``data-react-helmet``
      * Alpine ``x-*``, Livewire ``wire:*``, htmx ``hx-*``
    """
    stripped = 0
    for el in root.iter():
        if not isinstance(el.tag, str):  # comments, PIs handled elsewhere
            continue
        # ``etree`` attribs is a live view; collect names first.
        names_to_drop = [name for name in el.attrib if _is_framework_attr(name)]
        for name in names_to_drop:
            del el.attrib[name]
            stripped += 1
    return stripped


# Layout / responsive-image / loading-hint attrs that never affect the
# selector engine (parsel.css doesn't read them) but cost real tokens. The
# discovery LLM also doesn't need them — it picks selectors from class/id/
# tag/data-* signals.
_LAYOUT_NOISE_ATTRS: frozenset[str] = frozenset(
    {
        # Responsive image variants — large, never selectors.
        'srcset',
        'sizes',
        'imagesrcset',
        'imagesizes',
        # Image / iframe loading hints.
        'loading',
        'decoding',
        'fetchpriority',
        'referrerpolicy',
        'crossorigin',
        'integrity',
        # Legacy presentational table attrs (HTML4 hold-overs in a few
        # crusty corners of the web — Hacker News, government sites).
        'valign',
        'align',
        'cellpadding',
        'cellspacing',
        'border',
        'bgcolor',
        'bordercolor',
        'nowrap',
        'frame',
        'rules',
    }
)

# Meta tags worth keeping — everything else (og:*, twitter:*, theme-color,
# robots, generator, ...) is bulk that crowds the LLM input. Selectors
# don't target meta tags.
_KEEP_META_NAMES: frozenset[str] = frozenset(
    {
        'description',
        'viewport',
        'charset',
        'content-type',
    }
)
# We also keep meta tags carrying canonical entity hints because they
# can show up in JSON-LD-adjacent extraction prompts.
_KEEP_META_ITEMPROP: frozenset[str] = frozenset({'description', 'name', 'headline'})


def strip_layout_attrs(root: etree._Element) -> int:
    """Drop responsive-image / loading-hint / legacy-table attrs.

    None of these participate in selector logic and they account for
    meaningful byte counts on image-heavy pages (news sites with dense
    ``srcset`` ladders) and government/forum sites still using HTML4
    table layouts (Hacker News' homepage, irs.gov fragments).
    """
    stripped = 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        names_to_drop = [name for name in el.attrib if name in _LAYOUT_NOISE_ATTRS]
        for name in names_to_drop:
            del el.attrib[name]
            stripped += 1
    return stripped


def drop_link_and_meta_noise(root: etree._Element) -> int:
    """Drop ``<link>``, most ``<meta>``, and ``<noscript>`` tags from ``<head>``.

    Kept:
      * ``<link rel="canonical">`` — useful for entity grounding.
      * ``<meta charset>``, ``<meta name="viewport">``, ``<meta
        name="description">``, ``<meta http-equiv="content-type">`` —
        small, semantically meaningful, occasionally referenced in
        extraction.

    Dropped:
      * Other ``<link rel>`` (preload, prefetch, dns-prefetch, stylesheet,
        manifest, icon, alternate, apple-touch-icon, ...). None of these
        carry selector targets.
      * Other ``<meta>`` (og:*, twitter:*, robots, generator, theme-color,
        msapplication-*, csrf-token). Bulk noise that bloats the head.
      * ``<noscript>`` — the LLM operates on rendered HTML; the JS-disabled
        fallback is redundant.
    """
    dropped = 0
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        tag = el.tag
        if tag == 'link':
            rel = (el.get('rel') or '').strip().lower()
            if rel == 'canonical':
                continue
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                dropped += 1
        elif tag == 'meta':
            # Charset is special — attribute key, not name.
            if 'charset' in el.attrib:
                continue
            name = (el.get('name') or el.get('http-equiv') or '').strip().lower()
            itemprop = (el.get('itemprop') or '').strip().lower()
            if name in _KEEP_META_NAMES or itemprop in _KEEP_META_ITEMPROP:
                continue
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                dropped += 1
        elif tag == 'noscript':
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                dropped += 1
    return dropped


_WHITESPACE_RE = re.compile(r'[ \t\r\n]+')


def compact_whitespace(root: etree._Element) -> int:
    """Compact runs of whitespace in text/tail to a single space.

    Whitespace inside ``<pre>`` / ``<code>`` / ``<textarea>`` is preserved
    because their content is meaningful as written.
    """
    touched = 0
    preserve_tags = {'pre', 'code', 'textarea', 'script', 'style'}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        # Skip the *content* of preserve-formatting tags but still compact tails
        # (the whitespace AFTER the closing tag, which is outside its scope).
        in_preserve = any(isinstance(p.tag, str) and p.tag in preserve_tags for p in (el, *el.iterancestors()))
        if el.text and not in_preserve:
            new_text = _WHITESPACE_RE.sub(' ', el.text)
            if new_text != el.text:
                el.text = new_text
                touched += 1
        if el.tail:
            new_tail = _WHITESPACE_RE.sub(' ', el.tail)
            if new_tail != el.tail:
                el.tail = new_tail
                touched += 1
    return touched
