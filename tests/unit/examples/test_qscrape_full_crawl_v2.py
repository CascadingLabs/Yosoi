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

_EXAMPLE_DIR = Path(__file__).resolve().parents[3] / 'examples' / 'qscrape.dev'
_HELPER_PATH = _EXAMPLE_DIR / '_fingerprint_plan.py'
_SPEC = importlib.util.spec_from_file_location('qscrape_full_crawl_v2_fingerprint_plan', _HELPER_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPER
_SPEC.loader.exec_module(_HELPER)

_ALT_SPEC = importlib.util.spec_from_file_location('qscrape_full_crawl_v2_alt', _EXAMPLE_DIR / 'full_crawl_v2_alt.py')
assert _ALT_SPEC is not None
assert _ALT_SPEC.loader is not None
_ALT = importlib.util.module_from_spec(_ALT_SPEC)
sys.path.insert(0, str(_EXAMPLE_DIR))
sys.modules[_ALT_SPEC.name] = _ALT
_ALT_SPEC.loader.exec_module(_ALT)

_V3_SPEC = importlib.util.spec_from_file_location('qscrape_full_crawl_v3', _EXAMPLE_DIR / 'full_crawl_v3.py')
assert _V3_SPEC is not None
assert _V3_SPEC.loader is not None
_V3 = importlib.util.module_from_spec(_V3_SPEC)
sys.modules[_V3_SPEC.name] = _V3
_V3_SPEC.loader.exec_module(_V3)

_V3_DOMAIN_SPEC = importlib.util.spec_from_file_location(
    'qscrape_full_crawl_v3_domain_axis', _EXAMPLE_DIR / 'full_crawl_v3_domain_axis.py'
)
assert _V3_DOMAIN_SPEC is not None
assert _V3_DOMAIN_SPEC.loader is not None
_V3_DOMAIN = importlib.util.module_from_spec(_V3_DOMAIN_SPEC)
sys.modules[_V3_DOMAIN_SPEC.name] = _V3_DOMAIN
_V3_DOMAIN_SPEC.loader.exec_module(_V3_DOMAIN)

_V4_DOMAIN_SPEC = importlib.util.spec_from_file_location(
    'qscrape_full_crawl_v4_domain_axis_validation', _EXAMPLE_DIR / 'full_crawl_v4_domain_axis_validation.py'
)
assert _V4_DOMAIN_SPEC is not None
assert _V4_DOMAIN_SPEC.loader is not None
_V4_DOMAIN = importlib.util.module_from_spec(_V4_DOMAIN_SPEC)
sys.modules[_V4_DOMAIN_SPEC.name] = _V4_DOMAIN
_V4_DOMAIN_SPEC.loader.exec_module(_V4_DOMAIN)

_V5_SPEC = importlib.util.spec_from_file_location('qscrape_full_crawl_v5', _EXAMPLE_DIR / 'full_crawl_v5.py')
assert _V5_SPEC is not None
assert _V5_SPEC.loader is not None
_V5 = importlib.util.module_from_spec(_V5_SPEC)
sys.modules[_V5_SPEC.name] = _V5
_V5_SPEC.loader.exec_module(_V5)

_V6_SPEC = importlib.util.spec_from_file_location(
    'qscrape_full_crawl_v6_content', _EXAMPLE_DIR / 'full_crawl_v6_content.py'
)
assert _V6_SPEC is not None
assert _V6_SPEC.loader is not None
_V6 = importlib.util.module_from_spec(_V6_SPEC)
sys.modules[_V6_SPEC.name] = _V6
_V6_SPEC.loader.exec_module(_V6)

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

PRODUCT_LISTING_HTML = """
<html><head><title>Catalog Listing</title></head><body>
<h1>Catalog</h1>
<nav><a href="/shop/product/1">Iron Hammer</a><a href="/shop/product/2">Steel Pick</a></nav>
<section class="grid"><article>Iron Hammer</article><article>Steel Pick</article><article>Copper Anvil</article></section>
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


def test_plan_contract_targets_with_contrastives_rejects_near_misses() -> None:
    product_examples = [f'https://example.test/shop/product/{idx}' for idx in range(5)]
    listing_url = 'https://example.test/shop/catalog'
    target_url = 'https://example.test/shop/product/target'
    results = [
        *[
            _result(url, PRODUCT_HTML.replace('Iron Hammer', f'Iron Hammer {idx}'))
            for idx, url in enumerate(product_examples)
        ],
        _result(listing_url, PRODUCT_LISTING_HTML),
        _result(target_url, PRODUCT_HTML.replace('Steel Pick', 'Silver Pick')),
        _result(
            'https://example.test/shop/catalog?page=2', PRODUCT_LISTING_HTML.replace('Copper Anvil', 'Bronze Anvil')
        ),
    ]
    summary = CrawlRunSummary(results=results)

    plan = plan_contract_targets(
        summary,
        (ProductContract,),
        contract_exemplars={ProductContract: product_examples},
        contrastive_exemplars=(listing_url,),
        contrastive_weight=1.0,
        min_exemplar_score=0.50,
        min_exemplar_margin=0.0,
        max_targets_per_contract=None,
    )

    urls = plan.neutral_candidate_urls(ProductContract)
    assert target_url in urls
    assert 'https://example.test/shop/catalog?page=2' not in urls
    target_row = next(row for row in plan.as_rows() if row['url'] == target_url)
    assert target_row['contrastive_score'] is not None
    assert target_row['contrastive_weight'] == 1.0


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


def test_full_crawl_v2_alt_binary_oracle_and_summary() -> None:
    urls = [
        'https://qscrape.dev/l3/news/article/MHH-009/',
        'https://qscrape.dev/l1/news/article?postData=abc',
        'https://qscrape.dev/l1/news/articles/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-001/',
    ]
    predictions = {
        'https://qscrape.dev/l3/news/article/MHH-009/': 'NewsArticle',
        'https://qscrape.dev/l1/news/articles/': 'NewsArticle',
    }

    assert _ALT._news_binary_oracle('https://qscrape.dev/l3/news/article/MHH-009/') == 'NewsArticle'
    assert _ALT._news_binary_oracle('https://qscrape.dev/l1/news/article?postData=abc') == 'NewsArticle'
    assert _ALT._news_binary_oracle('https://qscrape.dev/l1/news/articles/') == 'NoContract'

    summary = _ALT._binary_summary(urls, predictions=predictions, training_urls=set())

    assert summary['true_positive'] == 1
    assert summary['false_positive'] == 1
    assert summary['false_negative'] == 1
    assert summary['true_negative'] == 1
    assert summary['precision'] == 0.5
    assert summary['recall'] == 0.5


def test_full_crawl_v3_binary_summary_and_scrape_gate(tmp_path: Path, monkeypatch: Any) -> None:
    urls = [
        'https://qscrape.dev/l3/news/article/MHH-009/',
        'https://qscrape.dev/l1/news/article?postData=abc',
        'https://qscrape.dev/l1/news/article/',
    ]
    summary = _V3._binary_summary(
        urls,
        predicted_urls={'https://qscrape.dev/l3/news/article/MHH-009/', 'https://qscrape.dev/l1/news/article/'},
        training_urls=set(),
    )
    assert summary['true_positive'] == 1
    assert summary['false_positive'] == 1
    assert summary['false_negative'] == 1

    monkeypatch.setattr(_V3, 'OUT', tmp_path)
    plan = _HELPER.FingerprintTargetPlan(
        {
            'NewsArticle': [
                _HELPER.FingerprintTarget(
                    contract_name='NewsArticle',
                    contract=_V3.NewsArticle,
                    url='https://qscrape.dev/l3/news/article/MHH-009/',
                    family_url='https://qscrape.dev/l3/news/article/MHH-001/',
                    score=0.9,
                    weighted_jaccard_score=0.9,
                    family_cohesion_score=1.0,
                    same_shape=True,
                    neutral_candidate=True,
                    family_size=5,
                    depth=1,
                    html_chars=100,
                    outlinks=1,
                )
            ]
        }
    )
    result = _HELPER.CrawlTargetWorkflowResult(
        summary=CrawlRunSummary(results=[]),
        inventory=_HELPER.CrawlInventory(items=()),
        plan=plan,
        scrape_results={
            'NewsArticle': {
                'https://qscrape.dev/l3/news/article/MHH-009/': {
                    'phase': 'replay',
                    'records': [{'headline': 'ok'}],
                    'error': None,
                }
            }
        },
    )
    payload_path = _V3._write_scrape_gate_eval(result)
    payload = json.loads(payload_path.read_text())
    assert payload['scrape_passed_urls'] == 1
    assert payload['scrape_failed_urls'] == 0
    assert payload['rows'][0]['phase'] == 'replay'


def test_full_crawl_v3_domain_axis_oracles_and_bucketed_metrics() -> None:
    urls = [
        'https://qscrape.dev/l3/news/article/MHH-009/',
        'https://qscrape.dev/l1/news/about/',
        'https://www.cnn.com/2026/06/22/tech/example/index.html',
        'https://www.vlr.gg/123456/team-a-vs-team-b',
        'https://www.vlr.gg/rankings',
    ]
    predictions = {
        'https://qscrape.dev/l3/news/article/MHH-009/': 'NewsArticle',
        'https://qscrape.dev/l1/news/about/': 'NewsArticle',
        'https://www.cnn.com/2026/06/22/tech/example/index.html': 'NewsArticle',
        'https://www.vlr.gg/rankings': 'ScoreContract',
    }

    assert _V3_DOMAIN._oracle_label('https://www.cnn.com/2026/06/22/tech/example/index.html') == 'NewsArticle'
    assert _V3_DOMAIN._oracle_label('https://finance.yahoo.com/news/example-story-123.html') == 'NewsArticle'
    assert _V3_DOMAIN._oracle_label('https://www.vlr.gg/123456/team-a-vs-team-b') == 'ScoreContract'
    assert (
        _V3_DOMAIN._domain_axis(
            'https://qscrape.dev/l3/news/article/MHH-009/',
            actual_label='NewsArticle',
            exemplars=_V3_DOMAIN.QSCRAPE_EXEMPLARS,
        )
        == 'sub_path'
    )
    assert (
        _V3_DOMAIN._domain_axis(
            'https://qscrape.dev/l1/news/about/', actual_label='NoContract', exemplars=_V3_DOMAIN.QSCRAPE_EXEMPLARS
        )
        == 'same_domain'
    )
    assert (
        _V3_DOMAIN._domain_axis(
            'https://www.cnn.com/2026/06/22/tech/example/index.html',
            actual_label='NewsArticle',
            exemplars=_V3_DOMAIN.QSCRAPE_EXEMPLARS,
        )
        == 'cross_domain'
    )

    binary = _V3_DOMAIN._classification_summary(
        urls,
        predictions=predictions,
        training_urls=set(),
        mode='binary',
    )
    multi = _V3_DOMAIN._classification_summary(
        urls,
        predictions=predictions,
        training_urls=set(),
        mode='multi',
    )

    assert binary['accuracy'] == 0.8
    assert binary['precision'] == 0.6667
    assert binary['recall'] == 1.0
    assert binary['f1'] == 0.8
    assert binary['by_domain_axis']['cross_domain']['total_eval_urls'] == 3
    assert multi['accuracy'] == 0.4
    assert multi['precision'] == 0.5
    assert multi['recall'] == 0.6667
    assert multi['f1'] == 0.5714
    assert multi['by_domain_axis']['same_domain']['false_positive'] == 1


def test_full_crawl_v6_reuses_v5_contracts_and_filters_successful_crawl_urls() -> None:
    summary = CrawlRunSummary(
        results=[
            _result('https://qscrape.dev/a', NEWS_HTML),
            CrawlResult(
                job=CrawlJob(url='https://qscrape.dev/fail', depth=1, source_url=None, batch_index=1), status='failed'
            ),
        ]
    )

    assert _V6.SEED == _V5.SEED
    assert [contract.__name__ for contract in _V6.CONTRACTS] == [contract.__name__ for contract in _V5.CONTRACTS]
    assert _V6._crawl_urls(summary) == ['https://qscrape.dev/a']


def test_full_crawl_v5_is_cold_start_single_seed_four_contracts() -> None:
    assert _V5.SEED == 'https://qscrape.dev/'
    assert [contract.__name__ for contract in _V5.CONTRACTS] == [
        'NewsArticle',
        'TaxInfo',
        'ScoreContract',
        'ProductContract',
    ]
    assert _V5.TOP >= 1
    assert _V5.SCRAPE_TOP >= 0


def test_full_crawl_v4_validation_gate_reduces_false_positives() -> None:
    urls = [
        'https://qscrape.dev/l3/news/article/MHH-009/',
        'https://qscrape.dev/l1/news/about/',
        'https://www.cnn.com/2026/06/22/tech/example/index.html',
    ]
    predictions = {
        'https://qscrape.dev/l3/news/article/MHH-009/': 'NewsArticle',
        'https://qscrape.dev/l1/news/about/': 'NewsArticle',
        'https://www.cnn.com/2026/06/22/tech/example/index.html': 'NewsArticle',
    }
    validation = {
        'https://qscrape.dev/l3/news/article/MHH-009/': {
            'NewsArticle': {'passed': True, 'record_count': 1, 'reason': 'passed'}
        },
        'https://qscrape.dev/l1/news/about/': {
            'NewsArticle': {'passed': False, 'record_count': 0, 'reason': 'no_records'}
        },
        'https://www.cnn.com/2026/06/22/tech/example/index.html': {
            'NewsArticle': {'passed': False, 'record_count': 1, 'reason': 'field_validation_failed'}
        },
    }

    valid_article = {
        'headline': 'Oil prices rise',
        'body_text': 'A concise article body.',
        'author': 'Jane Reporter',
        'date': '2026-06-22',
        'category': 'Energy',
    }
    invalid_article = {'headline': 'Only a headline'}
    valid_verdict = _V4_DOMAIN._record_validation_verdict(valid_article, _V4_DOMAIN.NewsArticle)
    invalid_verdict = _V4_DOMAIN._record_validation_verdict(invalid_article, _V4_DOMAIN.NewsArticle)
    gated = _V4_DOMAIN._apply_validation_gate(predictions, validation)
    reduction = _V4_DOMAIN._validation_reduction_summary(
        urls,
        before=predictions,
        after=gated,
        training_urls=set(),
    )

    assert valid_verdict['passed'] is True
    assert invalid_verdict['passed'] is False
    assert set(invalid_verdict['missing_required_fields']) == {'body_text'}
    assert gated == {'https://qscrape.dev/l3/news/article/MHH-009/': 'NewsArticle'}
    assert reduction['before_false_positive'] == 1
    assert reduction['after_false_positive'] == 0
    assert reduction['false_positive_reduction'] == 1


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
