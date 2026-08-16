"""CAS-228 over a real HTTP transport.

Every declaration pattern in ``tests/fixtures/encoding`` is served from a localhost
server with the exact ``Content-Type`` header the manifest records, then fetched with a
real :class:`SimpleFetcher`. This is the end-to-end shape of the bug: the header, the
bytes, and the decode all have to line up over the wire, not in a mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.local_site import Route, serve
from yosoi.core.fetcher.encoding import decode_html
from yosoi.core.fetcher.simple import SimpleFetcher

FIXTURE_DIR = Path(__file__).parent.parent / 'fixtures' / 'encoding'
MANIFEST: dict[str, dict[str, str | None]] = json.loads((FIXTURE_DIR / 'manifest.json').read_text())
pytestmark = pytest.mark.local_http

REPLACEMENT = '�'


def _content_type(http_charset: str | None) -> str:
    return 'text/html' if http_charset is None else f'text/html; charset={http_charset}'


@pytest.mark.parametrize('filename', sorted(MANIFEST))
def test_fixture_bytes_decode_to_readable_text(filename: str) -> None:
    """Offline: the resolver picks the right codec straight from the fixture bytes."""
    case = MANIFEST[filename]
    content = (FIXTURE_DIR / filename).read_bytes()

    text, encoding = decode_html(content, declared=case['http_charset'])

    assert case['marker'] in text
    assert REPLACEMENT not in text
    if case['expected_encoding'] is not None:
        assert encoding == case['expected_encoding']


@pytest.mark.asyncio
@pytest.mark.parametrize('filename', sorted(MANIFEST))
async def test_simple_fetcher_decodes_over_real_http(filename: str) -> None:
    """Online (localhost): the same fixture served over HTTP survives the fetcher path."""
    case = MANIFEST[filename]
    routes = {
        '/page': Route(
            body=(FIXTURE_DIR / filename).read_bytes(),
            content_type=_content_type(case['http_charset']),
        )
    }

    with serve(routes) as site:
        async with SimpleFetcher(min_delay=0, max_delay=0) as fetcher:
            result = await fetcher.fetch(site.url('/page'))

    assert result.html is not None
    assert case['marker'] in result.html
    assert REPLACEMENT not in result.html


@pytest.mark.asyncio
async def test_whole_corpus_is_mojibake_free_in_one_pass() -> None:
    """Stress the fetcher across every encoding in the corpus on one live server."""
    routes = {
        f'/{name}': Route(
            body=(FIXTURE_DIR / name).read_bytes(),
            content_type=_content_type(case['http_charset']),
        )
        for name, case in MANIFEST.items()
    }

    corrupted: list[str] = []
    with serve(routes) as site:
        async with SimpleFetcher(min_delay=0, max_delay=0) as fetcher:
            for name, case in MANIFEST.items():
                result = await fetcher.fetch(site.url(f'/{name}'))
                marker = case['marker']
                assert marker is not None
                if result.html is None or marker not in result.html or REPLACEMENT in result.html:
                    corrupted.append(name)

    assert corrupted == []
    assert len(site.requests) == len(MANIFEST)
