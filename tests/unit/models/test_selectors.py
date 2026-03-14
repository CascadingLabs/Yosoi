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


def test_selector_level_ordering():
    assert SelectorLevel.CSS < SelectorLevel.XPATH < SelectorLevel.REGEX < SelectorLevel.JSONLD


# ---------------------------------------------------------------------------
# SelectorEntry
# ---------------------------------------------------------------------------


def test_selector_entry_defaults_to_css():
    e = SelectorEntry(value='h1')
    assert e.type == 'css'
    assert e.level == SelectorLevel.CSS


def test_selector_entry_xpath_sets_level():
    e = SelectorEntry(type='xpath', value='//h1')
    assert e.level == SelectorLevel.XPATH


def test_selector_entry_regex_sets_level():
    e = SelectorEntry(type='regex', value=r'\d+')
    assert e.level == SelectorLevel.REGEX


def test_selector_entry_jsonld_sets_level():
    e = SelectorEntry(type='jsonld', value='$.name')
    assert e.level == SelectorLevel.JSONLD


def test_selector_entry_level_synced_from_type():
    e = SelectorEntry(type='xpath', value='//h1')
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
    entry = SelectorEntry(type='xpath', value='//h1')
    fs = FieldSelectors(primary=entry)
    assert fs.primary.type == 'xpath'


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
    fs = FieldSelectors(primary='h1', fallback=SelectorEntry(type='xpath', value='//h1'))
    assert fs.max_level == SelectorLevel.XPATH


def test_field_selectors_max_level_with_xpath_primary():
    fs = FieldSelectors(primary=SelectorEntry(type='xpath', value='//h1'))
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
    entry = SelectorEntry(type='xpath', value='//h1')
    fs = FieldSelectors(primary=entry)
    entries = fs.as_entries()
    assert entries[0][1].type == 'xpath'  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# FieldSelectors — NA coercion
# ---------------------------------------------------------------------------


def test_na_fallback_becomes_none():
    fs = FieldSelectors(primary='h1', fallback='NA')
    assert fs.fallback is None


def test_na_lowercase_fallback_becomes_none():
    fs = FieldSelectors(primary='h1', fallback='na')
    assert fs.fallback is None


def test_na_mixed_case_tertiary_becomes_none():
    fs = FieldSelectors(primary='h1', tertiary='Na')
    assert fs.tertiary is None


def test_empty_string_fallback_becomes_none():
    fs = FieldSelectors(primary='h1', fallback='')
    assert fs.fallback is None


# ---------------------------------------------------------------------------
# FieldSelectors — deduplication
# ---------------------------------------------------------------------------


def test_dedup_fallback_equals_primary():
    fs = FieldSelectors(primary='.star', fallback='.star')
    assert fs.fallback is None


def test_dedup_tertiary_equals_fallback():
    fs = FieldSelectors(primary='h1', fallback='.title', tertiary='.title')
    assert fs.fallback is not None
    assert fs.fallback.value == '.title'
    assert fs.tertiary is None


def test_dedup_tertiary_equals_primary_when_fallback_deduped():
    # fallback == primary → fallback becomes None; tertiary == primary → tertiary cleared
    fs = FieldSelectors(primary='.star', fallback='.star', tertiary='.star')
    assert fs.fallback is None
    assert fs.tertiary is None


def test_dedup_unique_selectors_preserved():
    fs = FieldSelectors(primary='h1', fallback='.title', tertiary='#heading')
    assert fs.fallback is not None
    assert fs.fallback.value == '.title'
    assert fs.tertiary is not None
    assert fs.tertiary.value == '#heading'


def test_dedup_only_tertiary_duplicates_primary():
    # fallback is unique; tertiary duplicates primary → only tertiary cleared
    fs = FieldSelectors(primary='h1', fallback='.unique', tertiary='h1')
    assert fs.fallback is not None
    assert fs.fallback.value == '.unique'
    assert fs.tertiary is None
