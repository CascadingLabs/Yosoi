"""Tests for the ys.File() field factory, annotation-directed output, allowlist, parsing."""

from pathlib import Path

import pytest

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.models.download import DownloadRecord, output_view_for_annotation
from yosoi.types.filetypes import (
    matches_allowed_types,
    normalize_allowed_types,
    parse_download,
)


class _DocContract(Contract):
    title: str = ys.Field()
    rows: list[dict] = ys.File(trigger='a.export', allowed_types=['csv'])
    clip: ys.DownloadRecord | None = ys.File(href='a.clip', allowed_types=['mp4', 'MP3', '.pdf'], default=None)


def test_file_field_metadata_and_modes() -> None:
    fields = _DocContract.file_fields()
    assert set(fields) == {'rows', 'clip'}
    assert fields['rows']['mode'] == 'retrigger'  # trigger => click
    assert fields['clip']['mode'] == 'refetch'  # href => direct fetch
    # parse= is gone — output is driven by the annotation, not metadata.
    assert 'parse' not in fields['rows']


def test_file_fields_excluded_from_css_discovery() -> None:
    names = _DocContract.discovery_field_names()
    assert 'title' in names
    assert 'rows' not in names
    assert 'clip' not in names


def test_allowed_types_normalized_canonical() -> None:
    assert _DocContract.file_fields()['clip']['allowed_types'] == ['mp4', 'mp3', 'pdf']


def test_file_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match='exactly one'):
        ys.File(allowed_types=['csv'])
    with pytest.raises(ValueError, match='exactly one'):
        ys.File(trigger='a', url='http://x', allowed_types=['csv'])


def test_file_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match='unknown file type'):
        ys.File(trigger='a', allowed_types=['mpx'])


# --- annotation-directed output resolution ----------------------------------


def test_output_view_for_annotation() -> None:
    assert output_view_for_annotation(DownloadRecord) == 'record'
    assert output_view_for_annotation(Path) == 'path'
    assert output_view_for_annotation(bytes) == 'bytes'
    assert output_view_for_annotation(str) == 'text'
    assert output_view_for_annotation(list[dict]) == 'parsed'
    assert output_view_for_annotation(list) == 'parsed'
    assert output_view_for_annotation(dict) == 'parsed'
    assert output_view_for_annotation(DownloadRecord | None) == 'record'  # Optional unwraps

    class Row(Contract):
        a: str = ys.Field()

    assert output_view_for_annotation(list[Row]) == 'parsed'


def test_output_view_rejects_unsupported() -> None:
    with pytest.raises(ValueError, match='not supported'):
        output_view_for_annotation(complex)


def test_unsupported_file_annotation_fails_at_contract_definition() -> None:
    with pytest.raises(TypeError, match='not supported'):

        class _Bad(Contract):
            blob: complex = ys.File(trigger='a', allowed_types=['csv'])


# --- allowlist matching -----------------------------------------------------


def test_match_csv_by_content_type_rejects_html_interstitial() -> None:
    assert matches_allowed_types(('csv',), 'text/csv', b'a,b\n1,2')
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


# --- parsing (format chosen by content-type) --------------------------------


def test_parse_download_csv_and_json() -> None:
    assert parse_download(b'name,age\nAda,36\n', 'text/csv') == [{'name': 'Ada', 'age': '36'}]
    assert parse_download(b'{"a": 1}', 'application/json') == {'a': 1}
    # No content-type and delimited text → treated as CSV.
    assert parse_download(b'x,y\n1,2', None) == [{'x': '1', 'y': '2'}]
