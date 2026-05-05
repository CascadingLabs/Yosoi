"""Tier-2 transform unit tests."""

from __future__ import annotations

import json

from lxml import etree, html

from yosoi.core.cleaning.preprocess.tier2 import (
    ELISION_MARKER,
    HYDRATION_JSON_BYTE_CAP,
    cap_hydration_json,
    hoist_jsonld,
    stub_svg_geometry,
)


def _parse(snippet: str) -> etree._Element:
    return html.fromstring(snippet)


# ---------------------------------------------------------------------------
# hoist_jsonld
# ---------------------------------------------------------------------------


def test_hoist_jsonld_moves_to_head_top() -> None:
    root = _parse(
        '<html><head><meta charset="utf-8"></head>'
        '<body><p>x</p>'
        '<script type="application/ld+json">{"@type":"Article"}</script>'
        '</body></html>'
    )
    assert hoist_jsonld(root) == 1
    head = root.find('.//head')
    assert head is not None
    first_child = head[0]
    assert first_child.tag == 'script'
    assert first_child.get('data-yosoi-hoisted') == '1'


def test_hoist_jsonld_preserves_document_order_among_blocks() -> None:
    root = _parse(
        '<html><head></head><body>'
        '<script type="application/ld+json">{"@type":"A"}</script>'
        '<script type="application/ld+json">{"@type":"B"}</script>'
        '</body></html>'
    )
    hoist_jsonld(root)
    head = root.find('.//head')
    assert head is not None
    payloads = [s.text for s in head.iter('script') if s.get('data-yosoi-hoisted') == '1']
    assert '"A"' in payloads[0]
    assert '"B"' in payloads[1]


def test_hoist_jsonld_no_op_when_absent() -> None:
    root = _parse('<html><head></head><body><p>x</p></body></html>')
    assert hoist_jsonld(root) == 0


# ---------------------------------------------------------------------------
# stub_svg_geometry
# ---------------------------------------------------------------------------


def test_stub_svg_geometry_drops_paths() -> None:
    root = _parse(
        '<div><svg viewBox="0 0 10 10" width="10" height="10">'
        '<title>chart</title><desc>line chart</desc>'
        '<path d="M0 0L1 1"/><path d="M1 1L2 2"/>'
        '<text x="5" y="5">label</text>'
        '</svg></div>'
    )
    touched = stub_svg_geometry(root)
    assert touched == 2
    svg = root.find('.//svg')
    assert svg is not None
    assert svg.find('title') is not None
    assert svg.find('desc') is not None
    assert svg.find('text') is not None
    assert svg.find('path') is None
    assert svg.get('data-yosoi-stub') == '1'


def test_stub_svg_geometry_strips_geometry_attrs() -> None:
    root = _parse(
        '<div><svg viewBox="0 0 10 10" width="10" height="10" xmlns="ns" fill="red"><title>x</title></svg></div>'
    )
    stub_svg_geometry(root)
    svg = root.find('.//svg')
    assert svg is not None
    # Cleared geometry attrs (lxml lowercases on parse)
    assert 'viewbox' not in svg.attrib
    assert 'width' not in svg.attrib
    assert 'height' not in svg.attrib
    assert 'fill' not in svg.attrib


# ---------------------------------------------------------------------------
# cap_hydration_json
# ---------------------------------------------------------------------------


def test_cap_hydration_json_no_op_under_cap() -> None:
    payload = json.dumps({'small': True})
    root = _parse(f'<div><script type="application/json">{payload}</script></div>')
    assert cap_hydration_json(root) == 0


def test_cap_hydration_json_truncates_above_cap() -> None:
    payload = json.dumps({'big': 'x' * (HYDRATION_JSON_BYTE_CAP + 1000)})
    root = _parse(f'<div><script type="application/json">{payload}</script></div>')
    assert cap_hydration_json(root) == 1
    script = root.find('.//script')
    assert script is not None
    assert script.text is not None
    assert ELISION_MARKER in script.text
    # Truncated body must fit within the cap + ~one elision marker line.
    assert len(script.text.encode('utf-8')) <= HYDRATION_JSON_BYTE_CAP + len(ELISION_MARKER) + 4
    assert script.get('data-yosoi-elided') == '1'


