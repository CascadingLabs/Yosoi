"""Tests for the ys.File() field factory, file-type allowlist, and parse transforms."""

import pytest

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.types.filetypes import (
    apply_parse,
    matches_allowed_types,
    normalize_allowed_types,
)


class _DocContract(Contract):
    title: str = ys.Field()
    report: list = ys.File(trigger='a.export', parse='csv', allowed_types=['csv'])
    clip: ys.DownloadRecord | None = ys.File(href='a.clip', allowed_types=['mp4', 'MP3', '.pdf'], default=None)


def test_file_field_metadata_and_modes() -> None:
    fields = _DocContract.file_fields()
    assert set(fields) == {'report', 'clip'}
    assert fields['report']['mode'] == 'retrigger'  # trigger => click
    assert fields['clip']['mode'] == 'refetch'  # href => direct fetch
    assert fields['report']['parse'] == 'csv'


def test_file_fields_excluded_from_css_discovery() -> None:
    names = _DocContract.discovery_field_names()
    assert 'title' in names
    assert 'report' not in names
    assert 'clip' not in names


def test_allowed_types_normalized_canonical() -> None:
    # friendly names, case, bare extension, alias all canonicalize
    assert _DocContract.file_fields()['clip']['allowed_types'] == ['mp4', 'mp3', 'pdf']


def test_file_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match='exactly one'):
        ys.File(allowed_types=['csv'])
    with pytest.raises(ValueError, match='exactly one'):
        ys.File(trigger='a', url='http://x', allowed_types=['csv'])


def test_file_rejects_unknown_type_and_bad_parse() -> None:
    with pytest.raises(ValueError, match='unknown file type'):
        ys.File(trigger='a', allowed_types=['mpx'])
    with pytest.raises(ValueError, match='unsupported'):
        ys.File(trigger='a', allowed_types=['csv'], parse='xml')


# --- allowlist matching -----------------------------------------------------


def test_match_csv_by_content_type_rejects_html_interstitial() -> None:
    assert matches_allowed_types(('csv',), 'text/csv', b'a,b\n1,2')
    # An HTML "sign in to download" page served as text/html must NOT pass as csv.
    assert not matches_allowed_types(('csv',), 'text/html', b'<html>please sign in</html>')


def test_match_binary_by_magic_bytes_even_as_octet_stream() -> None:
    assert matches_allowed_types(('mp4',), 'application/octet-stream', b'\x00\x00\x00\x18ftypmp42')
    assert matches_allowed_types(('pdf',), None, b'%PDF-1.7\n...')
    assert not matches_allowed_types(('pdf',), None, b'not a pdf at all')


def test_default_deny_empty_allowlist_matches_nothing() -> None:
    assert not matches_allowed_types((), 'text/csv', b'a,b')


def test_normalize_rejects_unknown() -> None:
    assert normalize_allowed_types(['CSV', '.mp4', 'video/webm']) == ('csv', 'mp4', 'video/webm')
    with pytest.raises(ValueError, match='unknown file type'):
        normalize_allowed_types(['definitely-not-a-type'])


# --- parse ------------------------------------------------------------------


def test_parse_csv_and_json() -> None:
    assert apply_parse('csv', b'name,age\nAda,36\n', 'text/csv') == [{'name': 'Ada', 'age': '36'}]
    assert apply_parse('json', b'{"a": 1}', 'application/json') == {'a': 1}
    assert apply_parse(None, b'whatever', None) is None
