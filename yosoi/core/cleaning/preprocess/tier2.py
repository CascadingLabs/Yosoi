"""Tier-2 transforms: transform-don't-drop.

Tier-2 reshapes content the LLM might still want, instead of removing it.
Each transform returns the count of nodes it touched.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from lxml import etree

# Query parameter prefixes / exact names that are pure tracking — Google
# Analytics, Facebook click ids, Mailchimp campaign tokens, share-source
# fingerprints. Stripping them shortens hrefs without changing the
# resource the URL points at, so selectors that match on the *path* still
# resolve. Selectors that match on a tracking param verbatim
# (``a[href*="utm_source"]``) would break — but those are pathological
# and the spike has explicit license to drop tracking.
_TRACKING_PARAM_PREFIXES: tuple[str, ...] = (
    'utm_',
    '_ga',
    'mc_',
    'igsh',
    'igshid',
)
_TRACKING_PARAM_EXACT: frozenset[str] = frozenset(
    {
        'fbclid',
        'gclid',
        'gclsrc',
        'dclid',
        'msclkid',
        'yclid',
        'wickedid',
        'ref',
        'ref_src',
        'ref_url',
        'referrer',
        'feature',
        'spm',
        'share',
        'sharedtime',
        'shared',
        '_hsenc',
        '_hsmi',
        'ck_subscriber_id',
    }
)

# Hard cap for inline hydration JSON (Next.js ``__NEXT_DATA__``, Nuxt
# ``__NUXT__``, etc.). 50KB ≈ 12.5K tokens at 4 chars/token — past that the
# tail rarely buys the LLM useful structure but blows up the prompt budget.
HYDRATION_JSON_BYTE_CAP = 50_000
ELISION_MARKER = '/* yosoi:elided due to size cap */'

# Inline SVG geometry tags. Anything not in this set is preserved (titles,
# descriptions, text labels — semantic content the LLM may need).
_SVG_GEOMETRY_TAGS = {
    'path',
    'rect',
    'circle',
    'ellipse',
    'line',
    'polyline',
    'polygon',
    'g',
    'defs',
    'use',
    'symbol',
    'clipPath',
    'mask',
    'pattern',
    'linearGradient',
    'radialGradient',
    'stop',
    'filter',
    'feGaussianBlur',
    'feOffset',
    'feBlend',
    'feFlood',
    'feComposite',
    'feMerge',
    'feMergeNode',
    'feColorMatrix',
}
_SVG_KEEP_TAGS = {'title', 'desc', 'text', 'tspan', 'textPath'}


def hoist_jsonld(root: etree._Element) -> int:
    """Move every JSON-LD ``<script>`` to the top of ``<head>`` (or root).

    JSON-LD blocks are commonly emitted at the bottom of ``<body>`` by SEO
    plugins. The LLM benefits from seeing them early because they describe
    the page's canonical entities (Article, Product, BreadcrumbList) before
    the noisy content tree.

    Marks each hoisted block with ``data-yosoi-hoisted="1"`` so tests and
    debug dumps can spot what moved.
    """
    jsonld_scripts = [s for s in root.iter('script') if (s.get('type') or '').strip().lower() == 'application/ld+json']
    if not jsonld_scripts:
        return 0

    head = root.find('.//head')
    target = head if head is not None else root

    # Reverse insertion order so original document order is preserved at the top.
    for script in reversed(jsonld_scripts):
        parent = script.getparent()
        if parent is not None:
            parent.remove(script)
        script.set('data-yosoi-hoisted', '1')
        target.insert(0, script)
    return len(jsonld_scripts)


def stub_svg_geometry(root: etree._Element) -> int:
    """Replace SVG geometry with a stub but keep title/desc/text.

    Strips ``<path d="...">``, ``<rect ...>`` and friends — geometry data is
    purely visual and never useful to a selector-discovery LLM. Preserves
    ``<title>``, ``<desc>``, and ``<text>`` because those carry the
    accessible label and any rendered words (chart axis labels, icon names).

    For each ``<svg>`` we also drop the geometry attrs on the root element
    (``viewBox``, ``xmlns``, ``width``, ``height``) and replace its tag
    contents with kept children only, leaving a marker attribute so a
    reader can tell something was stubbed.
    """
    touched = 0
    # iter() returns elements in document order — collect first to avoid
    # mutating-during-iteration bugs on lxml.
    svgs = [el for el in root.iter() if isinstance(el.tag, str) and _localname(el.tag) == 'svg']
    for svg in svgs:
        # Walk every descendant; remove anything in geometry tags, keep keep_tags.
        # Iterate in reverse to handle nested removals safely.
        for child in list(svg.iter()):
            if child is svg:
                continue
            local = _localname(child.tag) if isinstance(child.tag, str) else ''
            if local in _SVG_KEEP_TAGS:
                continue
            if local in _SVG_GEOMETRY_TAGS:
                parent = child.getparent()
                if parent is not None:
                    parent.remove(child)
                    touched += 1
        # Strip non-semantic attrs from the svg root itself. lxml's HTML
        # parser lowercases attribute names so we list the lowercased forms.
        for attr in (
            'viewbox',
            'xmlns',
            'xmlns:xlink',
            'width',
            'height',
            'preserveaspectratio',
            'fill',
            'stroke',
            'stroke-width',
        ):
            if attr in svg.attrib:
                del svg.attrib[attr]
        svg.set('data-yosoi-stub', '1')
    return touched


def cap_hydration_json(root: etree._Element, byte_cap: int = HYDRATION_JSON_BYTE_CAP) -> int:
    """Cap large ``application/json`` hydration blobs at ``byte_cap`` bytes.

    Targets the surviving tier-1 ``<script type="application/json">`` and
    JSON-LD blocks — anything whose text payload exceeds ``byte_cap`` is
    truncated and a clear elision marker is appended so the LLM can tell
    the trailing data was removed (and not just malformed JSON).

    Truncation respects UTF-8 boundaries.
    """
    capped = 0
    for script in root.iter('script'):
        script_type = (script.get('type') or '').strip().lower()
        if script_type not in ('application/json', 'application/ld+json'):
            continue
        text = script.text or ''
        if len(text.encode('utf-8')) <= byte_cap:
            continue
        # Truncate by byte count, then back off to the last valid UTF-8 codepoint.
        encoded = text.encode('utf-8')[:byte_cap]
        # Walk backward to land on a valid codepoint boundary.
        while encoded and (encoded[-1] & 0xC0) == 0x80:
            encoded = encoded[:-1]
        try:
            head = encoded.decode('utf-8')
        except UnicodeDecodeError:
            head = encoded.decode('utf-8', errors='ignore')
        script.text = f'{head}\n{ELISION_MARKER}'
        script.set('data-yosoi-elided', '1')
        capped += 1
    return capped


def _is_tracking_param(name: str) -> bool:
    name_lc = name.lower()
    if name_lc in _TRACKING_PARAM_EXACT:
        return True
    return any(name_lc.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)


def _strip_tracking_from_url(url: str) -> str:
    """Return ``url`` with tracking-only query params removed.

    Keeps fragment + path + non-tracking query params intact. Robust
    against malformed URLs (``mailto:``, ``javascript:``, anchors) — these
    short-circuit through ``urlsplit`` and pass back unchanged.
    """
    if not url or '?' not in url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_param(k)]
    new_query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


# Per-attribute byte cap — anything bigger gets replaced with an elision
# marker. Selectors rarely match exact long values; the LLM never needs
# them. Worst-case offenders seen in the wild:
#   * Reddit's ``data-cachedhtml`` (140 KB of embedded escaped HTML)
#   * Custom-element scripts stuffing serialized state into ``data-*``
#   * ``alt`` text on hero images that are paragraph-length descriptions
#   * ``title`` tooltips containing entire bibliographic citations
ATTR_BYTE_CAP = 1024
ATTR_ELISION_TEMPLATE = '[yosoi:elided:{n}b]'

# Attributes that are NEVER allowed to be elided because their *value*
# matters to selector matching or to downstream extraction. Class/id are
# obvious; href/src can be matched on prefix. data-* is intentionally
# included in the elision pass (selectors usually only check presence).
_ATTR_VALUE_PRESERVE: frozenset[str] = frozenset(
    {'class', 'id', 'href', 'src', 'name', 'type', 'role', 'datetime', 'value'}
)


def cap_oversized_attrs(root: etree._Element, byte_cap: int = ATTR_BYTE_CAP) -> int:
    """Replace attribute values that exceed ``byte_cap`` with an elision marker.

    Keeps the attribute *name* (so ``[data-cachedhtml]`` presence matchers
    still resolve) but drops the value so the LLM does not pay tokens for
    serialized HTML/JSON payloads stuffed into a single attribute. Whitelist
    in :data:`_ATTR_VALUE_PRESERVE` skips selector-relevant attrs.
    """
    capped = 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for name in list(el.attrib):
            if name in _ATTR_VALUE_PRESERVE:
                continue
            value = el.attrib[name]
            if len(value.encode('utf-8')) <= byte_cap:
                continue
            el.set(name, ATTR_ELISION_TEMPLATE.format(n=len(value)))
            capped += 1
    return capped


def trim_url_tracking_params(root: etree._Element) -> int:
    """Strip tracking query params from ``href`` and ``src`` attributes.

    Touches every element with one of the URL-bearing attrs. Returns the
    count of attributes whose value actually changed (idempotent on second
    pass).
    """
    touched = 0
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in ('href', 'src', 'action', 'data-href', 'data-url'):
            value = el.get(attr)
            if value is None:
                continue
            new_value = _strip_tracking_from_url(value)
            if new_value != value:
                el.set(attr, new_value)
                touched += 1
    return touched


def _localname(tag: str) -> str:
    """Strip XML namespace from a tag, e.g. ``{http://...}svg`` → ``svg``."""
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag
