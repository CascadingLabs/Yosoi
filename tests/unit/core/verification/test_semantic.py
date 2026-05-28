"""Tests for SemanticValidator — type-aware extraction sanity checks.

These verify the validator catches the EXACT failure modes that ship-blocked
reddit_ted on 2026-05-28 (CAS-78), so a regression that re-opens that hole
trips a test instead of escaping to a live LLM round-trip.
"""

from __future__ import annotations

import yosoi as ys
from yosoi.core.verification.semantic import (
    FieldIssue,
    SemanticValidator,
    _looks_datetime_like,
    _looks_numeric,
    _looks_url_like,
    render_feedback,
)


class RedditPost(ys.Contract):
    """Same shape as examples/opencode_voidcrawl/reddit_ted.py — the smoke-target contract."""

    title: str = ys.Title()
    author: str = ys.Author()
    score: int | None = ys.Count()
    comment_count: int | None = ys.Count()
    permalink: str = ys.Url()


# ---------------------------------------------------------------------------
# Per-field length caps
# ---------------------------------------------------------------------------


def test_title_under_cap_passes() -> None:
    v = SemanticValidator(RedditPost)
    record = {'title': 'A reasonable post title', 'author': 'u/x', 'permalink': '/r/x/abc'}
    issues = v.validate(record)
    titles = [i for i in issues if i.field == 'title']
    assert titles == []


def test_title_over_500_chars_flagged_as_too_broad() -> None:
    """The score-→-shreddit-post regression: returns 2 kB of card text instead
    of the title's ~80 chars. The validator should catch length > 500."""
    v = SemanticValidator(RedditPost)
    garbage_title = (
        'Facebook deleted 15m hate speech posts… ' + 'X ' * 1_500  # ~3 KB
    )
    issues = v.validate({'title': garbage_title, 'author': 'u/x', 'permalink': '/r/x/abc'})
    titles = [i for i in issues if i.field == 'title']
    assert len(titles) == 1
    assert 'max 500' in titles[0].reason
    assert 'too-broad container' in titles[0].reason


def test_empty_string_value_flagged() -> None:
    """An empty string in the record IS a semantic issue — the extractor
    matched something but produced no usable text."""
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': '', 'author': 'u/x', 'permalink': '/r/x/abc'})
    titles = [i for i in issues if i.field == 'title']
    assert len(titles) == 1
    assert 'empty or null' in titles[0].reason


def test_none_value_skipped_not_flagged() -> None:
    """A field absent (None) from the record is downstream pydantic's
    problem — the semantic validator only grades fields that WERE extracted.
    Conflating the two would force the iterative loop to chase fields the
    page legitimately doesn't have."""
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': None, 'author': 'u/x', 'permalink': '/r/x/abc'})
    titles = [i for i in issues if i.field == 'title']
    assert titles == []


def test_field_missing_from_record_skipped_not_flagged() -> None:
    v = SemanticValidator(RedditPost)
    # only title + author present; score/comment_count/permalink absent
    issues = v.validate({'title': 'A real title', 'author': 'u/x'})
    # Validator should not fire on the missing fields.
    flagged_fields = {i.field for i in issues}
    assert flagged_fields == set()


# ---------------------------------------------------------------------------
# URL shape probe (catches the permalink-→-title-text regression)
# ---------------------------------------------------------------------------


def test_url_field_with_plain_sentence_is_flagged() -> None:
    """The permalink regression: returned the title TEXT, not the URL. The
    validator must detect a non-URL-shaped value in a `yosoi_type='url'` field."""
    v = SemanticValidator(RedditPost)
    issues = v.validate(
        {
            'title': 't',
            'author': 'u/x',
            'permalink': 'A reasonable post title with no slashes or dots in it',
        }
    )
    perms = [i for i in issues if i.field == 'permalink']
    assert len(perms) == 1
    assert 'does not look like a URL' in perms[0].reason


def test_url_field_relative_path_passes() -> None:
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': 't', 'author': 'u/x', 'permalink': '/r/ted/comments/abc'})
    perms = [i for i in issues if i.field == 'permalink']
    assert perms == []


def test_url_field_absolute_https_passes() -> None:
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': 't', 'author': 'u/x', 'permalink': 'https://example.com/x'})
    perms = [i for i in issues if i.field == 'permalink']
    assert perms == []


def test_url_field_bare_domain_passes() -> None:
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': 't', 'author': 'u/x', 'permalink': 'example.com/path'})
    perms = [i for i in issues if i.field == 'permalink']
    assert perms == []


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Count fields — numeric shape probe + length cap
# ---------------------------------------------------------------------------


def test_count_field_with_numeric_value_passes() -> None:
    v = SemanticValidator(RedditPost)
    issues = v.validate(
        {'title': 'A title', 'author': 'u/x', 'permalink': '/r/x/abc', 'score': '278', 'comment_count': '9'}
    )
    scores = [i for i in issues if i.field == 'score']
    comments = [i for i in issues if i.field == 'comment_count']
    assert scores == []
    assert comments == []


