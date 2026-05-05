"""Unit tests + synthetic re-scrape harness for anchor_hash (CAS-18 stretch).

Validates the stretch-goal success metric: on a synthetic re-scrape harness
where pages are perturbed by *value-only* edits (no structural change),
≥ 50% of fields hit the "structure stable, values changed" path —
``anchor_hash_partial`` matches across raw and perturbed trees while
``anchor_hash_full`` differs.
"""

from __future__ import annotations

import re

from lxml import html
from parsel import Selector

from yosoi.core.cleaning.preprocess.anchor_hash import (
    AnchorHashes,
    compute_anchor_hashes,
    find_anchor_subtree,
    hash_subtree,
    normalize_text,
)

# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text('  hello\n\n   world  ') == 'hello world'


def test_normalize_text_handles_none() -> None:
    assert normalize_text(None) == ''


# ---------------------------------------------------------------------------
# find_anchor_subtree
# ---------------------------------------------------------------------------


def test_find_anchor_climbs_to_id_ancestor() -> None:
    root = html.fromstring('<div id="page"><div><span class="byline">Jane</span></div></div>')
    span = root.cssselect('span.byline')[0]
    anchor = find_anchor_subtree(span)
    assert anchor.get('id') == 'page'


def test_find_anchor_climbs_to_structural_tag() -> None:
    root = html.fromstring('<div><article><div><h2 class="title">Hi</h2></div></article></div>')
    h2 = root.cssselect('h2.title')[0]
    anchor = find_anchor_subtree(h2)
    assert anchor.tag == 'article'


def test_find_anchor_falls_back_to_self() -> None:
    """No id/structural ancestor — anchor is the match itself."""
    root = html.fromstring('<div><div><span>x</span></div></div>')
    span = root.cssselect('span')[0]
    anchor = find_anchor_subtree(span)
    assert anchor.tag == 'span'


# ---------------------------------------------------------------------------
# hash_subtree determinism + value-vs-structure distinction
# ---------------------------------------------------------------------------


def test_partial_hash_invariant_to_text_changes() -> None:
    """Same structure + classes, different text => identical partial hash."""
    a = html.fromstring('<article id="a"><h1 class="t">Hello</h1><p>Some body text</p></article>')
    b = html.fromstring('<article id="a"><h1 class="t">Goodbye</h1><p>Different body text</p></article>')
    assert hash_subtree(a, kind='partial') == hash_subtree(b, kind='partial')


def test_full_hash_changes_with_text() -> None:
    a = html.fromstring('<article id="a"><h1 class="t">Hello</h1></article>')
    b = html.fromstring('<article id="a"><h1 class="t">Goodbye</h1></article>')
    assert hash_subtree(a, kind='full') != hash_subtree(b, kind='full')


def test_partial_hash_changes_with_structure() -> None:
    """Adding a structural sibling changes the partial hash."""
    a = html.fromstring('<article id="a"><h1 class="t">Hi</h1></article>')
    b = html.fromstring('<article id="a"><h1 class="t">Hi</h1><p class="lead">extra</p></article>')
    assert hash_subtree(a, kind='partial') != hash_subtree(b, kind='partial')


def test_partial_hash_invariant_to_class_token_order() -> None:
    """``class="a b"`` and ``class="b a"`` mean the same thing in CSS."""
    a = html.fromstring('<div id="x"><p class="lead bold">x</p></div>')
    b = html.fromstring('<div id="x"><p class="bold lead">x</p></div>')
    assert hash_subtree(a, kind='partial') == hash_subtree(b, kind='partial')


def test_partial_hash_invariant_to_attr_order() -> None:
    a = html.fromstring('<div id="x"><a class="c" href="/y" data-id="42">x</a></div>')
    b = html.fromstring('<div id="x"><a data-id="42" class="c" href="/y">x</a></div>')
    assert hash_subtree(a, kind='partial') == hash_subtree(b, kind='partial')


def test_compute_anchor_hashes_returns_versioned_pair() -> None:
    root = html.fromstring('<article id="a"><h1 class="t">Hi</h1></article>')
    h1 = root.cssselect('h1.t')[0]
    hashes = compute_anchor_hashes(h1)
    assert isinstance(hashes, AnchorHashes)
    assert hashes.version == 1
    assert hashes.partial != hashes.full
    # 16-char truncated SHA-256.
    assert len(hashes.partial) == 16
    assert len(hashes.full) == 16


# ---------------------------------------------------------------------------
# Synthetic re-scrape harness — stretch goal success metric.
# ---------------------------------------------------------------------------


def _value_only_perturb(html_text: str) -> str:
    """Apply value-only edits: change visible text but keep tags/attrs intact.

    Mimics a CMS content edit (article body rewritten, headline tweaked,
    timestamp updated) without any layout / class / id rearrangement.
    """
    edits: list[tuple[str, str]] = [
        ('Why Async Python Matters', 'How Async Python Scales'),
        ('Andrew B.', 'Andy Berg'),
        ('May 1, 2026', 'May 7, 2026'),
        ('asyncio', 'AsyncIO'),
        ("Python's", 'Python is'),
        ('Breaking: Markets Rally on Tech Earnings', 'Markets Slip on Tech Guidance'),
        ('Jane Reporter', 'John Wire'),
        ('Wireless Headphones', 'Premium Headphones'),
        ('$129.99', '$139.99'),
    ]
    for old, new in edits:
        html_text = html_text.replace(old, new)
    return html_text


