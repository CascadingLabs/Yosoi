"""Tests for canonical operation request/result models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.operations import (
    ContractRef,
    CrawlRequest,
    ScrapeRequest,
    _selector_level,
    execute_crawl,
    execute_scrape,
    normalize_scrape_result,
    run_crawl,
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
        ContractRef.from_input(object())  # type: ignore[arg-type]


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


def test_selector_level_accepts_all_name_and_value():
    from yosoi.models.selectors import SelectorLevel

    assert _selector_level('all') == max(SelectorLevel)
    assert _selector_level('css') == SelectorLevel.CSS
    assert _selector_level('XPATH') == SelectorLevel.XPATH
    with pytest.raises(ValueError, match='not a valid SelectorLevel'):
        _selector_level('bogus')


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
