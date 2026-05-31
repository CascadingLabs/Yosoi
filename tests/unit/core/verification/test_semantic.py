"""Unit tests for the generic, rule-driven SemanticValidator."""

import pytest

import yosoi as ys
from yosoi.core.verification.semantic import (
    FieldSemanticIssue,
    SemanticValidator,
    field_rules_for_contract,
)
from yosoi.types.registry import (
    KIND_NUMERIC,
    KIND_TEXT,
    KIND_URL,
    SemanticRule,
)

# Rule shorthands mirroring what the built-in types declare.
NUMERIC = SemanticRule(kind=KIND_NUMERIC, max_chars=50)
URL = SemanticRule(kind=KIND_URL, max_chars=500)
TITLE = SemanticRule(kind=KIND_TEXT, max_chars=500, distinct=True)
BODY = SemanticRule(kind=KIND_TEXT, distinct=True)
AUTHOR = SemanticRule(kind=KIND_TEXT, max_chars=120)
DATETIME = SemanticRule(kind=KIND_TEXT, max_chars=80)


@pytest.fixture
def validator():
    return SemanticValidator()


# ---------------------------------------------------------------------------
# numeric
# ---------------------------------------------------------------------------


def test_numeric_accepts_short_number(validator):
    assert validator.validate({'score': '42'}, {'score': NUMERIC}) == []


def test_numeric_rejects_long_card_text(validator):
    blob = '42 points · ' + 'Facebook deleted my account ' * 50
    issues = validator.validate({'score': blob}, {'score': NUMERIC})
    assert len(issues) == 1
    assert issues[0].field == 'score'
    assert 'not a number' in issues[0].reason


def test_numeric_rejects_text_without_digits(validator):
    issues = validator.validate({'score': 'Reply Share'}, {'score': NUMERIC})
    assert len(issues) == 1
    assert 'no number' in issues[0].reason


def test_numeric_without_max_chars_only_needs_a_digit(validator):
    rule = SemanticRule(kind=KIND_NUMERIC)
    long_with_digit = 'x' * 1000 + ' 5'
    assert validator.validate({'n': long_with_digit}, {'n': rule}) == []


# ---------------------------------------------------------------------------
# url
# ---------------------------------------------------------------------------


def test_url_accepts_path(validator):
    assert validator.validate({'permalink': '/r/x/comments/1/_/c1/'}, {'permalink': URL}) == []


def test_url_accepts_absolute(validator):
    assert validator.validate({'permalink': 'https://reddit.com/r/x'}, {'permalink': URL}) == []


def test_url_rejects_non_url_text(validator):
    issues = validator.validate({'permalink': 'Posted by alice'}, {'permalink': URL})
    assert len(issues) == 1
    assert 'not a URL' in issues[0].reason


def test_url_rejects_too_long(validator):
    long_url = 'https://x.com/' + 'a' * 600
    issues = validator.validate({'permalink': long_url}, {'permalink': URL})
    assert len(issues) == 1
    assert 'too long to be a URL' in issues[0].reason


def test_list_value_uses_first_string(validator):
    # A list-valued extraction is reduced to its first string for shape checks.
    issues = validator.validate({'score': ['not a number at all']}, {'score': NUMERIC})
    assert len(issues) == 1


def test_related_content_list_of_dicts_is_skipped(validator):
    # related_content extracts list[dict]; there is no scalar to shape-check.
    item = {'links': [{'text': 'a', 'href': '/x'}]}
    assert validator.validate(item, {'links': URL}) == []


# ---------------------------------------------------------------------------
# text (title / body / author / datetime via max_chars + distinct)
# ---------------------------------------------------------------------------


def test_title_accepts_concise(validator):
    assert validator.validate({'title': 'A great post'}, {'title': TITLE}) == []


def test_title_rejects_full_card(validator):
    issues = validator.validate({'title': 'x' * 600}, {'title': TITLE})
    assert len(issues) == 1
    assert 'concise value' in issues[0].reason


def test_title_rejects_duplicate_of_other_field(validator):
    item = {'title': 'same', 'body': 'same'}
    issues = validator.validate(item, {'title': TITLE, 'body': BODY})
    assert {i.field for i in issues} == {'title', 'body'}


def test_body_accepts_long_prose(validator):
    assert validator.validate({'body': 'long prose ' * 200}, {'body': BODY}) == []


