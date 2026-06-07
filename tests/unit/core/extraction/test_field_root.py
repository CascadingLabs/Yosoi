"""Field-level root: a field resolves RELATIVE to its parent region (extractor)."""

from __future__ import annotations

import yosoi as ys
from yosoi.core.extraction.extractor import ContentExtractor
from yosoi.models.selectors import FieldSelectors, SelectorEntry

# Sponsored block and two organic blocks that share the same <a><h3> shape — the only
# discriminator is which region a field is rooted under.
_HTML = """<body>
  <div class="uEierd"><span>Sponsored</span>
    <a href="https://ad.example/lp"><h3>Sponsored Premier Home Care</h3></a></div>
  <div class="MjjYud"><a href="https://organic.example/a"><h3>Organic CareBuilders</h3></a></div>
  <div class="MjjYud"><a href="https://organic.example/b"><h3>Organic Two</h3></a></div>
</body>"""


class _Row(ys.Contract):
    """A SERP result row."""

    url: str = ys.Url()
    title: str = ys.Title()


def _smap(root_css: str) -> dict:
    # Same SIMPLE leaf selectors for both regions; only the root differs.
    return {
        'url': FieldSelectors(
            primary=SelectorEntry(value='a::attr(href)'), root=SelectorEntry(value=root_css)
        ).model_dump(exclude_none=True),
        'title': FieldSelectors(primary=SelectorEntry(value='h3'), root=SelectorEntry(value=root_css)).model_dump(
            exclude_none=True
        ),
    }


def test_root_scopes_field_to_organic_region() -> None:
    out = ContentExtractor(contract=_Row).extract_content_with_html('', _HTML, _smap('.MjjYud'))
    assert out is not None
    assert out['url'] == 'https://organic.example/a'  # first organic, NOT the ad
    assert 'Organic' in str(out['title'])


def test_root_scopes_field_to_sponsored_region() -> None:
    out = ContentExtractor(contract=_Row).extract_content_with_html('', _HTML, _smap('.uEierd'))
    assert out is not None
    assert out['url'] == 'https://ad.example/lp'  # the ad, NOT an organic result
    assert 'Sponsored' in str(out['title'])


def test_root_with_no_match_yields_no_value() -> None:
    # Root set but matches nothing -> the field has no value in its region; no silent
    # fallback to the whole document.
    out = ContentExtractor(contract=_Row).extract_content_with_html('', _HTML, _smap('.no-such-region'))
    assert out is None


def test_no_root_still_works_unscoped() -> None:
    smap = {
        'url': {'primary': {'type': 'css', 'value': '.uEierd a::attr(href)'}},
        'title': {'primary': {'type': 'css', 'value': '.uEierd h3'}},
    }
    out = ContentExtractor(contract=_Row).extract_content_with_html('', _HTML, smap)
    assert out is not None
    assert out['url'] == 'https://ad.example/lp'
