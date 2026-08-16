"""Opt-in live smoke tests for CAS-228 charset resolution against real non-UTF-8 sites.

The corpus was chosen by probing the live web for pages that still ship legacy encodings,
one per declaration pattern that actually occurs out there:

* ``kakaku.com`` sends **no** HTTP charset and declares ``<meta charset="shift_jis">`` —
  the exact pattern that produced mojibake before the fix.
* ``lib.ru`` sends a correct ``koi8-r``/``windows-1251`` HTTP header and no meta tag — the
  control case that worked before and must keep working.

Live sites drift; these are smoke tests, not CI gates. Run with ``YOSOI_LIVE_SMOKE=1``.
"""

from __future__ import annotations

import os

import pytest

from yosoi.core.fetcher.simple import SimpleFetcher

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run live encoding smoke tests',
    ),
]

REPLACEMENT = '�'

# url -> (declaration pattern, a script-specific string the decoded page must contain)
LIVE_CASES = {
    'https://kakaku.com/': ('meta-only shift_jis', '価格'),
    'https://kakaku.com/pc/': ('meta-only shift_jis', 'パソコン'),
    'http://www.lib.ru/': ('header-only koi8-r', 'Библиотека'),
    'http://lib.ru/PROZA/': ('header-only windows-1251', 'Проза'),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(('url', 'case'), sorted(LIVE_CASES.items()))
async def test_live_legacy_encoding_page_is_readable(url: str, case: tuple[str, str]) -> None:
    _pattern, marker = case
    async with SimpleFetcher(min_delay=0.5, max_delay=1.5, allow_redirects=True) as fetcher:
        result = await fetcher.fetch(url)

    assert result.html is not None, result.block_reason
    assert marker in result.html
    # A handful of replacement chars can legitimately appear in user-generated content on a
    # live page; a decoding failure produces them at scale, so assert on the rate.
    assert result.html.count(REPLACEMENT) / len(result.html) < 0.001
