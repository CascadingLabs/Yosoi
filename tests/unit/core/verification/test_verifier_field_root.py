"""Root-relative verification: a (root, leaf) verifies only if the leaf resolves UNDER root."""

from __future__ import annotations

from parsel import Selector

from yosoi.core.verification.verifier import SelectorVerifier
from yosoi.models.selectors import FieldSelectors, SelectorEntry

_HTML = """<body>
  <div class="uEierd"><a href="https://ad.example/lp"><h3 class="adonly">Ad</h3></a></div>
  <div class="MjjYud"><a href="https://organic.example/a"><h3 class="orgonly">Org</h3></a></div>
</body>"""


def _fs(primary: str, root: str | None = None) -> FieldSelectors:
    return FieldSelectors(
        primary=SelectorEntry(value=primary),
        root=SelectorEntry(value=root) if root else None,
    )


def _verify(field_selectors: FieldSelectors, field: str = 'url') -> str:
    return SelectorVerifier()._verify_field(Selector(text=_HTML), field, field_selectors).status


def test_leaf_verifies_under_its_root() -> None:
    assert _verify(_fs('a::attr(href)', root='.uEierd')) == 'verified'


def test_root_that_matches_nothing_fails() -> None:
    assert _verify(_fs('a::attr(href)', root='.no-such-region')) == 'failed'


def test_leaf_under_wrong_root_fails() -> None:
    # `.orgonly` exists only in the organic block; rooted under the ad block it must NOT verify.
    assert _verify(_fs('.orgonly', root='.uEierd'), field='title') == 'failed'


def test_leaf_under_correct_root_verifies() -> None:
    assert _verify(_fs('.orgonly', root='.MjjYud'), field='title') == 'verified'


def test_no_root_verifies_against_whole_document() -> None:
    assert _verify(_fs('a::attr(href)')) == 'verified'