def test_author_rejects_card_blob(validator):
    issues = validator.validate({'author': 'alice ' * 50}, {'author': AUTHOR})
    assert len(issues) == 1
    assert 'concise value' in issues[0].reason


def test_datetime_rejects_long_text(validator):
    issues = validator.validate({'created_at': 'x' * 100}, {'created_at': DATETIME})
    assert len(issues) == 1


# ---------------------------------------------------------------------------
# absence / no-rule
# ---------------------------------------------------------------------------


def test_none_and_empty_are_not_flagged(validator):
    item = {'score': None, 'permalink': '', 'author': '   '}
    rules = {'score': NUMERIC, 'permalink': URL, 'author': AUTHOR}
    assert validator.validate(item, rules) == []


def test_field_without_rule_is_never_flagged(validator):
    assert validator.validate({'misc': 'x' * 5000}, {}) == []


# ---------------------------------------------------------------------------
# feedback rendering
# ---------------------------------------------------------------------------


def test_feedback_quotes_value_and_length():
    issue = FieldSemanticIssue(
        field='score', raw_value='Reply Share Save', reason='returned text with no number in it.'
    )
    msg = issue.as_feedback()
    assert '`score`' in msg
    assert '16 characters' in msg
    assert 'Reply Share Save' in msg
    assert '::attr' in msg


def test_feedback_truncates_long_values():
    issue = FieldSemanticIssue(field='score', raw_value='x' * 1000, reason='returned a long block of text.')
    msg = issue.as_feedback()
    assert '…' in msg
    assert '1000 characters' in msg


# ---------------------------------------------------------------------------
# field_rules_for_contract — rules come from the registry + annotation fallback
# ---------------------------------------------------------------------------


def test_field_rules_from_contract():
    class Post(ys.Contract):
        title: str | None = ys.Title(default=None)
        author: str | None = ys.Author(default=None)
        body: str | None = ys.BodyText(default=None)
        created_at: str | None = ys.Datetime(default=None)
        permalink: str | None = ys.Url(default=None)
        score: int | None = ys.Field(default=None)
        note: str | None = ys.Field(default=None)

    rules = field_rules_for_contract(Post)
    assert rules['title'].kind == KIND_TEXT
    assert rules['title'].distinct
    assert rules['author'].kind == KIND_TEXT
    assert rules['author'].max_chars == 120
    assert rules['body'].kind == KIND_TEXT
    assert rules['created_at'].kind == KIND_TEXT
    assert rules['permalink'].kind == KIND_URL
    assert rules['score'].kind == KIND_NUMERIC  # inferred from int annotation
    assert 'note' not in rules  # plain str field, no rule


def test_field_rules_expands_nested_contract():
    class Inner(ys.Contract):
        url: str | None = ys.Url(default=None)
        count: int | None = ys.Field(default=None)

    class Outer(ys.Contract):
        title: str | None = ys.Title(default=None)
        inner: Inner = ys.Field(default_factory=Inner)

    rules = field_rules_for_contract(Outer)
    assert rules['title'].kind == KIND_TEXT
    assert rules['inner_url'].kind == KIND_URL
    assert rules['inner_count'].kind == KIND_NUMERIC


def test_to_text_returns_none_for_list_of_dicts():
    """_to_text returns None for a list of dicts (related_content) — not shape-checkable (line 161-162)."""
    from yosoi.core.verification.semantic import _to_text

    result = _to_text([{'title': 'Related', 'href': '/link'}])
    assert result is None


def test_duplicate_of_returns_none_for_empty_text():
    """_duplicate_of returns None immediately when text normalizes to '' (line 169)."""
    from yosoi.core.verification.semantic import _duplicate_of

    result = _duplicate_of('headline', '   ', {'headline': '   ', 'author': 'Bob'})
    assert result is None


def test_check_field_rule_returns_none_when_no_rule_applies():
    """validate() returns no issues when no semantic rule is registered for a field (line 148)."""
    from yosoi.core.verification.semantic import SemanticValidator
    from yosoi.models.contract import Contract

    class MinimalContract(Contract):
        custom_field: str = ''  # no yosoi type → no semantic rule

    validator = SemanticValidator()
    rules = {'custom_field': None}  # type: ignore[dict-item]
    issues = validator.validate({'custom_field': 'anything'}, rules)
    assert issues == []
