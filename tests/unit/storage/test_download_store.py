"""Tests for the content-addressed download store + per-domain lookup index + drift."""

from __future__ import annotations

import json
from pathlib import Path

from yosoi.storage.download_store import commit_download, infer_extension


def _write(qdir: Path, name: str, data: bytes) -> Path:
    path = qdir / name
    path.write_bytes(data)
    return path


def _commit(qdir: Path, *, field: str, name: str, data: bytes, sha256: str, content_type: str = 'text/csv'):
    return commit_download(
        qdir=qdir,
        field=field,
        src_path=_write(qdir, name, data),
        sha256=sha256,
        content_type=content_type,
        size_bytes=len(data),
        source_url='https://sec.gov/x.csv',
        allowed_types=('csv',),
    )


def test_cas_path_is_sha256_named_and_moves_source(tmp_path: Path) -> None:
    cas, changed = _commit(tmp_path, field='rows', name='report.csv', data=b'a,b\n1,2', sha256='deadbeef')
    assert cas == tmp_path / 'deadbeef.csv'
    assert cas.read_bytes() == b'a,b\n1,2'
    assert not (tmp_path / 'report.csv').exists()  # moved, not copied
    assert changed is True  # first time this field is seen


def test_dedup_same_bytes_bumps_seen_count(tmp_path: Path) -> None:
    _commit(tmp_path, field='rows', name='a.csv', data=b'x', sha256='aaa')
    cas2, changed2 = _commit(tmp_path, field='rows', name='b.csv', data=b'x', sha256='aaa')
    assert cas2 == tmp_path / 'aaa.csv'
    assert not (tmp_path / 'b.csv').exists()  # duplicate bytes dropped
    index = json.loads((tmp_path / 'index.json').read_text())
    assert list(index['blobs']) == ['aaa']  # one blob, not two
    assert index['blobs']['aaa']['seen_count'] == 2
    assert index['blobs']['aaa']['name'] == 'a.csv'  # first name retained
    assert changed2 is False  # same field, identical bytes → no drift


def test_drift_changed_when_bytes_differ(tmp_path: Path) -> None:
    _, c1 = _commit(tmp_path, field='rows', name='v1.csv', data=b'v1', sha256='h1')
    _, c2 = _commit(tmp_path, field='rows', name='v2.csv', data=b'v2', sha256='h2')
    assert c1 is True
    assert c2 is True  # bytes changed for this field
    index = json.loads((tmp_path / 'index.json').read_text())
    assert index['fields']['rows']['history'] == ['h1', 'h2']
    assert index['fields']['rows']['last_sha256'] == 'h2'


def test_infer_extension() -> None:
    assert infer_extension('text/csv') == 'csv'
    assert infer_extension('application/json; charset=utf-8') == 'json'
    assert infer_extension('application/pdf') == 'pdf'
    assert infer_extension(None, ('pdf',)) == 'pdf'  # fall back to allowlist name
    assert infer_extension(None, ('video/webm',)) == 'bin'  # MIME-only allowlist → bin
    assert infer_extension(None, ()) == 'bin'
