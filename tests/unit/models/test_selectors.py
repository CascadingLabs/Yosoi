"""Tests for FieldSelectors, SelectorEntry, and SelectorLevel models."""

from yosoi.models.selectors import FieldSelectors, SelectorEntry, SelectorLevel

# ---------------------------------------------------------------------------
# SelectorLevel
# ---------------------------------------------------------------------------


def test_selector_level_css_is_1():
    assert SelectorLevel.CSS == 1


def test_selector_level_xpath_is_2():
    assert SelectorLevel.XPATH == 2


def test_selector_level_regex_is_3():
    assert SelectorLevel.REGEX == 3


def test_selector_level_jsonld_is_4():
    assert SelectorLevel.JSONLD == 4


def test_selector_level_clean_alias():
    assert SelectorLevel.CLEAN == SelectorLevel.CSS


def test_selector_level_standard_alias():
    assert SelectorLevel.STANDARD == SelectorLevel.XPATH


def test_selector_level_all_alias():
    assert SelectorLevel.ALL == SelectorLevel.JSONLD


def test_selector_level_ordering():
    assert SelectorLevel.CSS < SelectorLevel.XPATH < SelectorLevel.REGEX < SelectorLevel.JSONLD


# ---------------------------------------------------------------------------
# SelectorEntry
# ---------------------------------------------------------------------------


def test_selector_entry_defaults_to_css():
    e = SelectorEntry(value='h1')
    assert e.strategy == 'css'
    assert e.level == SelectorLevel.CSS


def test_selector_entry_xpath_sets_level():
    e = SelectorEntry(strategy='xpath', value='//h1')
    assert e.level == SelectorLevel.XPATH


def test_selector_entry_regex_sets_level():
    e = SelectorEntry(strategy='regex', value=r'\d+')
    assert e.level == SelectorLevel.REGEX


def test_selector_entry_jsonld_sets_level():
    e = SelectorEntry(strategy='jsonld', value='$.name')
    assert e.level == SelectorLevel.JSONLD


def test_selector_entry_level_synced_from_strategy():
    e = SelectorEntry(strategy='xpath', value='//h1')
    assert e.level == 2


# ---------------------------------------------------------------------------
# FieldSelectors — backward compat (str coercion)
# ---------------------------------------------------------------------------


def test_field_selectors_coerces_str_to_entry():
    fs = FieldSelectors(primary='h1')
    assert isinstance(fs.primary, SelectorEntry)
    assert fs.primary.value == 'h1'


def test_field_selectors_coerces_fallback_str():
    fs = FieldSelectors(primary='h1', fallback='h2')
    assert isinstance(fs.fallback, SelectorEntry)
    assert fs.fallback.value == 'h2'  # type: ignore[union-attr]


def test_field_selectors_accepts_selector_entry_directly():
    entry = SelectorEntry(strategy='xpath', value='//h1')
    fs = FieldSelectors(primary=entry)
    assert fs.primary.strategy == 'xpath'


def test_field_selectors_fallback_none_by_default():
    fs = FieldSelectors(primary='h1')
    assert fs.fallback is None
    assert fs.tertiary is None


# ---------------------------------------------------------------------------
# FieldSelectors.max_level
# ---------------------------------------------------------------------------


def test_field_selectors_max_level_plain_str_is_css():
    assert FieldSelectors(primary='h1').max_level == SelectorLevel.CSS


def test_field_selectors_max_level_with_xpath_fallback():
    fs = FieldSelectors(primary='h1', fallback=SelectorEntry(strategy='xpath', value='//h1'))
    assert fs.max_level == SelectorLevel.XPATH


def test_field_selectors_max_level_with_xpath_primary():
    fs = FieldSelectors(primary=SelectorEntry(strategy='xpath', value='//h1'))
    assert fs.max_level == SelectorLevel.XPATH


# ---------------------------------------------------------------------------
# FieldSelectors.as_tuples — backward compat
# ---------------------------------------------------------------------------


def test_as_tuples_returns_three_entries():
    fs = FieldSelectors(primary='h1', fallback='h2', tertiary='h3')
    result = fs.as_tuples()
    assert len(result) == 3


def test_as_tuples_correct_levels_and_values():
    fs = FieldSelectors(primary='h1', fallback='h2', tertiary='h3')
    result = fs.as_tuples()
    assert result[0] == ('primary', 'h1')
    assert result[1] == ('fallback', 'h2')
    assert result[2] == ('tertiary', 'h3')


def test_as_tuples_none_fallback_preserved():
    fs = FieldSelectors(primary='h1')
    result = fs.as_tuples()
    assert result[1] == ('fallback', None)
    assert result[2] == ('tertiary', None)


def test_as_tuples_partial_none():
    fs = FieldSelectors(primary='h1', fallback='.title', tertiary=None)
    result = fs.as_tuples()
    assert result[1] == ('fallback', '.title')
    assert result[2] == ('tertiary', None)


def test_as_tuples_returns_value_string_not_entry():
    fs = FieldSelectors(primary='h1', fallback='h2')
    tuples = fs.as_tuples()
    # Values must be plain strings, not SelectorEntry
    assert isinstance(tuples[0][1], str)
    assert tuples[0][1] == 'h1'


# ---------------------------------------------------------------------------
# FieldSelectors.as_entries
# ---------------------------------------------------------------------------


def test_as_entries_returns_selector_entry_objects():
    fs = FieldSelectors(primary='h1', fallback='h2')
    entries = fs.as_entries()
    assert isinstance(entries[0][1], SelectorEntry)
    assert isinstance(entries[1][1], SelectorEntry)


def test_as_entries_none_preserved():
    fs = FieldSelectors(primary='h1')
    entries = fs.as_entries()
    assert entries[1] == ('fallback', None)
    assert entries[2] == ('tertiary', None)


def test_as_entries_xpath_entry_preserved():
    entry = SelectorEntry(strategy='xpath', value='//h1')
    fs = FieldSelectors(primary=entry)
    entries = fs.as_entries()
    assert entries[0][1].strategy == 'xpath'  # type: ignore[union-attr]
