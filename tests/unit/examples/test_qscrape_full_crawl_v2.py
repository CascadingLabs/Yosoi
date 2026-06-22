from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yosoi as ys
from yosoi.core.crawler.coordinator import CrawlJob, CrawlResult, CrawlRunSummary
from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.download import DownloadRecord

_HELPER_PATH = Path(__file__).resolve().parents[3] / 'examples' / 'qscrape.dev' / '_fingerprint_plan.py'
_SPEC = importlib.util.spec_from_file_location('qscrape_full_crawl_v2_fingerprint_plan', _HELPER_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPER
_SPEC.loader.exec_module(_HELPER)

crawl_contract_targets = _HELPER.crawl_contract_targets
plan_contract_targets = _HELPER.plan_contract_targets
scrape_planned_targets = _HELPER.scrape_planned_targets
write_target_inventory = _HELPER.write_target_inventory


class ProductContract(ys.Contract):
    """E-commerce product catalog records."""

    name: str = ys.Title(description='Product name')
    price: float | None = ys.Price(description='Product price')
    availability: str | None = ys.Field(description='Stock availability')


class NewsContract(ys.Contract):
    """News article archive records."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author')
    body_text: str = ys.BodyText(description='Article body text')


class TaxContract(ys.Contract):
    """Tax registry record with downloadable document."""

    parcel_id: str = ys.Field(description='Parcel tax identifier')
    document: DownloadRecord | None = ys.File(description='Downloadable tax PDF', allowed_types=('pdf',))


PRODUCT_HTML = """
<html><head><title>VaultMart Product Catalog</title></head><body>
<h1>Product Catalog</h1>
<section class="product-card"><h2>Iron Hammer</h2><span class="price">$12.00</span><span>In Stock</span></section>
<section class="product-card"><h2>Steel Pick</h2><span class="price">$18.00</span><span>Low Stock</span></section>
</body></html>
"""

PRODUCT_HTML_2 = PRODUCT_HTML.replace('Iron Hammer', 'Copper Hammer').replace('$12.00', '$9.00')

NEWS_HTML = """
<html><head><title>Mountainhome News Articles</title></head><body>
<h1>Article Archive</h1>
<article><h2>Guild Reports Record Output</h2><p class="author">Urist Reporter</p><p>Article body text goes here.</p></article>
</body></html>
"""

TAX_HTML = """
<html><head><title>Tax Registry</title></head><body>
<h1>Parcel Tax Registry</h1>
<table><tr><th>Parcel ID</th><th>Tax Status</th><th>Downloadable PDF</th></tr><tr><td>APN-1</td><td>Paid</td><td><a href="/tax.pdf">PDF</a></td></tr></table>
</body></html>
"""


def _result(url: str, html: str, *, depth: int = 1) -> CrawlResult:
    return CrawlResult(
        job=CrawlJob(url=url, depth=depth, source_url='https://example.test/', batch_index=0),
        status='succeeded',
        html=html,
        html_chars=len(html),
        content_type='text/html',
        fingerprint=PageFingerprint.of(html),
    )


def test_plan_contract_targets_uses_fingerprint_families_not_route_or_schema_terms() -> None:
    summary = CrawlRunSummary(
        results=[
            _result('https://example.test/shop/catalog', PRODUCT_HTML),
            _result('https://example.test/shop/catalog?page=2', PRODUCT_HTML_2),
            _result('https://example.test/news/articles', NEWS_HTML),
        ]
    )

    plan = plan_contract_targets(summary, (ProductContract, NewsContract), max_targets_per_contract=5)

    product_urls = plan.neutral_candidate_urls(ProductContract)
    news_urls = plan.neutral_candidate_urls(NewsContract)
    assert product_urls == news_urls
    assert 'https://example.test/shop/catalog' in product_urls
    assert 'https://example.test/shop/catalog?page=2' in product_urls
    assert 'https://example.test/news/articles' in product_urls
    row = plan.as_rows()[0]
    forbidden = {'matched' + '_contract_terms', 'contract' + '_relevance_score', 'eligible', 'contract'}
    assert forbidden.isdisjoint(row)
    assert row['fanout_contract'] in {'NewsContract', 'ProductContract'}
    assert row['neutral_candidate'] is True
    assert row['evidence_scope'] == 'neutral_fingerprint_family'
    assert row['contract_specific'] is False
    assert row['verification_status'] == 'not_verified'


def test_plan_contract_targets_diversifies_across_fingerprint_families() -> None:
    summary = CrawlRunSummary(
        results=[
            _result('https://example.test/shop/catalog', PRODUCT_HTML),
            _result('https://example.test/shop/catalog?page=2', PRODUCT_HTML_2),
            _result('https://example.test/news/articles', NEWS_HTML),
        ]
    )

    plan = plan_contract_targets(summary, (ProductContract,), max_targets_per_contract=2)
    targets = plan.neutral_candidate_targets(ProductContract)

    assert len({target.family_url for target in targets}) == 2


def test_plan_contract_targets_with_exemplars_classifies_instead_of_fanning_out() -> None:
    product_examples = [f'https://example.test/shop/product/{idx}' for idx in range(5)]
    news_examples = [f'https://example.test/news/article/{idx}' for idx in range(5)]
    results = [
        *[
            _result(url, PRODUCT_HTML.replace('Iron Hammer', f'Iron Hammer {idx}'))
            for idx, url in enumerate(product_examples)
        ],
        *[
            _result(url, NEWS_HTML.replace('Guild Reports', f'Guild Reports {idx}'))
            for idx, url in enumerate(news_examples)
        ],
        _result('https://example.test/shop/product/target', PRODUCT_HTML.replace('Steel Pick', 'Silver Pick')),
        _result('https://example.test/news/article/target', NEWS_HTML.replace('Archive', 'Dispatch')),
    ]
    summary = CrawlRunSummary(results=results)

    plan = plan_contract_targets(
        summary,
        (ProductContract, NewsContract),
        contract_exemplars={ProductContract: product_examples, NewsContract: news_examples},
        min_exemplar_score=0.50,
        min_exemplar_margin=0.0,
        max_targets_per_contract=5,
    )

    assert plan.as_output()['plan_kind'] == 'validated_fingerprint_exemplar_ranking'
    assert plan.as_output()['contract_specific_ranking'] is True
    assert plan.neutral_candidate_urls(ProductContract) == ['https://example.test/shop/product/target']
    assert plan.neutral_candidate_urls(NewsContract) == ['https://example.test/news/article/target']
    row = plan.as_rows()[0]
    assert row['evidence_scope'] == 'validated_fingerprint_exemplars'
    assert row['contract_specific'] is True
    assert row['exemplar_score'] >= 0.50
    assert row['best_exemplar_url'] in {*product_examples, *news_examples}


async def test_scrape_planned_targets_uses_explicit_contracts_and_download_policy(mocker: Any) -> None:
    summary = CrawlRunSummary(results=[_result('https://example.test/taxes', TAX_HTML)])
    plan = plan_contract_targets(summary, (TaxContract,), max_targets_per_contract=1)
    scrape = mocker.patch('yosoi.api.scrape', new=mocker.AsyncMock(return_value=['ok']))

    result = await scrape_planned_targets(plan, policy=ys.Policy(), top_per_contract=1, scrape_max_concurrency=2)

    assert result == {'TaxContract': ['ok']}
    scrape.assert_awaited_once()
    _, contract = scrape.await_args.args[:2]
    assert contract is TaxContract
    assert scrape.await_args.kwargs['allow_downloads'] is True
    assert scrape.await_args.kwargs['allowed_download_types'] == ('pdf',)
    assert scrape.await_args.kwargs['max_concurrency'] == 2


def test_write_target_inventory_redacts_query_strings_and_writes_all_pairs_scores(tmp_path: Path) -> None:
    summary = CrawlRunSummary(
        results=[
            _result('https://example.test/shop?token=secret', PRODUCT_HTML),
            _result('https://example.test/shop?page=2', PRODUCT_HTML_2),
            _result('https://example.test/news', NEWS_HTML),
        ]
    )
    plan = plan_contract_targets(summary, (ProductContract,), max_targets_per_contract=1)

    paths = write_target_inventory(summary, plan, tmp_path)

    assert 'token=secret' not in Path(paths['frontier_urls']).read_text()
    payload = json.loads(Path(paths['fingerprint_target_plan']).read_text())
    assert payload['plan_kind'] == 'neutral_fingerprint_candidate_fanout'
    assert payload['contract_specific_ranking'] is False
    assert payload['verified'] is False
    assert payload['rows'][0]['neutral_candidate'] is True

    scores = json.loads(Path(paths['fingerprint_scores']).read_text())
    assert scores['artifact_kind'] == 'neutral_fingerprint_all_pairs'
    assert scores['pairing'] == 'unordered_including_self'
    assert len(scores['rows']) == 6  # n=3 -> n*(n+1)/2
    assert scores['rows'][0]['left_url'] == scores['rows'][0]['right_url']
    assert scores['rows'][0]['weighted_jaccard_score'] == 1.0


async def test_crawl_contract_targets_hides_workflow_plumbing(mocker: Any, tmp_path: Path) -> None:
    summary = CrawlRunSummary(results=[_result('https://example.test/taxes', TAX_HTML)])
    mocker.patch('yosoi.core.crawler.run.crawl', new=mocker.AsyncMock(return_value=summary))
    scrape = mocker.patch('yosoi.api.scrape', new=mocker.AsyncMock(return_value=['ok']))

    result = await crawl_contract_targets(
        'https://example.test/',
        (TaxContract,),
        crawl_policy=ys.Policy(),
        scrape_policy=ys.Policy(),
        output_dir=tmp_path,
        scrape_top_per_contract=1,
    )

    assert result.inventory_paths
    assert result.scrape_results == {'TaxContract': ['ok']}
    scrape.assert_awaited_once()
