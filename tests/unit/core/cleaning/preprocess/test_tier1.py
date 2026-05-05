"""Tier-1 transform unit tests."""

from __future__ import annotations

from lxml import etree, html

from yosoi.core.cleaning.preprocess.tier1 import (
    compact_whitespace,
    drop_comments,
    drop_scripts,
    strip_framework_attrs,
)


def _parse(snippet: str) -> etree._Element:
    return html.fromstring(snippet)


# ---------------------------------------------------------------------------
# drop_scripts
# ---------------------------------------------------------------------------


def test_drop_scripts_removes_plain_script() -> None:
    root = _parse('<div><script>alert(1)</script><p>kept</p></div>')
    assert drop_scripts(root) == 1
    assert root.find('.//script') is None
    assert root.find('.//p') is not None


def test_drop_scripts_removes_text_javascript_type() -> None:
    root = _parse('<div><script type="text/javascript">x()</script></div>')
    assert drop_scripts(root) == 1
    assert root.find('.//script') is None


def test_drop_scripts_keeps_jsonld() -> None:
    root = _parse('<div><script type="application/ld+json">{"@type":"Article"}</script></div>')
    assert drop_scripts(root) == 0
    assert root.find('.//script') is not None


def test_drop_scripts_keeps_application_json() -> None:
    root = _parse('<div><script type="application/json">{"x":1}</script></div>')
    assert drop_scripts(root) == 0
    assert root.find('.//script') is not None


def test_drop_scripts_handles_uppercase_type() -> None:
    """``type`` is matched case-insensitively because real-world HTML mixes them."""
    root = _parse('<div><script type="Application/LD+JSON">{"@type":"Article"}</script></div>')
    assert drop_scripts(root) == 0


# ---------------------------------------------------------------------------
# drop_comments
# ---------------------------------------------------------------------------


def test_drop_comments_removes_html_comments() -> None:
    root = _parse('<div><!-- hidden --><p>kept</p><!-- also --></div>')
    assert drop_comments(root) == 2
    assert root.find('.//p') is not None


def test_drop_comments_idempotent() -> None:
    root = _parse('<div><!-- a --></div>')
    drop_comments(root)
    assert drop_comments(root) == 0


# ---------------------------------------------------------------------------
# strip_framework_attrs
# ---------------------------------------------------------------------------


def test_strip_framework_attrs_removes_vue_attrs() -> None:
    root = _parse('<div data-v-abc123="" :class="x" @click="f"><p data-v-abc123>x</p></div>')
    count = strip_framework_attrs(root)
    assert count == 4
    div = root if root.tag == 'div' else root.find('.//div')
    assert div is not None
    assert 'data-v-abc123' not in div.attrib
    assert ':class' not in div.attrib
    assert '@click' not in div.attrib


def test_strip_framework_attrs_removes_angular_attrs() -> None:
    root = _parse('<div _ngcontent-ng-c0="" _nghost-ng-c0="" ng-class="x" ng-if="y">a</div>')
    count = strip_framework_attrs(root)
    assert count == 4


def test_strip_framework_attrs_removes_react_root_and_handlers() -> None:
    root = _parse('<div data-reactroot onclick="f()" onmouseover="g()" onerror="h()">a</div>')
    count = strip_framework_attrs(root)
    assert count == 4


def test_strip_framework_attrs_removes_inline_style() -> None:
    root = _parse('<div style="color:red;font-size:12px">a</div>')
    assert strip_framework_attrs(root) == 1
    div = root if root.tag == 'div' else root.find('.//div')
    assert div is not None
    assert 'style' not in div.attrib


def test_strip_framework_attrs_keeps_class_and_id() -> None:
    """Selector-relevant attrs (``class``/``id``/``data-*`` non-framework) survive."""
    root = _parse('<div class="card" id="hero" data-product-id="42" style="color:red">a</div>')
    strip_framework_attrs(root)
    div = root if root.tag == 'div' else root.find('.//div')
    assert div is not None
    assert div.attrib['class'] == 'card'
    assert div.attrib['id'] == 'hero'
    assert div.attrib['data-product-id'] == '42'
    assert 'style' not in div.attrib


