"""Tests for live-tab ys.File() download execution (fake tab — no real browser)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from yosoi.core.fetcher import downloads as dl
from yosoi.models.download import DownloadRecord, DownloadResult, DownloadSpec
from yosoi.utils.exceptions import DownloadError

CSV_BYTES = b'month,revenue\nJan,100\nFeb,120\n'
HTML_BYTES = b'<html><body>Please sign in to download</body></html>'


class _FakeOutcome:
    """Stand-in for voidcrawl.DownloadOutcome."""

    def __init__(self, path: str, content_type: str | None, size: int) -> None:
        self.path = path
        self.content_type = content_type
        self.bytes = size


class _FakeTab:
    """Minimal tab implementing the download protocol capture_download/Page.download use."""

    def __init__(
        self, *, data: bytes, content_type: str | None, filename: str = 'f.bin', href: str | None = None
    ) -> None:
        self._data = data
        self._content_type = content_type
        self._filename = filename
        self._href = href
        self.clicked: str | None = None
        self._dir: str | None = None

    def _write(self) -> _FakeOutcome:
        assert self._dir is not None
        path = Path(self._dir) / self._filename
        path.write_bytes(self._data)
        return _FakeOutcome(str(path), self._content_type, len(self._data))

    # --- retrigger (capture_download) path ---
    async def arm_download(self, dir: str, max_bytes: int | None = None) -> object:
        self._dir = dir
        return object()

    async def click_element(self, selector: str) -> None:
        self.clicked = selector

    async def wait_download(self, capture: object, timeout: float = 120.0) -> _FakeOutcome:
        return self._write()

    async def reset_download(self) -> None:
        pass

    # --- refetch (Page.download) path ---
    async def download(self, url: str, dir: str, timeout: float = 120.0, max_bytes: int | None = None) -> _FakeOutcome:
        self._dir = dir
        return self._write()

    async def eval_js(self, expr: str) -> Any:
        return self._href


async def test_retrigger_csv_parse(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='export.csv')
    spec = DownloadSpec(field='report', mode='retrigger', trigger='a.export', allowed_types=('csv',), output='parsed')

    result = await dl.run_download(tab, spec, tmp_path)

    assert isinstance(result, DownloadResult)
    assert tab.clicked == 'a.export'  # the trigger was clicked inside capture
    assert result.value == [{'month': 'Jan', 'revenue': '100'}, {'month': 'Feb', 'revenue': '120'}]
    assert result.record.sha256 == hashlib.sha256(CSV_BYTES).hexdigest()
    assert result.record.size_bytes == len(CSV_BYTES)
    assert Path(result.record.path).read_bytes() == CSV_BYTES
    # Content-addressed: the stored file is named by its sha256, and drift is flagged.
    assert Path(result.record.path).name == f'{result.record.sha256}.csv'
    assert result.changed is True
    assert (tmp_path / 'index.json').exists()


async def test_redownload_same_bytes_is_not_changed(tmp_path: Path) -> None:
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',), output='parsed')
    first = await dl.run_download(_FakeTab(data=CSV_BYTES, content_type='text/csv', filename='e.csv'), spec, tmp_path)
    second = await dl.run_download(_FakeTab(data=CSV_BYTES, content_type='text/csv', filename='e.csv'), spec, tmp_path)
    assert first.changed is True
    assert second.changed is False  # identical bytes for the same field → no drift
    assert second.record.path == first.record.path  # deduped to one content-addressed file


async def test_empty_download_rejected(tmp_path: Path) -> None:
    tab = _FakeTab(data=b'', content_type='text/csv', filename='empty.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='empty'):
        await dl.run_download(tab, spec, tmp_path)


async def test_retrigger_no_parse_returns_record(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='export.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',))
    result = await dl.run_download(tab, spec, tmp_path)
    assert isinstance(result.value, DownloadRecord)
    assert result.value is result.record


async def test_output_view_path(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='export.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',), output='path')
    result = await dl.run_download(tab, spec, tmp_path)
    assert isinstance(result.value, Path)
    assert result.value == Path(result.record.path)


async def test_output_view_bytes(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='export.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',), output='bytes')
    result = await dl.run_download(tab, spec, tmp_path)
    assert result.value == CSV_BYTES


async def test_output_view_text(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='export.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',), output='text')
    result = await dl.run_download(tab, spec, tmp_path)
    assert result.value == CSV_BYTES.decode('utf-8')


async def test_allowed_types_mismatch_rejects_and_purges(tmp_path: Path) -> None:
    # An HTML interstitial served as text/html must fail when only csv is allowed,
    # and the quarantined bytes must be deleted.
    tab = _FakeTab(data=HTML_BYTES, content_type='text/html', filename='gotcha.csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='allowed_types'):
        await dl.run_download(tab, spec, tmp_path)
    assert not (tmp_path / 'gotcha.csv').exists()  # purged


async def test_default_deny_empty_allowlist(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv')
    spec = DownloadSpec(field='report', trigger='a.export', allowed_types=())
    with pytest.raises(DownloadError, match='default-deny'):
        await dl.run_download(tab, spec, tmp_path)


async def test_refetch_by_url(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='r.csv')
    spec = DownloadSpec(
        field='report', mode='refetch', url='https://sec.gov/r.csv', allowed_types=('csv',), output='parsed'
    )
    result = await dl.run_download(tab, spec, tmp_path)
    assert result.value[0]['month'] == 'Jan'


async def test_refetch_by_href_resolution(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='r.csv', href='https://sec.gov/data.csv')
    spec = DownloadSpec(field='report', mode='refetch', href='a.dl', allowed_types=('csv',))
    result = await dl.run_download(tab, spec, tmp_path)
    assert result.record.content_type == 'text/csv'


async def test_refetch_unsafe_scheme_rejected(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv')
    spec = DownloadSpec(field='report', mode='refetch', url='javascript:alert(1)', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='unsafe'):
        await dl.run_download(tab, spec, tmp_path)


async def test_execute_downloads_aggregates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl, 'quarantine_dir', lambda _domain, _base=None: tmp_path)
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='a.csv')
    specs = {'report': DownloadSpec(field='report', trigger='a.x', allowed_types=('csv',), output='parsed')}
    results = await dl.execute_downloads(tab, specs, 'sec.gov')
    assert set(results) == {'report'}
    assert results['report'].value[0]['revenue'] == '100'


def test_quarantine_dir_defaults_to_yosoi() -> None:
    target = dl.quarantine_dir('sec.gov')
    assert target.parent.name == 'downloads'
    assert '.yosoi' in target.parts


def test_quarantine_dir_honours_custom_base(tmp_path: Path) -> None:
    target = dl.quarantine_dir('sec.gov', base_dir=str(tmp_path / 'scratch'))
    assert target == tmp_path / 'scratch' / 'sec.gov'
    assert target.is_dir()


async def test_execute_downloads_uses_base_dir(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', filename='a.csv')
    specs = {'report': DownloadSpec(field='report', trigger='a.x', allowed_types=('csv',))}
    results = await dl.execute_downloads(tab, specs, 'sec.gov', base_dir=str(tmp_path))
    assert Path(results['report'].record.path).parent == tmp_path / 'sec.gov'


# --- error-path / branch coverage ------------------------------------------


class _EvalRaisesTab(_FakeTab):
    async def eval_js(self, expr: str) -> Any:
        raise RuntimeError('eval blew up')


class _ArmRaisesTab(_FakeTab):
    async def arm_download(self, dir: str, max_bytes: int | None = None) -> object:
        raise RuntimeError('cdp arm failed')


class _MissingFileTab(_FakeTab):
    def _write(self) -> _FakeOutcome:  # return an outcome whose path was never written
        assert self._dir is not None
        return _FakeOutcome(str(Path(self._dir) / 'does-not-exist.csv'), self._content_type, 7)


async def test_retrigger_without_trigger_fails(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv')
    spec = DownloadSpec(field='report', mode='retrigger', trigger=None, allowed_types=('csv',))
    with pytest.raises(DownloadError, match='retrigger mode requires'):
        await dl.run_download(tab, spec, tmp_path)


async def test_refetch_href_unresolved_fails(tmp_path: Path) -> None:
    tab = _FakeTab(data=CSV_BYTES, content_type='text/csv', href=None)  # eval returns None
    spec = DownloadSpec(field='report', mode='refetch', href='a.missing', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='could not resolve'):
        await dl.run_download(tab, spec, tmp_path)


async def test_refetch_href_eval_error_fails(tmp_path: Path) -> None:
    tab = _EvalRaisesTab(data=CSV_BYTES, content_type='text/csv', href='x')
    spec = DownloadSpec(field='report', mode='refetch', href='a.dl', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='could not resolve'):
        await dl.run_download(tab, spec, tmp_path)


async def test_capture_backend_error_wrapped(tmp_path: Path) -> None:
    tab = _ArmRaisesTab(data=CSV_BYTES, content_type='text/csv')
    spec = DownloadSpec(field='report', trigger='a.x', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='did not complete'):
        await dl.run_download(tab, spec, tmp_path)


async def test_unreadable_file_fails(tmp_path: Path) -> None:
    tab = _MissingFileTab(data=CSV_BYTES, content_type='text/csv')
    spec = DownloadSpec(field='report', trigger='a.x', allowed_types=('csv',))
    with pytest.raises(DownloadError, match='unreadable'):
        await dl.run_download(tab, spec, tmp_path)


async def test_parse_failure_fails(tmp_path: Path) -> None:
    tab = _FakeTab(data=b'{not valid json', content_type='application/json', filename='x.json')
    spec = DownloadSpec(field='cfg', trigger='a.x', allowed_types=('json',), output='parsed')
    with pytest.raises(DownloadError, match='could not parse'):
        await dl.run_download(tab, spec, tmp_path)


async def test_execute_downloads_empty_specs_returns_empty() -> None:
    assert await dl.execute_downloads(object(), None, 'sec.gov') == {}
    assert await dl.execute_downloads(object(), {}, 'sec.gov') == {}