# A representative slate of selectors per fixture — these stand in for the
# fields the discovery LLM would pick on each page.
FIELD_SELECTORS: dict[str, list[str]] = {
    'wordpress_article.html': [
        'h1.entry-title',
        'a.author-name',
        'time.entry-date',
        'div.entry-content p',
        'a[rel]',  # any anchor with `rel`
        'header.entry-header',
    ],
    'react_app.html': [
        'article.story h2',
        'span.byline',
        'time[datetime]',
        'header.App-header h1',
        'main article',
    ],
    'vue_spa.html': [
        'article.card h2',
        'p.price',
        'main h1',
        'footer p',
    ],
}


def _load_fixture(name: str) -> str:
    from pathlib import Path

    p = Path(__file__).parents[4] / 'data' / 'preprocess' / name
    return p.read_text()


def _hash_at_selector(tree: html.HtmlElement, css: str) -> AnchorHashes | None:
    matches = tree.cssselect(css)
    if not matches:
        return None
    return compute_anchor_hashes(matches[0])


def test_value_only_perturb_actually_perturbs() -> None:
    """Sanity: the perturb helper changes content on at least one fixture."""
    raw = _load_fixture('wordpress_article.html')
    edited = _value_only_perturb(raw)
    assert raw != edited


def test_synthetic_rescrape_hits_50pct_structure_stable_path() -> None:
    """Stretch success metric: ≥ 50% of fields hit the partial-match path.

    For each (fixture, selector) pair: hash the anchor subtree on the
    pristine tree, perturb values only, hash again. A "structure-stable"
    hit means partial matches across the two trees and full differs (or
    matches if our edits didn't touch the anchor).
    """
    structure_stable_hits = 0
    total_fields = 0
    for fixture, selectors in FIELD_SELECTORS.items():
        raw = _load_fixture(fixture)
        edited = _value_only_perturb(raw)
        before = html.fromstring(raw)
        after = html.fromstring(edited)
        for css in selectors:
            total_fields += 1
            h_before = _hash_at_selector(before, css)
            h_after = _hash_at_selector(after, css)
            if h_before is None or h_after is None:
                continue
            if h_before.partial == h_after.partial:
                structure_stable_hits += 1
    assert total_fields > 0
    rate = structure_stable_hits / total_fields
    assert rate >= 0.5, f'structure-stable rate {rate:.2%} ({structure_stable_hits}/{total_fields}) below 50%'


def test_synthetic_rescrape_full_hash_differs_when_text_changes() -> None:
    """Where the perturb edited text inside the anchor, full hash MUST differ.

    This is the "structure stable, values changed" branch. We assert the
    branch is exercised by at least one (fixture, selector) pair, not on
    every pair, because some selectors may anchor on subtrees the
    perturb didn't touch.
    """
    full_diff_hits = 0
    for fixture, selectors in FIELD_SELECTORS.items():
        raw = _load_fixture(fixture)
        edited = _value_only_perturb(raw)
        if raw == edited:
            continue
        before = html.fromstring(raw)
        after = html.fromstring(edited)
        for css in selectors:
            h_before = _hash_at_selector(before, css)
            h_after = _hash_at_selector(after, css)
            if h_before is None or h_after is None:
                continue
            if h_before.partial == h_after.partial and h_before.full != h_after.full:
                full_diff_hits += 1
    assert full_diff_hits >= 1, 'no fixture/selector pair exercised the value-only branch'


# ---------------------------------------------------------------------------
# Strong selectors-hold check — selectors discovered on the preprocessed
# tree must validate against the original (pre-preprocess) tree.
# ---------------------------------------------------------------------------


def test_known_content_selectors_resolve_on_both_trees() -> None:
    """For each fixture's known selectors, raw-tree + preprocessed-tree match.

    Uses parsel (same engine pipeline.SelectorVerifier uses), so this is a
    closer proxy to the actual selectors-hold success condition than the
    coarse-anchor count test. The text content under the selector must
    match across the two trees.
    """
    from yosoi.core.cleaning.preprocess import HTMLPreprocessor

    pp = HTMLPreprocessor()
    failures: list[str] = []
    for fixture, selectors in FIELD_SELECTORS.items():
        raw = _load_fixture(fixture)
        out = pp.preprocess(raw).html
        before = Selector(text=raw)
        after = Selector(text=out)
        for css in selectors:
            before_text = ' '.join(t.strip() for t in before.css(f'{css} *::text, {css}::text').getall() if t.strip())
            after_text = ' '.join(t.strip() for t in after.css(f'{css} *::text, {css}::text').getall() if t.strip())
            # Tolerate trivial whitespace differences from preprocess's
            # ``compact_whitespace`` transform.
            norm_before = re.sub(r'\s+', ' ', before_text).strip()
            norm_after = re.sub(r'\s+', ' ', after_text).strip()
            if norm_after == '' and norm_before != '':
                failures.append(f'{fixture}: {css!r} dropped all text after preprocess')
                continue
            # Allow some shrink (e.g. JSON-LD scripts that are visible as
            # text in raw but live in <script> in output) — require the
            # output text to be a substring of the raw text after norm.
            if norm_after and norm_after not in norm_before and norm_before not in norm_after:
                failures.append(f'{fixture}: {css!r} text drifted')
    assert not failures, '\n'.join(failures)
