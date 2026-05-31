"""Tests for the pipeline download wiring: spec resolution, opt-in gate, and merge.

These exercise the methods directly against a lightweight stand-in for ``self`` so we
avoid the heavy Pipeline constructor (LLM config, orchestrators, storage).
"""

from __future__ import annotations

import types
from typing import Any

import pytest

import yosoi as ys
from yosoi.core.pipeline import Pipeline
from yosoi.models.contract import Contract
from yosoi.models.download import DownloadRecord, DownloadResult
from yosoi.types.filetypes import normalize_allowed_types


class _Files(Contract):
    title: str = ys.Field()
    report: list = ys.File(trigger='a.export', parse='csv', allowed_types=['csv', 'pdf'])


class _NoFiles(Contract):
    title: str = ys.Field()


def _fake_pipeline(contract: type[Contract], *, allow: bool, global_types: tuple[str, ...] = ()) -> Any:
    ns = types.SimpleNamespace()
    ns._allow_downloads = allow
    ns._allowed_download_types = normalize_allowed_types(global_types)
    ns.contract = contract
    ns._file_download_specs = lambda: Pipeline._file_download_specs(ns)
    return ns


def test_file_download_specs_built() -> None:
    specs = Pipeline._file_download_specs(_fake_pipeline(_Files, allow=True))
    assert set(specs) == {'report'}
    assert specs['report'].mode == 'retrigger'
    assert specs['report'].parse == 'csv'
    assert specs['report'].allowed_types == ('csv', 'pdf')


def test_global_allowlist_intersects_field() -> None:
    # Global ceiling narrows the field's allowlist.
    specs = Pipeline._file_download_specs(_fake_pipeline(_Files, allow=True, global_types=('csv',)))
    assert specs['report'].allowed_types == ('csv',)


def test_gate_fails_fast_when_downloads_disabled() -> None:
    with pytest.raises(RuntimeError, match='disabled'):
        Pipeline._resolve_download_specs(_fake_pipeline(_Files, allow=False))


def test_gate_returns_specs_when_enabled() -> None:
    specs = Pipeline._resolve_download_specs(_fake_pipeline(_Files, allow=True))
    assert specs is not None
    assert 'report' in specs


def test_gate_none_without_file_fields() -> None:
    assert Pipeline._resolve_download_specs(_fake_pipeline(_NoFiles, allow=False)) is None


def _result(downloads: dict[str, DownloadResult] | None, js: dict[str, Any] | None = None) -> Any:
    return types.SimpleNamespace(downloads=downloads, js_outputs=js)


def test_merge_downloads_into_dict_and_list() -> None:
    rec = DownloadRecord(path='/q/x.csv', sha256='a' * 64, size_bytes=3, content_type='text/csv')
    downloads = {'report': DownloadResult(record=rec, value=[{'a': 1}])}

    merged_dict = Pipeline._merge_downloads({'title': 'T'}, downloads)
    assert merged_dict == {'title': 'T', 'report': [{'a': 1}]}

    merged_list = Pipeline._merge_downloads([{'title': 'A'}, {'title': 'B'}], downloads)
    assert merged_list == [{'title': 'A', 'report': [{'a': 1}]}, {'title': 'B', 'report': [{'a': 1}]}]


def test_merge_fetch_outputs_applies_js_and_downloads() -> None:
    rec = DownloadRecord(path='/q/x.csv', sha256='b' * 64, size_bytes=1, content_type='text/csv')
    result = _result({'report': DownloadResult(record=rec, value='ROWS')}, js={'sig': True})
    merged = Pipeline._merge_fetch_outputs({'title': 'T'}, result)
    assert merged == {'title': 'T', 'sig': True, 'report': 'ROWS'}
