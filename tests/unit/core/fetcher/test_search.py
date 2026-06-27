"""Tests for the DDGS search fetcher boundary."""

from __future__ import annotations

import pytest
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_none

from yosoi.core.fetcher import search as search_fetcher
from yosoi.operations import SearchRequest


def test_run_ddgs_text_sync_forwards_request_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeDDGS:
        def __enter__(self) -> FakeDDGS:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def text(self, query: str, **kwargs: object) -> list[dict[str, object]]:
            captured['query'] = query
            captured['kwargs'] = kwargs
            return [{'title': 'One', 'href': 'https://one.test', 'body': 'First'}]

    monkeypatch.setattr(search_fetcher, 'DDGS', FakeDDGS)
    request = SearchRequest(
        query='widgets',
        backend='google,bing,brave',
        region='us-en',
        safesearch='moderate',
        timelimit='w',
        max_results=7,
        page=2,
    )

    rows = search_fetcher._run_ddgs_text_sync(request)

    assert rows == [{'title': 'One', 'href': 'https://one.test', 'body': 'First'}]
    assert captured == {
        'query': 'widgets',
        'kwargs': {
            'backend': 'google,bing,brave',
            'region': 'us-en',
            'safesearch': 'moderate',
            'timelimit': 'w',
            'max_results': 7,
            'page': 2,
        },
    }


async def test_fetch_ddgs_text_uses_retryer_and_thread_offload(mocker) -> None:
    request = SearchRequest(query='widgets')
    retryer = AsyncRetrying(
        stop=stop_after_attempt(2),
        wait=wait_none(),
        retry=retry_if_exception_type(RuntimeError),
        reraise=True,
    )
    retry_factory = mocker.patch('yosoi.core.fetcher.search.get_async_retryer', return_value=retryer)
    to_thread = mocker.patch(
        'yosoi.core.fetcher.search.asyncio.to_thread',
        mocker.AsyncMock(
            side_effect=[
                RuntimeError('temporary'),
                [{'title': 'One', 'href': 'https://one.test', 'body': 'First'}],
            ]
        ),
    )

    rows = await search_fetcher.fetch_ddgs_text(request)

    assert rows == [{'title': 'One', 'href': 'https://one.test', 'body': 'First'}]
    assert to_thread.await_count == 2
    assert retry_factory.call_args.kwargs['max_attempts'] == 3
    assert retry_factory.call_args.kwargs['wait_min'] == 0.5