def test_count_field_with_si_suffix_passes() -> None:
    """The SI-suffix shape (4.2K) starts with digits so the numeric-prefix probe accepts it."""
    v = SemanticValidator(RedditPost)
    issues = v.validate(
        {'title': 'A title', 'author': 'u/x', 'permalink': '/r/x/abc', 'score': '4.2K', 'comment_count': '1,234'}
    )
    assert [i for i in issues if i.field in ('score', 'comment_count')] == []


def test_count_field_with_full_card_text_is_flagged() -> None:
    """The exact regression: shreddit-post CSS selector returns the whole card text,
    coercion to Count would fail downstream, but the validator catches it FIRST."""
    v = SemanticValidator(RedditPost)
    garbage = 'Facebook deleted 15m hate speech posts, 18m pieces of terrorist...'
    issues = v.validate(
        {
            'title': 'A title',
            'author': 'u/x',
            'permalink': '/r/x/abc',
            'score': garbage,
            'comment_count': garbage,
        }
    )
    score_issues = [i for i in issues if i.field == 'score']
    assert len(score_issues) == 1
    # Either too-long OR non-numeric — both reasons are valid for this regression.
    assert (
        'max 50' in score_issues[0].reason
        or 'does not look numeric' in score_issues[0].reason
        or 'equals other fields' in score_issues[0].reason
    )


def test_count_field_with_non_numeric_text_is_flagged() -> None:
    """A short non-numeric value (passes the length cap) must still be flagged by the
    type-shape probe — the LLM picked the wrong attribute."""
    v = SemanticValidator(RedditPost)
    issues = v.validate(
        {'title': 'A title', 'author': 'u/x', 'permalink': '/r/x/abc', 'score': 'Hot', 'comment_count': '5'}
    )
    score_issues = [i for i in issues if i.field == 'score']
    assert len(score_issues) == 1
    assert 'does not look numeric' in score_issues[0].reason


# Cross-field distinctness (catches "all three CSS selectors matched same card")
# ---------------------------------------------------------------------------


def test_cross_field_identical_values_all_flagged() -> None:
    """When title and permalink return the same string, BOTH are flagged — the
    LLM almost certainly latched onto the same wrong container for both."""
    v = SemanticValidator(RedditPost)
    same = 'some shared garbage value matched on both selectors'
    issues = v.validate({'title': same, 'author': 'u/x', 'permalink': same})
    titles = [i for i in issues if i.field == 'title']
    perms = [i for i in issues if i.field == 'permalink']
    assert len(titles) == 1
    assert len(perms) == 1
    # Both reasons should describe the collision.
    assert 'equals other fields' in titles[0].reason or 'does not look like a URL' in titles[0].reason
    assert 'equals other fields' in perms[0].reason or 'does not look like a URL' in perms[0].reason


def test_cross_field_distinct_values_pass() -> None:
    v = SemanticValidator(RedditPost)
    issues = v.validate({'title': 'A', 'author': 'u/x', 'permalink': '/r/x/abc'})
    # No cross-field collision since all values differ.
    assert all('equals other fields' not in i.reason for i in issues)


# ---------------------------------------------------------------------------
# Helper shape probes
# ---------------------------------------------------------------------------


def test_looks_numeric_accepts_common_formats() -> None:
    assert _looks_numeric('42')
    assert _looks_numeric('4.5')
    assert _looks_numeric('$1,234.56')
    assert _looks_numeric('4.2 stars')  # numeric prefix is enough
    assert not _looks_numeric('not a number')
    assert not _looks_numeric('')


def test_looks_url_like_accepts_paths_and_urls() -> None:
    assert _looks_url_like('/r/ted/comments/abc')
    assert _looks_url_like('https://example.com')
    assert _looks_url_like('//cdn.example.com/x')
    assert _looks_url_like('example.com/path')
    assert not _looks_url_like('A title with no URL-y characters at all')
    assert not _looks_url_like('')


def test_looks_datetime_like_accepts_common_shapes() -> None:
    assert _looks_datetime_like('2026-05-28')
    assert _looks_datetime_like('2026-05-28T14:35:59Z')
    assert _looks_datetime_like('May 28, 2026')
    assert _looks_datetime_like('5/28/2026')
    assert not _looks_datetime_like('not a date')
    assert not _looks_datetime_like('')


# ---------------------------------------------------------------------------
# Feedback rendering
# ---------------------------------------------------------------------------


def test_render_feedback_quotes_previous_selector() -> None:
    issues = [
        FieldIssue(
            field='score',
            yosoi_type=None,
            raw_value='Facebook deleted 15m hate speech posts...',
            reason="extracted 2,847 chars (max 500 for type 'text'); likely matched a too-broad container.",
        ),
    ]
    prev_selectors = {
        'score': {'primary': {'type': 'css', 'value': 'shreddit-post', 'identity': 'id'}},
    }
    feedback = render_feedback(issues, prev_selectors)
    assert 'score' in feedback
    msg = feedback['score']
    # The feedback names the field, quotes the prior selector, and surfaces the rule reference.
    assert 'score' in msg
    assert 'shreddit-post' in msg
    assert 'extracted 2,847 chars' in msg
    assert 'RULE 1' in msg  # rubric pointer (site-agnostic — no shreddit-specific text)


def test_render_feedback_empty_for_no_issues() -> None:
    assert render_feedback([], {}) == {}
