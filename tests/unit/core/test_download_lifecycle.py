"""Tests for Phase 7 download lifecycle: run-end manifest accumulation + keep_downloads purge.

Drives the Pipeline methods directly against a lightweight stand-in for ``self`` to avoid
the heavy constructor.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

from yosoi.core.pipeline import Pipeline
from yosoi.models.download import DownloadRecord, DownloadResult


def _fake_pipeline(tmp_path: Path, *, keep: bool) -> Any:
    ns = types.SimpleNamespace()
    ns._download_log = []
    ns._keep_downloads = keep
    ns.logger = __import__('logging').getLogger('test')
    ns.console = __import__('rich.console', fromlist=['Console']).Console(quiet=True)
    return ns


def _result(tmp_path: Path, *, name: str, data: bytes, changed: bool) -> DownloadResult:
    path = tmp_path / name
    path.write_bytes(data)
    rec = DownloadRecord(path=str(path), sha256='h' * 64, size_bytes=len(data), content_type='text/csv')
    return DownloadResult(record=rec, value=rec, changed=changed)


def test_record_downloads_accumulates_and_logs(tmp_path: Path) -> None:
    ns = _fake_pipeline(tmp_path, keep=True)
    result = _result(tmp_path, name='a.csv', data=b'x,y\n1,2', changed=True)
    Pipeline._record_downloads(ns, {'rows': result})
    assert ns._download_log == [('rows', result)]


def test_finalize_keeps_blobs_when_keep_true(tmp_path: Path) -> None:
    ns = _fake_pipeline(tmp_path, keep=True)
    result = _result(tmp_path, name='keep.csv', data=b'data', changed=True)
    ns._download_log.append(('rows', result))
    Pipeline._finalize_downloads(ns)
    assert Path(result.record.path).exists()  # kept


def test_finalize_purges_blobs_when_keep_false(tmp_path: Path) -> None:
    ns = _fake_pipeline(tmp_path, keep=False)
    result = _result(tmp_path, name='purge.csv', data=b'data', changed=True)
    ns._download_log.append(('rows', result))
    Pipeline._finalize_downloads(ns)
    assert not Path(result.record.path).exists()  # purged


def test_finalize_noop_without_downloads(tmp_path: Path) -> None:
    ns = _fake_pipeline(tmp_path, keep=False)
    Pipeline._finalize_downloads(ns)  # must not raise with an empty log
    assert ns._download_log == []