def test_cap_hydration_json_caps_jsonld_too() -> None:
    payload = json.dumps({'@type': 'X', 'data': 'y' * (HYDRATION_JSON_BYTE_CAP + 100)})
    root = _parse(f'<div><script type="application/ld+json">{payload}</script></div>')
    assert cap_hydration_json(root) == 1


# ---------------------------------------------------------------------------
# trim_url_tracking_params (iteration 1 expansion)
# ---------------------------------------------------------------------------


def test_trim_url_tracking_params_strips_utm() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import trim_url_tracking_params

    root = _parse('<a href="https://example.com/path?utm_source=newsletter&utm_medium=email&id=42">x</a>')
    assert trim_url_tracking_params(root) == 1
    a = root.find('.//a') if root.tag != 'a' else root
    assert a is not None
    assert 'utm_source' not in a.get('href', '')
    assert 'id=42' in a.get('href', '')


def test_trim_url_tracking_params_strips_fbclid_and_gclid() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import trim_url_tracking_params

    root = _parse('<a href="https://x.com/p?fbclid=abc&gclid=def&q=hi">x</a>')
    trim_url_tracking_params(root)
    a = root.find('.//a') if root.tag != 'a' else root
    assert a is not None
    assert 'fbclid' not in a.get('href', '')
    assert 'gclid' not in a.get('href', '')
    assert 'q=hi' in a.get('href', '')


def test_trim_url_tracking_params_no_op_on_clean_url() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import trim_url_tracking_params

    root = _parse('<a href="https://example.com/path?id=42">x</a>')
    assert trim_url_tracking_params(root) == 0


def test_trim_url_tracking_params_handles_special_schemes() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import trim_url_tracking_params

    root = _parse('<div><a href="mailto:a@b.com">m</a><a href="javascript:void(0)">j</a></div>')
    # No tracking params on mailto/javascript URIs — no-op.
    assert trim_url_tracking_params(root) == 0


# ---------------------------------------------------------------------------
# cap_oversized_attrs (iteration 2 expansion)
# ---------------------------------------------------------------------------


def test_cap_oversized_attrs_replaces_huge_data_attr() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import (
        ATTR_BYTE_CAP,
        ATTR_ELISION_TEMPLATE,
        cap_oversized_attrs,
    )

    big = 'x' * (ATTR_BYTE_CAP + 100)
    root = _parse(f'<div data-cachedhtml="{big}"><p>kept</p></div>')
    assert cap_oversized_attrs(root) == 1
    div = root if root.tag == 'div' else root.find('.//div')
    assert div is not None
    value = div.attrib['data-cachedhtml']
    assert value == ATTR_ELISION_TEMPLATE.format(n=len(big))


def test_cap_oversized_attrs_preserves_class_id_href() -> None:
    """Selector-relevant attrs are never elided even when long."""
    from yosoi.core.cleaning.preprocess.tier2 import ATTR_BYTE_CAP, cap_oversized_attrs

    long_class = 'x' * (ATTR_BYTE_CAP + 100)
    long_href = '/p?' + '&'.join(f'k{i}=v{i}' for i in range((ATTR_BYTE_CAP // 6) + 100))
    root = _parse(f'<a class="{long_class}" href="{long_href}" id="{long_class}">x</a>')
    cap_oversized_attrs(root)
    a = root if root.tag == 'a' else root.find('.//a')
    assert a is not None
    assert a.attrib['class'] == long_class
    assert a.attrib['id'] == long_class
    assert a.attrib['href'] == long_href


def test_cap_oversized_attrs_no_op_under_cap() -> None:
    from yosoi.core.cleaning.preprocess.tier2 import cap_oversized_attrs

    root = _parse('<div data-meta="short">x</div>')
    assert cap_oversized_attrs(root) == 0
