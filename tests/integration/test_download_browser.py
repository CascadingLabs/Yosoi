"""ys.File() download integration tests — real Chromium downloading from a local server.

Gated behind @pytest.mark.browser_integration (YOSOI_INTEGRATION=1). Exercises both download
modes end to end through a live VoidCrawl tab: refetch (download a URL) and retrigger
(click a link → capture the download), plus content-addressing/dedup, drift, and the
allowed_types gate. Deterministic and offline — a tiny stdlib HTTP server serves the CSV.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

from yosoi.core.fetcher.downloads import run_download
from yosoi.models.download import DownloadSpec

_CSV = b'month,revenue\nJan,100\nFeb,120\n'
_HTML = b'<!doctype html><html><body><a id="dl" href="/data.csv" download>Download CSV</a></body></html>'
_ROWS = [{'month': 'Jan', 'revenue': '100'}, {'month': 'Feb', 'revenue': '120'}]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body, ct = (_CSV, 'text/csv') if self.path == '/data.csv' else (_HTML, 'text/html')
        self.send_response(200)
        self.send_header('Content-Type', ct)
        if self.path == '/data.csv':
            self.send_header('Content-Disposition', 'attachment; filename=data.csv')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence per-request logging
        pass


@pytest.fixture
def csv_server():
    """Serve an HTML page with a CSV download link + the CSV itself on a random port."""
    server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()


@pytest.mark.browser_integration
async def test_file_download_both_modes_dedup_and_drift(csv_server, no_sandbox, tmp_path) -> None:
    """Refetch + retrigger both download & parse the CSV; identical bytes dedup; drift is flagged."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher

    async with (
        HeadlessFetcher(console=None, timeout=30, no_sandbox=no_sandbox, allow_downloads=True) as driver,
        driver.browse(f'{csv_server}/') as tab,
    ):
        refetch = await run_download(
            tab,
            DownloadSpec(
                field='rows', mode='refetch', url=f'{csv_server}/data.csv', allowed_types=('csv',), output='parsed'
            ),
            tmp_path,
        )
        retrigger = await run_download(
            tab,
            DownloadSpec(field='rows', mode='retrigger', trigger='a#dl', allowed_types=('csv',), output='parsed'),
            tmp_path,
        )

    assert refetch.value == _ROWS
    assert retrigger.value == _ROWS
    # Content-addressed: stored under sha256; identical bytes dedup to the same blob.
    assert Path(refetch.record.path).name == f'{refetch.record.sha256}.csv'
    assert retrigger.record.path == refetch.record.path
    # Drift: first download is new, the identical re-download is unchanged.
    assert refetch.changed is True
    assert retrigger.changed is False
    index = json.loads((tmp_path / 'index.json').read_text())
    assert list(index['blobs']) == [refetch.record.sha256]


@pytest.mark.browser_integration
async def test_file_download_rejects_disallowed_type(csv_server, no_sandbox, tmp_path) -> None:
    """A real CSV is rejected (and purged) when only mp4 is allowed."""
    from yosoi.core.fetcher.voiddriver import HeadlessFetcher
    from yosoi.utils.exceptions import DownloadError

    async with (
        HeadlessFetcher(console=None, timeout=30, no_sandbox=no_sandbox, allow_downloads=True) as driver,
        driver.browse(f'{csv_server}/') as tab,
    ):
        with pytest.raises(DownloadError, match='allowed_types'):
            await run_download(
                tab,
                DownloadSpec(field='clip', mode='refetch', url=f'{csv_server}/data.csv', allowed_types=('mp4',)),
                tmp_path,
            )
