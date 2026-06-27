"""Tests for canonical operation request/result models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.operations import (
    ContractRef,
    CrawlRequest,
    ScrapeRequest,
    ScrapeUnitResult,
    SearchRequest,
    _envelope,
    _selector_level,
    execute_crawl,
    execute_scrape,
    execute_search,
    normalize_scrape_result,
    normalize_search_result,
    run_crawl,
    run_search,
)


class OpContract(Contract):
    title: str = ys.Title()


class OpContract2(Contract):
    url: str = ys.Url()


@pytest.mark.parametrize(
    ('urls', 'contracts', 'raw', 'expected'),
    [
        ('https://one.test', OpContract, [{'title': 'one'}], [('https://one.test', 'OpContract', [{'title': 'one'}])]),
        (
            ['https://one.test', 'https://two.test'],
            OpContract,
            {'https://one.test': [{'title': 'one'}], 'https://two.test': [{'title': 'two'}]},
            [
                ('https://one.test', 'OpContract', [{'title': 'one'}]),
                ('https://two.test', 'OpContract', [{'title': 'two'}]),
            ],
        ),
        (
            'https://one.test',
            [OpContract, OpContract2],
            {'OpContract': [{'title': 'one'}], 'OpContract2': [{'url': 'https://one.test'}]},
            [
                ('https://one.test', 'OpContract', [{'title': 'one'}]),
                ('https://one.test', 'OpContract2', [{'url': 'https://one.test'}]),
            ],
        ),
        (
            ['https://one.test', 'https://two.test'],
            [OpContract, OpContract2],
            {
                'https://one.test': {'OpContract': [{'title': 'one'}], 'OpContract2': [{'url': '1'}]},
                'https://two.test': {'OpContract': [{'title': 'two'}], 'OpContract2': [{'url': '2'}]},
            },
            [
                ('https://one.test', 'OpContract', [{'title': 'one'}]),
                ('https://one.test', 'OpContract2', [{'url': '1'}]),
                ('https://two.test', 'OpContract', [{'title': 'two'}]),
                ('https://two.test', 'OpContract2', [{'url': '2'}]),
            ],
        ),
    ],
)
def test_normalize_scrape_result_shapes(urls, contracts, raw, expected):
    request = ScrapeRequest.from_axes(urls, contracts)
    result = normalize_scrape_result(request, raw)
    assert [(unit.url, unit.contract, unit.records) for unit in result.results] == expected
    assert all(unit.status == 'ok' for unit in result.results)
    assert all(unit.record_count == len(unit.records) for unit in result.results)


def test_scrape_envelope_reports_empty_and_partial_states():
    assert _envelope([]).status == 'error'

    ok = ScrapeUnitResult(url='https://one.test', contract='OpContract', contract_fingerprint='fp', records=[])
    failed = ScrapeUnitResult(
        url='https://two.test',
        contract='OpContract',
        contract_fingerprint='fp',
        status='failed',
        error='boom',
    )

    assert _envelope([ok]).status == 'ok'
    assert _envelope([failed]).status == 'error'
    assert _envelope([ok, failed]).status == 'partial'


def test_contract_ref_doors_and_validation(tmp_path: Path):
    spec = OpContract.to_spec()
    spec_file = tmp_path / 'contract.json'
    spec_file.write_text(spec.model_dump_json())

    assert ContractRef.from_input(spec).to_contract().to_spec().fingerprint == spec.fingerprint
    assert ContractRef.from_input(spec.model_dump()).to_contract().to_spec().fingerprint == spec.fingerprint
    assert ContractRef.from_input(spec.model_dump_json()).to_contract().to_spec().fingerprint == spec.fingerprint
    assert ContractRef.from_input(str(spec_file)).to_contract().to_spec().fingerprint == spec.fingerprint
    assert ContractRef(ref='@NewsArticle').to_contract().__name__ == 'NewsArticle'
    assert ContractRef().to_contract().__name__ == 'NewsArticle'

    with pytest.raises(ValueError, match='non-empty'):
        ContractRef(ref='   ')
    with pytest.raises(TypeError, match='Unsupported'):
        ContractRef.from_input(cast(Any, object()))


def test_request_validators_and_axes():
    with pytest.raises(ValueError, match='urls'):
        ScrapeRequest(urls=[])
    with pytest.raises(ValueError, match='seeds'):
        CrawlRequest(seeds=[])

    scrape = ScrapeRequest.from_axes(['https://a.test'], None)
    assert scrape.url_axis_many is True
    assert scrape.contract_axis_many is False

    crawl = CrawlRequest.from_axes('https://seed.test', [OpContract, '@NewsArticle'], persist=True)
    assert crawl.seeds == ['https://seed.test']
    assert len(crawl.contract_classes()) == 2
    assert crawl.persist is True

    search = SearchRequest(query='  cascading labs  ')
    assert search.query == 'cascading labs'
    assert search.provider == 'ddgs'
    assert search.kind == 'text'
    assert search.backend == 'google,bing,brave'
    assert search.region == 'us-en'
    assert search.safesearch == 'moderate'
    assert search.max_results == 10
    assert search.page == 1

    with pytest.raises(ValueError, match='non-empty'):
        SearchRequest(query=' ')
    with pytest.raises(ValueError, match='greater than or equal to 1'):
        SearchRequest(query='x', max_results=0)
    with pytest.raises(ValueError, match='greater than or equal to 1'):
        SearchRequest(query='x', page=0)
    with pytest.raises(ValueError, match='boolean values'):
        SearchRequest(query='x', max_results=True)

    search_from_policy = SearchRequest.from_policy(
        'widgets',
        ys.Policy(search=ys.SearchPolicy(backend='bing', region='wt-wt', safesearch='off', max_results=7, page=2)),
        max_results=3,
    )
    assert search_from_policy.backend == 'bing'
    assert search_from_policy.region == 'wt-wt'
    assert search_from_policy.safesearch == 'off'
    assert search_from_policy.max_results == 3
    assert search_from_policy.page == 2


def test_selector_level_accepts_all_name_and_value():
    from yosoi.models.selectors import SelectorLevel

    assert _selector_level('all') == max(SelectorLevel)
    assert _selector_level('css') == SelectorLevel.CSS
    assert _selector_level('XPATH') == SelectorLevel.XPATH
    with pytest.raises(ValueError, match='not a valid SelectorLevel'):
        _selector_level('bogus')


def test_normalize_search_result_shapes_and_malformed_rows():
    request = SearchRequest(query='widgets', backend='google,bing,brave')
    result = normalize_search_result(
        request,
        [
            {'title': 'One', 'href': 'https://one.test', 'body': 'First result'},
            {'title': 'Two', 'url': 'https://two.test', 'snippet': 'Second result'},
        ],
    )

    assert result.urls == ['https://one.test', 'https://two.test']
    assert [(hit.rank, hit.title, hit.url, hit.snippet, hit.source, hit.backend) for hit in result.hits] == [
        (1, 'One', 'https://one.test', 'First result', 'ddgs', 'google,bing,brave'),
        (2, 'Two', 'https://two.test', 'Second result', 'ddgs', 'google,bing,brave'),
    ]

    with pytest.raises(ValueError, match='Malformed ddgs row 1: title'):
        normalize_search_result(request, [{'href': 'https://bad.test', 'body': 'missing title'}])
    with pytest.raises(ValueError, match='row must be an object'):
        normalize_search_result(request, cast(Any, ['not-a-row']))
    with pytest.raises(ValueError, match='absolute HTTP'):
        normalize_search_result(request, [{'title': 'Bad', 'href': 'javascript:void(0)', 'body': 'bad url'}])


async def test_execute_scrape_and_crawl_delegate(monkeypatch, mocker):
    import yosoi.api as api_module

    scrape_impl = mocker.AsyncMock(return_value=[{'title': 'ok'}])
    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)
    scrape_request = ScrapeRequest.from_axes(
        'https://one.test',
        OpContract,
        selector_level='all',
        save_formats=['json'],
        max_concurrency=3,
    )
    scrape_result = await execute_scrape(scrape_request)
    assert scrape_result.results[0].records == [{'title': 'ok'}]
    assert scrape_result.results[0].record_count == 1
    assert scrape_impl.await_args.kwargs['max_concurrency'] == 3
    assert scrape_impl.await_args.kwargs['save_formats'] == ['json']

    @dataclass
    class Summary:
        pages: int

    from yosoi.core.crawler import run as crawl_run

    crawl_impl = mocker.AsyncMock(return_value=Summary(pages=7))
    monkeypatch.setattr(crawl_run, '_crawl_impl', crawl_impl)
    crawl_request = CrawlRequest.from_axes(['https://a.test', 'https://b.test'], [OpContract], limit=2, progress=False)
    summary = await execute_crawl(crawl_request)
    assert summary.pages == 7
    assert crawl_impl.await_args.args[0] == ['https://a.test', 'https://b.test']
    assert crawl_impl.await_args.kwargs['contracts'][0].__name__ == 'OpContract'

    result = await run_crawl(crawl_request)
    assert result.summary == {'pages': 7}


async def test_execute_scrape_reports_metadata_and_llm_blocked(monkeypatch, mocker):
    import yosoi.api as api_module
    from yosoi.utils.exceptions import LLMBlockedError

    async def scrape_impl(*args, **kwargs):
        metadata = kwargs['metadata_collect']
        metadata[('https://one.test', 'OpContract')] = {
            'selector_source': 'cache',
            'cache_decision': 'hit',
            'llm_used': False,
        }
        return [{'title': 'ok'}]

    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)
    persist = mocker.patch('yosoi.operations._persist_scrape_unit', mocker.AsyncMock())

    result = await execute_scrape(ScrapeRequest.from_axes('https://one.test', OpContract))

    unit = result.results[0]
    assert result.status == 'ok'
    assert unit.selector_source == 'cache'
    assert unit.cache_decision == 'hit'
    assert unit.llm_used is False
    persist.assert_awaited_once()

    monkeypatch.setattr(api_module, '_scrape_impl', mocker.AsyncMock(side_effect=LLMBlockedError('cache_miss')))
    blocked = await execute_scrape(ScrapeRequest.from_axes('https://one.test', OpContract, allow_llm=False))

    failed = blocked.results[0]
    assert blocked.status == 'error'
    assert failed.status == 'failed'
    assert failed.cache_decision == 'llm_blocked'
    assert failed.llm_reason == 'cache_miss'


async def test_execute_scrape_reports_generic_failure_metadata(monkeypatch, mocker):
    import yosoi.api as api_module

    async def scrape_impl(*args, **kwargs):
        url = args[0]
        metadata = kwargs['metadata_collect']
        if url == 'https://one.test':
            metadata[(url, 'OpContract')] = {
                'selector_source': 'cache',
                'cache_decision': 'hit',
                'llm_used': False,
            }
            return [{'title': 'ok'}]
        metadata[(url, 'OpContract')] = {
            'selector_source': 'discovery',
            'cache_decision': 'miss',
            'llm_used': True,
            'llm_reason': 'cache_miss',
        }
        raise RuntimeError('extraction failed')

    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)
    persist = mocker.patch('yosoi.operations._persist_scrape_unit', mocker.AsyncMock())

    result = await execute_scrape(ScrapeRequest.from_axes(['https://one.test', 'https://two.test'], OpContract))

    assert result.status == 'partial'
    assert [unit.status for unit in result.results] == ['ok', 'failed']
    failed = result.results[1]
    assert failed.selector_source == 'discovery'
    assert failed.cache_decision == 'miss'
    assert failed.llm_used is True
    assert failed.llm_reason == 'cache_miss'
    assert failed.error == 'extraction failed'
    assert persist.await_count == 2


async def test_execute_search_delegates_and_run_search(monkeypatch, mocker):
    from yosoi.core.fetcher import search as search_fetcher

    fetch = mocker.AsyncMock(return_value=[{'title': 'One', 'href': 'https://one.test', 'body': 'First result'}])
    monkeypatch.setattr(search_fetcher, 'fetch_ddgs_text', fetch)

    request = SearchRequest(query='widgets', backend='google,bing,brave', region='us-en', max_results=3)
    result = await execute_search(request)

    assert result.urls == ['https://one.test']
    assert fetch.await_args.args == (request,)

    second = await run_search(request)
    assert second.urls == ['https://one.test']
    assert fetch.await_count == 2
