"""Shared anchor identity, including composite keys used across modalities."""

from __future__ import annotations

from lxml import html

from yosoi.observations import anchoring
from yosoi.observations.index.addressing import anchor_address, format_address, parse_address


def test_two_non_unique_attributes_can_form_one_unique_composite_anchor() -> None:
    elements = (
        ('link', (('name', 'Home'), ('role', 'link'))),
        ('heading', (('name', 'Home'), ('role', 'heading'))),
        ('link', (('name', 'Docs'), ('role', 'link'))),
        ('heading', (('name', 'Welcome'), ('role', 'heading'))),
    )
    census = anchoring.build_census(elements)

    key = anchoring.usable_anchor(*elements[0], census)

    assert key == '@{name=Home&role=link}'
    assert anchoring.anchor_tier(key) == 'composite'
    locator = format_address(anchor_address(key))
    address = parse_address(locator)
    assert address.segments[0].anchor == key
    assert address.segments[0].path == '//*[@name="Home" and @role="link"]'


def test_a_composite_anchor_xpath_selects_the_exact_html_element() -> None:
    document = html.fromstring(
        '<main><a name="Home" role="link">home</a><h1 name="Home" role="heading">title</h1></main>'
    )
    key = anchoring.composite_anchor_key((('name', 'Home'), ('role', 'link')))

    assert key is not None
    path = anchor_address(key).segments[0].path
    assert [element.text for element in document.xpath(path)] == ['home']


def test_a_composite_anchor_is_refused_when_its_delimiter_cannot_round_trip() -> None:
    assert anchoring.composite_anchor_key((('name', 'A&B'), ('role', 'link'))) is None
