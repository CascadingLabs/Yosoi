"""Tests for canonical operation request/result models."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

import yosoi as ys
import yosoi.operations as ops
from yosoi.models.contract import Contract
from yosoi.operations import (
    ContentRequest,
    ContractRef,
    CrawlRequest,
    FetchRequest,
    MapRequest,
    MapResult,
    ScrapeRequest,
    ScrapeUnitResult,
    SearchRequest,
    _envelope,
    _selector_level,
    execute_content,
    execute_crawl,
    execute_fetch,
    execute_map,
    execute_scrape,
    execute_search,
    execute_searches,
    normalize_scrape_result,
    normalize_search_result,
    run_content,
    run_crawl,
    run_fetch,
    run_map,
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
    with pytest.raises(ValueError, match='boolean values'):
        SearchRequest(query='x', page=True)
    with pytest.raises(ValueError, match='timelimit'):
        SearchRequest(query='x', timelimit='  ')
    assert SearchRequest(query='x', timelimit=' d ').timelimit == 'd'
    with pytest.raises(ValueError, match='Input should'):
        FetchRequest(urls=['https://one.test'], view=object())
    with pytest.raises(ValueError, match='Input should'):
        FetchRequest(urls=['https://one.test'], include=object())

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


async def test_execute_scrape_shape_delegates_axis_shape(monkeypatch, mocker):
    import yosoi.api as api_module

    scrape_impl = mocker.AsyncMock(return_value={'https://one.test': {'OpContract': [{'title': 'ok'}]}})
    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)

    request = ScrapeRequest.from_axes(
        ['https://one.test'],
        [OpContract, OpContract2],
        selector_level='all',
        allow_llm=False,
        max_concurrency=2,
    )
    result = await ops._execute_scrape_shape(request)

    assert result == {'https://one.test': {'OpContract': [{'title': 'ok'}]}}
    assert scrape_impl.await_args.args[0] == ['https://one.test']
    assert [contract.__name__ for contract in scrape_impl.await_args.args[1]] == ['OpContract', 'OpContract2']
    assert scrape_impl.await_args.kwargs['allow_llm'] is False
    assert scrape_impl.await_args.kwargs['max_concurrency'] == 2


async def test_execute_scrape_failure_paths_and_persist_best_effort(monkeypatch, mocker):
    import yosoi.api as api_module
    import yosoi.storage.cache_metrics_libsql as metrics_module
    from yosoi.utils.exceptions import LLMBlockedError

    outcomes = [LLMBlockedError('cache_miss'), RuntimeError('boom')]

    async def scrape_impl(*_args, **_kwargs):
        outcome = outcomes.pop(0)
        raise outcome

    class RaisingStore:
        async def __aenter__(self):
            raise RuntimeError('metrics unavailable')

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)
    monkeypatch.setattr(metrics_module, 'LibSQLCacheMetricsStore', RaisingStore)

    result = await execute_scrape(ScrapeRequest.from_axes(['https://one.test', 'https://two.test'], OpContract))

    assert result.status == 'error'
    assert [unit.cache_decision for unit in result.results] == ['llm_blocked', 'unknown']
    assert result.results[0].llm_reason == 'cache_miss'
    assert result.results[1].error == 'boom'
    assert result.results[1].quality_issues == ['boom']


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


async def test_execute_crawl_enforces_deadline(monkeypatch):
    from yosoi.core.crawler import run as crawl_run

    async def slow_crawl(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(crawl_run, '_crawl_impl', slow_crawl)

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await execute_crawl(CrawlRequest.from_axes('https://one.test', deadline_seconds=0.01))


async def test_execute_content_fetches_clean_document(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult

    class Fetcher:
        async def fetch(self, url: str) -> FetchResult:
            return FetchResult(
                url=url,
                status_code=200,
                html=(
                    '<html><head><title>Example Page</title><script>bad()</script></head>'
                    '<body><header>Nav</header><main><h1>Example Page</h1>'
                    '<p>Hello <a href="/docs">world</a>.</p>'
                    '<table><tr><th>Plan</th><th>Price</th></tr><tr><td>Starter</td><td>$49</td></tr></table>'
                    '<div><strong>Freelance</strong><span>$49<span>/mo</span></span></div>'
                    '</main></body></html>'
                ),
                fetch_time=0.5,
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())

    result = await execute_content(ContentRequest.from_axes('https://one.test', include_html=True))
    unit = result.results[0]

    assert result.status == 'ok'
    assert unit.title == 'Example Page'
    assert unit.status_code == 200
    assert unit.fetcher_type == 'auto'
    assert unit.text == 'Example Page Hello world. Plan Price Starter $49 Freelance $49 /mo'
    assert unit.markdown.startswith('# Example Page\n\nSource: https://one.test\n\n## Example Page\n\n')
    assert '[world](https://one.test/docs)' in unit.markdown
    assert '| Plan | Price |' in unit.markdown
    assert '| --- | --- |' in unit.markdown
    assert '| Starter | $49 |' in unit.markdown
    assert '- Freelance' in unit.markdown
    assert '- $49/mo' in unit.markdown
    assert unit.html is not None
    assert '<script>' not in unit.html
    assert unit.links == [{'text': 'world', 'url': 'https://one.test/docs'}]
    assert unit.metadata['source_url'] == 'https://one.test'
    assert unit.metadata['content_hash']
    assert result.success is True
    assert result.data is not None
    assert result.data['markdown'] == unit.markdown
    assert result.data['metadata']['title'] == 'Example Page'
    assert result.documents == [unit.data]
    assert result.errors == []


async def test_run_content_reports_partial_failures(monkeypatch):
    import yosoi.core.fetcher as fetcher_module

    class Fetcher:
        async def fetch(self, _url: str) -> None:
            raise RuntimeError('blocked')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())

    result = await run_content(ContentRequest.from_axes(['https://one.test', 'https://two.test']))

    assert result.status == 'error'
    assert [unit.status for unit in result.results] == ['failed', 'failed']
    assert all(unit.error == 'blocked' for unit in result.results)


async def test_execute_fetch_batches_urls_concurrently_and_preserves_order(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    active = 0
    peak_active = 0

    class Fetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            try:
                await asyncio.sleep(0.01)
                return HtmlFetchResult(url=url, status_code=200, html=f'<html><body>{url}</body></html>')
            finally:
                active -= 1

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())
    urls = ['https://one.test', 'https://two.test', 'https://three.test']

    result = await execute_fetch(FetchRequest.from_axes(urls, max_concurrency=2))

    assert peak_active == 2
    assert [unit.url for unit in result.results] == urls


async def test_execute_fetch_continues_after_a_failed_batch_unit(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class Fetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            if url == 'https://two.test':
                raise RuntimeError('blocked')
            return HtmlFetchResult(url=url, status_code=200, html=f'<html><body>{url}</body></html>')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())

    result = await execute_fetch(
        FetchRequest.from_axes(['https://one.test', 'https://two.test', 'https://three.test'], max_concurrency=2)
    )

    assert [unit.status for unit in result.results] == ['ok', 'failed', 'ok']
    assert result.results[1].error == 'blocked'
    assert result.status == 'partial'


async def test_execute_fetch_paginates_and_includes_metadata(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class Fetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(
                url=url,
                status_code=200,
                html=(
                    '<html><head><title>Example Page</title></head>'
                    '<body><main><h1>Example Page</h1><p>Hello world.</p>'
                    '<a href="/pricing">Pricing</a></main></body></html>'
                ),
                fetch_time=0.25,
                headers={'content-type': 'text/html'},
                endpoints=['https://one.test/api/prices'],
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())

    result = await execute_fetch(
        FetchRequest.from_axes(
            'https://one.test',
            view='text',
            page_size=12,
            include=['headers', 'endpoints', 'links', 'fingerprint'],
        )
    )
    unit = result.results[0]

    assert result.status == 'ok'
    assert unit.content == 'Example Page'
    assert unit.truncated is True
    assert unit.next_page == 2
    assert unit.headers == {'content-type': 'text/html'}
    assert unit.endpoints == ['https://one.test/api/prices']
    assert unit.links == [{'text': 'Pricing', 'url': 'https://one.test/pricing'}]
    assert unit.fingerprint is not None
    assert result.data is not None
    assert result.data['text'] == 'Example Page'


async def test_execute_fetch_contract_probe_verifies_cached_selectors(monkeypatch, mocker):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult
    from yosoi.models.snapshot import selector_dict_to_snapshot

    class Fetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(
                url=url,
                status_code=200,
                html='<html><body><main><h1>Headline</h1></main></body></html>',
            )

        async def close(self) -> None:
            return None

    class Storage:
        async def load_snapshots(self, _domain: str, contract_sig: str | None = None, *, url: str | None = None):
            assert contract_sig == OpContract.to_spec().fingerprint
            return {'title': selector_dict_to_snapshot({'primary': 'h1'})}

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())
    mocker.patch('yosoi.storage.persistence.SelectorStorage', return_value=Storage())

    result = await run_fetch(FetchRequest.from_axes('https://one.test/story', contracts=OpContract))
    probe = result.results[0].contract_probes[0]

    assert probe.contract == 'OpContract'
    assert probe.cached_fields == ['title']
    assert probe.verified_fields == ['title']
    assert probe.fit == 'strong'
    assert probe.fit_score == 1.0


async def test_execute_fetch_contract_probe_does_not_report_strong_with_unresolved_extractor(monkeypatch, mocker):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult
    from yosoi.models.snapshot import selector_dict_to_snapshot

    class MixedProbeContract(Contract):
        title: str = ys.Title()
        author: str = ys.Extractor()

    class Fetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(url=url, status_code=200, html='<html><body><h1>Headline</h1></body></html>')

        async def close(self) -> None:
            return None

    class Storage:
        async def load_snapshots(self, _domain: str, contract_sig: str | None = None, *, url: str | None = None):
            assert contract_sig == MixedProbeContract.to_spec().fingerprint
            return {'title': selector_dict_to_snapshot({'primary': 'h1'})}

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: Fetcher())
    mocker.patch('yosoi.storage.persistence.SelectorStorage', return_value=Storage())

    result = await run_fetch(FetchRequest.from_axes('https://one.test/story', contracts=MixedProbeContract))
    probe = result.results[0].contract_probes[0]

    assert probe.required_fields == ['author', 'title']
    assert probe.resolvable_extractor_fields == []
    assert probe.fit == 'partial'
    assert probe.fit_score == 0.5


def test_fetch_result_document_projection_and_envelope_statuses():
    ok = ops.FetchUnitResult(
        url='https://one.test',
        final_url='https://one.test/final',
        title='One',
        view='html',
        content='<main>Hello</main>',
        content_chars=18,
        total_chars=18,
        html='<main>Hello</main>',
        links=[{'text': 'Pricing', 'url': 'https://one.test/pricing'}],
        artifacts={'markdown.md': '/tmp/markdown.md'},
    )
    failed = ops.FetchUnitResult(url='https://bad.test', status='failed', error='blocked')

    assert ok.metadata['source_url'] == 'https://one.test'
    assert ok.metadata['final_url'] == 'https://one.test/final'
    assert ok.metadata['content_hash']
    assert ok.data is not None
    assert ok.data['html'] == '<main>Hello</main>'
    assert ok.data['links'][0]['text'] == 'Pricing'
    assert ok.data['artifacts']['markdown.md'] == '/tmp/markdown.md'
    assert failed.data is None

    partial = ops.FetchResult(status='partial', results=[ok, failed])
    assert partial.success is False
    assert partial.data is None
    assert partial.documents == [ok.data]
    assert partial.errors == [{'url': 'https://bad.test', 'error': 'blocked'}]
    assert ops._fetch_envelope([]).status == 'error'
    assert ops._fetch_envelope([ok, failed]).status == 'partial'
    assert ops._fetch_envelope([failed]).status == 'error'


def test_fetch_request_normalization_and_rich_document_projection():
    request = FetchRequest.from_axes(
        'https://one.test',
        view='rendered-html',
        include='network, links, ax',
        contracts=OpContract,
    )

    assert request.view == 'rendered_html'
    assert request.include == ['endpoints', 'links', 'ax']
    assert [contract.to_contract() for contract in request.contracts] == [OpContract]
    assert FetchRequest.from_axes('en.wikipedia.org/wiki/Web_scraping').urls == [
        'https://en.wikipedia.org/wiki/Web_scraping'
    ]
    assert FetchRequest.from_axes('//en.wikipedia.org/wiki/Web_scraping?oldid=1#History').urls == [
        'https://en.wikipedia.org/wiki/Web_scraping?oldid=1#History'
    ]
    assert ContentRequest.from_axes('one.test/docs').urls == ['https://one.test/docs']
    with pytest.raises(ValueError, match='whitespace'):
        FetchRequest.from_axes('en.wikipedia.org/wiki/Web scraping')
    with pytest.raises(ValueError, match='absolute HTTP'):
        FetchRequest.from_axes('ftp://example.com/file')
    assert FetchRequest.from_axes('https://one.test', include=None).include == []
    assert (
        ops._effective_fetcher_type(FetchRequest.from_axes('https://one.test', fetcher_type='simple'), 'auto')
        == 'simple'
    )
    assert ops._effective_fetcher_type(FetchRequest.from_axes('https://one.test', view='raw_html'), 'auto') == 'simple'
    assert ops._jsonable(object()).startswith('<object object at ')
    auto_fast = ops._content_fetcher_kwargs(ys.Policy(), 'auto', fast_fetch=True)
    assert auto_fast['simple_first'] is True
    assert auto_fast['crawl_frontier_only'] is True
    headless_fast = ops._content_fetcher_kwargs(ys.Policy(), 'headless', fast_fetch=True)
    assert headless_fast['lightweight_fetch'] is True
    assert 'lightweight_fetch' not in ops._content_fetcher_kwargs(ys.Policy(), 'headless')
    with pytest.raises(ValueError, match='urls must contain at least one URL'):
        FetchRequest(urls=[])
    with pytest.raises(ValueError, match='urls must contain at least one URL'):
        ContentRequest(urls=[])

    unit = ops.FetchUnitResult(
        url='https://one.test',
        view='markdown',
        content='# One',
        headers={'content-type': 'text/html'},
        endpoints=['https://one.test/api'],
        fingerprint={'shape': 'pricing'},
        ax_snapshot={'role': 'document'},
        contract_probes=[ops.ContractProbeResult(contract='OpContract', contract_fingerprint='fp')],
    )

    assert unit.data is not None
    assert unit.data['markdown'] == '# One'
    assert unit.data['headers'] == {'content-type': 'text/html'}
    assert unit.data['endpoints'] == ['https://one.test/api']
    assert unit.data['fingerprint'] == {'shape': 'pricing'}
    assert unit.data['ax_snapshot'] == {'role': 'document'}
    assert unit.data['contract_probes'][0]['contract'] == 'OpContract'
    assert ops.FetchResult(status='ok', results=[unit]).success is True


def test_fetch_html_helpers_degrade_when_parser_raises(monkeypatch):
    def raise_parse(_html: str):
        raise ValueError('bad html')

    monkeypatch.setattr(ops.lxml.html, 'fromstring', raise_parse)

    assert ops._text_from_html('<p>fallback</p>') == 'fallback'
    assert ops._title_from_html('<title>x</title>') is None
    assert ops._links_from_html('<a href="/x">x</a>', 'https://one.test') == []
    assert ops._markdown_blocks_from_html('<p>x</p>', 'fallback', 'https://one.test') == 'fallback'


def test_fetch_markdown_helpers_cover_sparse_and_fallback_shapes():
    assert ops._text_from_html('') == ''
    assert ops._title_from_html('') is None
    assert ops._links_from_html('', 'https://one.test') == []
    assert ops._text_from_html('<') == '<'
    assert ops._title_from_html('<') is None
    assert ops._links_from_html('<', 'https://one.test') == []
    assert ops._markdown_block_for_element(ops.lxml.etree.Comment('comment'), 'https://one.test') is None
    assert ops._markdown_body_or_text([], 'plain fallback') == 'plain fallback'

    html = (
        '<main>'
        '<p>See <a>plain link</a> <a href=""></a>.</p>'
        '<ul><li>Item</li></ul>'
        '<blockquote>Quote</blockquote>'
        '<pre>code()</pre>'
        '<table></table>'
        '<span>Standalone</span>'
        '<p><span>Nested inline</span></p>'
        f'<span>{"x" * 121}</span>'
        '<span><div>block child</div></span>'
        '<p>Currency $99 only appears in extracted body.</p>'
        '<p><a href="/dup">Same</a><a href="/dup">Same</a></p>'
        '</main>'
    )
    text = 'See plain link. Item Quote code() Standalone Nested inline block child Currency $99 only appears in extracted body.'
    markdown = ops._markdown_blocks_from_html(html, text, 'https://one.test')

    assert 'plain link' in markdown
    assert '- Item' in markdown
    assert '> Quote' in markdown
    assert '```\ncode()\n```' in markdown
    assert '- Standalone' in markdown
    assert '## Extracted Text' not in markdown
    assert '## Extracted Text' in ops._markdown_body_or_text(
        ['Plan name with enough surrounding content'],
        'Plan name with enough surrounding content $99',
    )
    assert ops._markdown_table_for_element(ops.lxml.html.fromstring('<table></table>')) is None


def test_fetch_helpers_render_views_metadata_and_bundle(tmp_path):
    request = FetchRequest.from_axes('https://one.test', view='links', output_dir=str(tmp_path))
    links = [{'text': 'Pricing', 'url': 'https://one.test/pricing'}]
    metadata = ops._fetch_metadata_doc(
        url='https://one.test',
        final_url='https://one.test/final',
        status_code=200,
        title='One',
        fetcher_type='simple',
        fetch_time=0.1,
        raw_html='<html></html>',
        cleaned_html='<main>Hello</main>',
        text='Hello',
        include={'headers', 'endpoints', 'links', 'fingerprint', 'ax'},
        headers={'content-type': 'text/html'},
        endpoints=['https://one.test/api'],
        links=links,
        fingerprint={'shape': 'abc'},
        ax_snapshot={'role': 'document'},
        contract_probes=[ops.ContractProbeResult(contract='OpContract', contract_fingerprint='fp')],
    )

    assert metadata['headers'] == {'content-type': 'text/html'}
    assert metadata['endpoints'] == ['https://one.test/api']
    assert metadata['links'] == links
    assert metadata['fingerprint'] == {'shape': 'abc'}
    assert metadata['ax_snapshot'] == {'role': 'document'}
    assert metadata['contract_probes'][0]['contract'] == 'OpContract'
    assert ops._view_content(
        request,
        raw_html='raw',
        cleaned_html='clean',
        text='txt',
        markdown='md',
        links=links,
        metadata=metadata,
        ax_snapshot={'role': 'document'},
    ).startswith('[\n')
    assert ops._view_content(
        request.model_copy(update={'view': 'metadata'}),
        raw_html='raw',
        cleaned_html='clean',
        text='txt',
        markdown='md',
        links=links,
        metadata=metadata,
        ax_snapshot=None,
    ).startswith('{\n')
    assert ops._view_content(
        request.model_copy(update={'view': 'ax'}),
        raw_html='raw',
        cleaned_html='clean',
        text='txt',
        markdown='md',
        links=links,
        metadata=metadata,
        ax_snapshot={'role': 'document'},
    ).startswith('{\n')
    assert ops._view_content(
        request.model_copy(update={'view': 'bundle'}),
        raw_html='raw',
        cleaned_html='clean',
        text='txt',
        markdown='md',
        links=links,
        metadata=metadata,
        ax_snapshot=None,
    ).startswith('{\n')
    assert (
        ops._view_content(
            request.model_copy(update={'view': 'raw_html'}),
            raw_html='raw',
            cleaned_html='clean',
            text='txt',
            markdown='md',
            links=links,
            metadata=metadata,
            ax_snapshot=None,
        )
        == 'raw'
    )
    assert (
        ops._view_content(
            request.model_copy(update={'view': 'clean_html'}),
            raw_html='raw',
            cleaned_html='clean',
            text='txt',
            markdown='md',
            links=links,
            metadata=metadata,
            ax_snapshot=None,
        )
        == 'clean'
    )
    assert (
        ops._view_content(
            request.model_copy(update={'view': 'markdown'}),
            raw_html='raw',
            cleaned_html='clean',
            text='txt',
            markdown='md',
            links=links,
            metadata=metadata,
            ax_snapshot=None,
        )
        == 'md'
    )

    page, truncated, next_page = ops._paginate_content('abcdef', page=2, page_size=2)
    assert (page, truncated, next_page) == ('cd', True, 3)
    single_dir = ops._fetch_artifact_dir(str(tmp_path / 'single'), 'https://one.test/path', multiple=False)
    multi_dir = ops._fetch_artifact_dir(str(tmp_path / 'multi'), 'https://www.one.test/path', multiple=True)
    assert single_dir.exists()
    assert multi_dir.name.startswith('one.test-path-')
    files = ops._write_fetch_bundle(
        request,
        url='https://one.test',
        raw_html='raw',
        static_html='static',
        cleaned_html='clean',
        text='txt',
        markdown='md',
        links=links,
        metadata=metadata,
        headers={'content-type': 'text/html'},
        endpoints=['https://one.test/api'],
        fingerprint={'shape': 'abc'},
        ax_snapshot={'role': 'document'},
    )
    assert {
        'raw.html',
        'static.html',
        'rendered.html',
        'clean.html',
        'text.txt',
        'markdown.md',
        'links.json',
        'headers.json',
        'network.json',
        'metadata.json',
        'fingerprint.json',
        'ax.json',
    } <= set(files)


def test_content_result_projection_and_jsonable_helpers():
    @dataclass
    class Row:
        name: str
        count: int

    ok = ops.ContentUnitResult(
        url='https://one.test',
        title='One',
        markdown='# One',
        text='One',
        html='<main>One</main>',
        links=[{'text': 'Home', 'url': 'https://one.test'}],
    )
    failed = ops.ContentUnitResult(url='https://bad.test', status='failed', error='blocked')
    result = ops.ContentResult(status='partial', results=[ok, failed])

    assert ok.metadata['content_hash']
    assert ok.data is not None
    assert ok.data['html'] == '<main>One</main>'
    assert failed.data is None
    assert result.success is False
    assert result.data is None
    assert result.documents == [ok.data]
    assert result.errors == [{'url': 'https://bad.test', 'error': 'blocked'}]
    assert ops._content_envelope([]).status == 'error'
    assert ops._content_envelope([ok, failed]).status == 'partial'
    assert ops._content_envelope([failed]).status == 'error'
    assert ops._jsonable(Row('a', 1)) == {'name': 'a', 'count': 1}
    assert ops._jsonable({'row': Row('b', 2), 'items': [Row('c', 3)]}) == {
        'row': {'name': 'b', 'count': 2},
        'items': [{'name': 'c', 'count': 3}],
    }


async def test_fetch_static_html_context_manager_and_exception_paths(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class ContextFetcher:
        entered = False

        async def __aenter__(self):
            self.entered = True
            return self

        async def __aexit__(self, *_args):
            self.entered = False

        async def fetch(self, url: str) -> HtmlFetchResult:
            assert self.entered
            return HtmlFetchResult(url=url, status_code=200, html='<html><body>static</body></html>')

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: ContextFetcher())
    assert await ops._fetch_static_html('https://one.test', ys.Policy()) == '<html><body>static</body></html>'

    class RaisingFetcher:
        async def fetch(self, _url: str) -> HtmlFetchResult:
            raise RuntimeError('boom')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: RaisingFetcher())
    assert await ops._fetch_static_html('https://one.test', ys.Policy()) is None


async def test_execute_fetch_unit_context_manager_and_advisory_fingerprint_failure(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    import yosoi.generalization.fingerprint as fingerprint_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class ContextFetcher:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(
                url=url,
                status_code=200,
                html='<html><head><title>Ctx</title></head><body><main><p>ok</p></main></body></html>',
            )

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: ContextFetcher())
    monkeypatch.setattr(
        fingerprint_module.PageFingerprint, 'of', lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('fp'))
    )

    result = await execute_fetch(FetchRequest.from_axes('https://ctx.test', view='text'))

    assert result.status == 'ok'
    assert result.results[0].content == 'ok'
    assert result.results[0].fingerprint is None


async def test_execute_fetch_catches_unexpected_unit_exception(monkeypatch):
    async def fail_unit(_request, _url):
        raise RuntimeError('unit exploded')

    monkeypatch.setattr(ops, '_fetch_unit', fail_unit)

    result = await execute_fetch(FetchRequest.from_axes('https://boom.test', view='metadata', page=2, page_size=10))

    assert result.status == 'error'
    assert result.results[0].view == 'metadata'
    assert result.results[0].page == 2
    assert result.results[0].page_size == 10
    assert result.results[0].error == 'unit exploded'


async def test_execute_fetch_failure_and_bundle_paths(monkeypatch, tmp_path):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class BlockedFetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(url=url, status_code=403, html=None, is_blocked=True, block_reason='blocked')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: BlockedFetcher())
    failed = await execute_fetch(FetchRequest.from_axes('https://blocked.test'))

    assert failed.status == 'error'
    assert failed.results[0].status == 'failed'
    assert failed.results[0].error == 'blocked'

    class BundleFetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(
                url=url,
                status_code=200,
                html=(
                    '<html><head><title>Bundle</title></head><body><main>'
                    '<h1>Bundle</h1><p>Ready.</p></main></body></html>'
                ),
                headers={'x-test': '1'},
                endpoints=['https://bundle.test/api'],
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: BundleFetcher())
    bundled = await execute_fetch(
        FetchRequest.from_axes(
            'https://bundle.test',
            view='bundle',
            include=['headers', 'endpoints', 'fingerprint'],
            output_dir=str(tmp_path),
        )
    )
    unit = bundled.results[0]

    assert bundled.status == 'ok'
    assert unit.content is not None
    assert '"artifacts"' in unit.content
    assert unit.artifacts['markdown.md'].endswith('markdown.md')
    assert unit.data is not None
    assert unit.data['artifacts'] == unit.artifacts


async def test_execute_content_failed_fetch_and_exception_paths(monkeypatch):
    import yosoi.core.fetcher as fetcher_module
    from yosoi.models.results import FetchResult as HtmlFetchResult

    class BlockedFetcher:
        async def fetch(self, url: str) -> HtmlFetchResult:
            return HtmlFetchResult(url=url, status_code=429, html=None, is_blocked=True, block_reason='rate limited')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: BlockedFetcher())
    blocked = await execute_content(ContentRequest.from_axes('https://blocked.test'))
    assert blocked.status == 'error'
    assert blocked.results[0].error == 'rate limited'

    class RaisingFetcher:
        async def fetch(self, _url: str) -> HtmlFetchResult:
            raise RuntimeError('boom')

        async def close(self) -> None:
            return None

    monkeypatch.setattr(fetcher_module, 'create_fetcher', lambda *_args, **_kwargs: RaisingFetcher())
    raised = await execute_content(ContentRequest.from_axes('https://boom.test'))
    assert raised.status == 'error'
    assert raised.results[0].error == 'boom'


async def test_run_crawl_requires_run_id_when_storing(monkeypatch, mocker):
    from yosoi.core.crawler import run as crawl_run

    @dataclass
    class Summary:
        pages: int

    monkeypatch.setattr(crawl_run, '_crawl_impl', mocker.AsyncMock(return_value=Summary(pages=1)))

    with pytest.raises(ValueError, match='run_id is required'):
        await run_crawl(CrawlRequest.from_axes('https://one.test', store_crawl=True))


async def test_run_scrape_alias_delegates(monkeypatch, mocker):
    execute = mocker.AsyncMock(return_value=ops.ScrapeResult(status='ok', results=[]))
    monkeypatch.setattr(ops, 'execute_scrape', execute)

    request = ScrapeRequest.from_axes('https://one.test', OpContract)
    assert await ops.run_scrape(request) == ops.ScrapeResult(status='ok', results=[])
    execute.assert_awaited_once_with(request)


async def test_run_crawl_compact_output_and_persistence(monkeypatch, mocker, tmp_path):
    from yosoi.core.crawler import run as crawl_run
    from yosoi.core.crawler.coordinator import CrawlJob, CrawlRunSummary
    from yosoi.core.crawler.coordinator import CrawlResult as PageResult
    from yosoi.storage.crawl_runs import CrawlRunsStore

    summary = CrawlRunSummary(
        results=[
            PageResult(
                job=CrawlJob(url='https://one.test', depth=0, source_url=None, batch_index=0),
                status='failed',
                html_chars=0,
                fetch_time=0.1,
                error='boom',
            )
        ],
        failures=1,
    )
    summary.attempted_urls = 1
    crawl_impl = mocker.AsyncMock(return_value=summary)
    monkeypatch.setattr(crawl_run, '_crawl_impl', crawl_impl)

    db_path = tmp_path / 'yosoi.sqlite3'
    mocker.patch('yosoi.storage.crawl_runs.CrawlRunsStore', return_value=CrawlRunsStore(database_url=db_path))

    request = CrawlRequest.from_axes(
        'https://one.test',
        compact=True,
        run_id='run-compact',
        store_crawl=True,
        stress=True,
    )
    result = await run_crawl(request)

    assert result.status == 'partial'
    assert result.summary['run_id'] == 'run-compact'
    assert result.summary['results'][0]['error'] == 'boom'
    async with CrawlRunsStore(database_url=db_path) as store:
        stored = await store.load_run('run-compact')
    assert stored is not None
    assert stored['status'] == 'partial'


async def test_execute_map_delegates_to_site_mapper(monkeypatch, mocker):
    from yosoi.core import site_map

    expected = MapResult(requested_url='https://example.com/', root_url='https://example.com/', root_host='example.com')
    discover = mocker.AsyncMock(return_value=expected)
    monkeypatch.setattr(site_map, 'discover_site_map', discover)

    request = MapRequest(url='example.com', max_urls=10)
    assert await execute_map(request) == expected
    assert await run_map(request) == expected
    assert discover.await_args.args[0].url == 'https://example.com/'


async def test_execute_scrape_reports_metadata_and_llm_blocked(monkeypatch, mocker):
    import yosoi.api as api_module
    from yosoi.utils.exceptions import LLMBlockedError

    async def scrape_impl(*args, **kwargs):
        metadata = kwargs['metadata_collect']
        metadata[('https://one.test', 'OpContract')] = {
            'selector_source': 'cache',
            'cache_decision': 'hit',
            'llm_used': False,
            'quality_status': 'partial',
            'quality_issues': ['record_count dropped from discovery baseline 4 to 2'],
            'expected_record_count': 4,
        }
        return [{'title': 'ok'}]

    monkeypatch.setattr(api_module, '_scrape_impl', scrape_impl)
    persist = mocker.patch('yosoi.operations._persist_scrape_unit', mocker.AsyncMock())

    result = await execute_scrape(ScrapeRequest.from_axes('https://one.test', OpContract))

    unit = result.results[0]
    assert result.status == 'partial'
    assert unit.selector_source == 'cache'
    assert unit.cache_decision == 'hit'
    assert unit.llm_used is False
    assert unit.quality_status == 'partial'
    assert unit.expected_record_count == 4
    assert unit.quality_issues == ['record_count dropped from discovery baseline 4 to 2']
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


async def test_execute_searches_rejects_empty_or_invalid_batches():
    with pytest.raises(ValueError, match='requests must not be empty'):
        await execute_searches([])
    with pytest.raises(ValueError, match='max_concurrency must be >= 1'):
        await execute_searches([SearchRequest(query='one')], max_concurrency=0)
    with pytest.raises(ValueError, match='max_concurrency must be >= 1'):
        await execute_searches([SearchRequest(query='one')], max_concurrency=True)


async def test_execute_searches_limits_fanout_preserves_order_and_isolates_failures(monkeypatch):
    active = 0
    peak_active = 0

    async def fake_execute(request):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0.01)
            if request.query == 'two':
                raise RuntimeError('backend unavailable')
            return ops.SearchResult(request=request)
        finally:
            active -= 1

    monkeypatch.setattr(ops, 'execute_search', fake_execute)
    requests = [SearchRequest(query=query) for query in ('one', 'two', 'three')]

    result = await execute_searches(requests, max_concurrency=2)

    assert peak_active == 2
    assert [unit.query for unit in result.results] == ['one', 'two', 'three']
    assert [unit.status for unit in result.results] == ['ok', 'failed', 'ok']
    assert result.results[1].error == 'backend unavailable'
    assert result.status == 'partial'


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