# ---------------------------------------------------------------------------
# compact_whitespace
# ---------------------------------------------------------------------------


def test_compact_whitespace_collapses_runs() -> None:
    root = _parse('<div>  hello\n\n   world  </div>')
    compact_whitespace(root)
    div = root if root.tag == 'div' else root.find('.//div')
    assert div is not None
    assert div.text == ' hello world '


def test_compact_whitespace_preserves_pre() -> None:
    root = _parse('<div><pre>  a\n   b</pre></div>')
    compact_whitespace(root)
    pre = root.find('.//pre')
    assert pre is not None
    assert pre.text == '  a\n   b'


# ---------------------------------------------------------------------------
# strip_layout_attrs (iteration 1 expansion)
# ---------------------------------------------------------------------------


def test_strip_layout_attrs_drops_responsive_image_attrs() -> None:
    from yosoi.core.cleaning.preprocess.tier1 import strip_layout_attrs

    root = _parse(
        '<img src="/x.jpg" srcset="/x@1x.jpg 1x, /x@2x.jpg 2x" sizes="100vw" '
        'loading="lazy" decoding="async" fetchpriority="low">'
    )
    count = strip_layout_attrs(root)
    assert count == 5
    img = root if root.tag == 'img' else root.find('.//img')
    assert img is not None
    assert 'srcset' not in img.attrib
    assert 'sizes' not in img.attrib
    assert 'loading' not in img.attrib
    assert 'decoding' not in img.attrib
    assert 'fetchpriority' not in img.attrib
    # Selector-relevant attrs survive.
    assert img.attrib['src'] == '/x.jpg'


def test_strip_layout_attrs_drops_legacy_table_attrs() -> None:
    from yosoi.core.cleaning.preprocess.tier1 import strip_layout_attrs

    root = _parse('<table valign="top" border="1" cellpadding="4"><tr align="left"><td>x</td></tr></table>')
    count = strip_layout_attrs(root)
    assert count == 4
    table = root.find('.//table') if root.tag != 'table' else root
    assert table is not None
    assert 'valign' not in table.attrib
    assert 'border' not in table.attrib


# ---------------------------------------------------------------------------
# drop_link_and_meta_noise (iteration 1 expansion)
# ---------------------------------------------------------------------------


def test_drop_link_and_meta_noise_keeps_canonical() -> None:
    from yosoi.core.cleaning.preprocess.tier1 import drop_link_and_meta_noise

    root = _parse(
        '<html><head>'
        '<link rel="stylesheet" href="/x.css">'
        '<link rel="canonical" href="https://example.com/page">'
        '<link rel="preload" href="/y.js">'
        '</head></html>'
    )
    drop_link_and_meta_noise(root)
    head = root.find('.//head')
    assert head is not None
    rels = [link.get('rel') for link in head.iter('link')]
    assert rels == ['canonical']


def test_drop_link_and_meta_noise_keeps_essential_meta() -> None:
    from yosoi.core.cleaning.preprocess.tier1 import drop_link_and_meta_noise

    root = _parse(
        '<html><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        '<meta name="description" content="Page description">'
        '<meta name="og:title" content="Title">'
        '<meta name="twitter:card" content="summary">'
        '<meta name="generator" content="WordPress">'
        '<meta name="theme-color" content="#fff">'
        '</head></html>'
    )
    drop_link_and_meta_noise(root)
    head = root.find('.//head')
    assert head is not None
    metas = list(head.iter('meta'))
    keys = {m.get('charset') or m.get('name') for m in metas}
    assert 'utf-8' in keys
    assert 'viewport' in keys
    assert 'description' in keys
    assert 'og:title' not in keys
    assert 'generator' not in keys
    assert 'theme-color' not in keys


def test_drop_link_and_meta_noise_drops_noscript() -> None:
    from yosoi.core.cleaning.preprocess.tier1 import drop_link_and_meta_noise

    root = _parse('<div><noscript>JS required</noscript><p>kept</p></div>')
    assert drop_link_and_meta_noise(root) == 1
    assert root.find('.//noscript') is None
    assert root.find('.//p') is not None
