"""Full qscrape.dev crawl v2: frontier → neutral candidates → optional verified scrape.

Run:
    uv run python examples/qscrape.dev/full_crawl_v2.py

Requires Docker VoidCrawl CDP endpoints. Override ``YOSOI_CHROME_WS_URLS`` if
your Docker ports differ. The default plan uses five explicit clean fingerprint
exemplars per contract to rank crawled pages. A row is still not extracted-data
success until optional verified scrape succeeds. Verified scraping is opt-in with
``YOSOI_FULL_CRAWL_V2_SCRAPE_TOP_PER_CONTRACT`` so the default run does not need
LLM/API credentials.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from _fingerprint_plan import crawl_contract_targets, plan_contract_targets

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.models.download import DownloadRecord

SEED = 'https://qscrape.dev/'
DEFAULT_OUT = Path(chr(46) + 'yosoi') / 'full_crawl_v2'
OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V2_OUTPUT_DIR') or DEFAULT_OUT)
TOP = int(os.getenv('YOSOI_FULL_CRAWL_V2_TOP_PER_CONTRACT', '12'))
SCRAPE_TOP = int(os.getenv('YOSOI_FULL_CRAWL_V2_SCRAPE_TOP_PER_CONTRACT', '0'))
CHROME_WS_URLS = tuple(
    url.strip()
    for url in os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223').split(',')
    if url.strip()
)
MIN_EXEMPLAR_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V2_MIN_EXEMPLAR_SCORE', '0.70'))
MIN_EXEMPLAR_MARGIN = float(os.getenv('YOSOI_FULL_CRAWL_V2_MIN_EXEMPLAR_MARGIN', '0.06'))
EXEMPLAR_SUPPORT_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V2_EXEMPLAR_SUPPORT_SCORE', '0.70'))


class NewsArticle(ys.Contract):
    """News article or article-listing record."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author or byline')
    date: str | None = ys.Datetime(description='Article publication date')
    category: str | None = ys.Field(description='Article category or section')
    body_text: str = ys.BodyText(description='Article body, summary, or excerpt')


class TaxInfo(ys.Contract):
    """Tax, deed, parcel, or registry record."""

    parcel_id: str | None = ys.Field(description='Parcel, APN, deed, or registry identifier')
    owner_name: str | None = ys.Author(description='Owner, grantee, grantor, or filer name')
    address: str | None = ys.Field(description='Property or registry address')
    tax_amount: float | None = ys.Price(description='Tax amount, fee amount, assessed value, or balance')
    status: str | None = ys.Field(description='Payment, filing, deed, or registry status')
    document: DownloadRecord | None = ys.File(
        description='Downloadable tax, deed, parcel, receipt, CSV, JSON, or PDF document',
        allowed_types=('pdf', 'csv', 'json'),
        max_bytes=5_000_000,
    )


class ScoreContract(ys.Contract):
    """ScoreTap match, game, or standings row."""

    team_a: str = ys.Field(description='First team, player, or competitor name')
    team_b: str | None = ys.Field(description='Second team, player, or competitor name')
    score: str = ys.Field(description='Displayed score, result, or standing value')
    status: str | None = ys.Field(description='Match state, round, time, or final status')


class ProductContract(ys.Contract):
    """E-commerce product card or product detail."""

    name: str = ys.Title(description='Product name')
    category: str | None = ys.Field(description='Product category label')
    price: float | None = ys.Price(description='Product price as a number')
    rating: float | None = ys.Rating(as_float=True, description='Visible product rating or score')
    reviews_count: int | None = ys.Field(description='Number of reviews or ratings')
    availability: str | None = ys.Field(description='Stock or availability status')


CONTRACTS = (NewsArticle, TaxInfo, ScoreContract, ProductContract)

QSCRAPE_EXEMPLARS: dict[type[Contract] | str, tuple[str, ...]] = {
    NewsArticle: (
        'https://qscrape.dev/l3/news/article/MHH-001/',
        'https://qscrape.dev/l3/news/article/MHH-002/',
        'https://qscrape.dev/l3/news/article/MHH-003/',
        'https://qscrape.dev/l3/news/article/MHH-004/',
        'https://qscrape.dev/l3/news/article/MHH-005/',
    ),
    TaxInfo: (
        'https://qscrape.dev/l3/taxes/viewer/26-010033/',
        'https://qscrape.dev/l3/taxes/viewer/26-010241/',
        'https://qscrape.dev/l3/taxes/viewer/26-010502/',
        'https://qscrape.dev/l3/taxes/viewer/26-010618/',
        'https://qscrape.dev/l3/taxes/viewer/26-010744/',
    ),
    ScoreContract: (
        'https://qscrape.dev/l1/scoretap/match?id=match-001',
        'https://qscrape.dev/l1/scoretap/match?id=match-002',
        'https://qscrape.dev/l1/scoretap/match?id=match-003',
        'https://qscrape.dev/l1/scoretap/event?id=iem-katowice-2026',
        'https://qscrape.dev/l1/scoretap/team?id=vitality',
    ),
    ProductContract: (
        'https://qscrape.dev/l3/eshop/product/VM-FDB-001/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-002/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-003/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-004/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-005/',
    ),
}


def _qscrape_oracle_label(url: str) -> str:
    """Broad qscrape.dev section oracle; not used by planner scoring."""
    path = urlparse(url).path.lower()
    if '/news/' in path:
        return 'NewsArticle'
    if '/taxes/' in path:
        return 'TaxInfo'
    if '/scoretap/' in path:
        return 'ScoreContract'
    if '/eshop/' in path:
        return 'ProductContract'
    return 'Unknown'


def _qscrape_target_oracle_label(url: str) -> str:
    """Strict qscrape.dev target-vs-contrastive oracle; not used by planner scoring."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if path.startswith('/l3/news/article/') or path.startswith('/l1/news/article'):
        return 'NewsArticle'
    if '/eshop/product/' in path and not path.rstrip('/').endswith('/product'):
        return 'ProductContract'
    if path.startswith('/l3/taxes/viewer/'):
        return 'TaxInfo'
    if path.startswith('/l1/scoretap/match') and 'id' in query:
        return 'ScoreContract'
    if path.startswith('/l1/scoretap/team') and 'id' in query:
        return 'ScoreContract'
    if path.startswith('/l1/scoretap/event') and 'id' in query:
        return 'ScoreContract'
    return 'NoContract'


def _write_qscrape_accuracy_eval(result: Any) -> Path:
    rows = result.plan.as_rows()
    payload = {
        'artifact_kind': 'qscrape_url_oracle_accuracy_eval',
        'oracle_scope': 'evaluation_only_not_planner_input',
        **_qscrape_accuracy_summary(
            rows,
            known_urls=result.inventory.urls,
            exemplar_urls={url for urls in QSCRAPE_EXEMPLARS.values() for url in urls},
        ),
    }
    path = OUT / 'qscrape_accuracy_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def _write_qscrape_exemplar_level_eval(result: Any) -> Path:
    levels: list[dict[str, Any]] = []
    for exemplar_count in (5, 4, 3, 2, 1, 0):
        exemplar_subset = _exemplars_at_level(exemplar_count)
        plan = plan_contract_targets(
            result.inventory,
            CONTRACTS,
            max_targets_per_contract=TOP,
            contract_exemplars=exemplar_subset or None,
            min_exemplar_score=MIN_EXEMPLAR_SCORE,
            min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
            exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
        )
        exemplar_urls = {url for urls in exemplar_subset.values() for url in urls}
        levels.append(
            {
                'exemplars_per_contract': exemplar_count,
                'plan_kind': plan.as_output()['plan_kind'],
                'contract_specific_ranking': plan.as_output()['contract_specific_ranking'],
                **_qscrape_accuracy_summary(
                    plan.as_rows(), known_urls=result.inventory.urls, exemplar_urls=exemplar_urls
                ),
            }
        )

    payload = {
        'artifact_kind': 'qscrape_exemplar_level_comparison',
        'oracle_scope': 'evaluation_only_not_planner_input',
        'levels': levels,
    }
    path = OUT / 'qscrape_exemplar_level_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def _write_qscrape_frontier_generalization_eval(result: Any) -> Path:
    levels: list[dict[str, Any]] = []
    for exemplar_count in (5, 4, 3, 2, 1, 0):
        exemplar_subset = _exemplars_at_level(exemplar_count)
        exemplar_urls = {url for urls in exemplar_subset.values() for url in urls}
        if exemplar_subset:
            plan = plan_contract_targets(
                result.inventory,
                CONTRACTS,
                max_targets_per_contract=None,
                contract_exemplars=exemplar_subset,
                min_exemplar_score=MIN_EXEMPLAR_SCORE,
                min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
                exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
            )
            predictions = {row['url']: row['fanout_contract'] for row in plan.as_rows()}
            classifier_available = True
        else:
            predictions = {}
            classifier_available = False
        levels.append(
            {
                'exemplars_per_contract': exemplar_count,
                'classifier_available': classifier_available,
                **_qscrape_frontier_generalization_summary(
                    result.inventory.urls,
                    predictions=predictions,
                    exemplar_urls=exemplar_urls,
                ),
            }
        )

    payload = {
        'artifact_kind': 'qscrape_frontier_generalization_eval',
        'oracle_scope': 'evaluation_only_not_planner_input',
        'positive_oracle': 'strict_record_like_targets',
        'contrastive_label': 'NoContract',
        'levels': levels,
    }
    path = OUT / 'qscrape_frontier_generalization_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def _exemplars_at_level(count: int) -> dict[type[Contract] | str, tuple[str, ...]]:
    if count <= 0:
        return {}
    return {contract: urls[:count] for contract, urls in QSCRAPE_EXEMPLARS.items()}


def _qscrape_accuracy_summary(
    rows: list[dict[str, Any]], *, known_urls: list[str], exemplar_urls: set[str]
) -> dict[str, Any]:
    by_contract: dict[str, Counter[str]] = defaultdict(Counter)
    wrong_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    correct = 0
    selected_known_urls: set[str] = set()
    for row in rows:
        predicted = str(row['fanout_contract'])
        url = str(row['url'])
        actual = _qscrape_oracle_label(url)
        is_correct = predicted == actual
        correct += int(is_correct)
        if actual != 'Unknown':
            selected_known_urls.add(url)
        by_contract[predicted]['total'] += 1
        by_contract[predicted]['correct'] += int(is_correct)
        by_contract[predicted]['wrong'] += int(not is_correct)
        by_contract[predicted][actual] += 1
        if not is_correct and len(wrong_examples[predicted]) < 10:
            wrong_examples[predicted].append({'actual': actual, 'url': url})

    total = len(rows)
    known_target_urls = {url for url in known_urls if _qscrape_oracle_label(url) != 'Unknown'} - exemplar_urls
    return {
        'total_rows': total,
        'correct_rows': correct,
        'wrong_rows': total - correct,
        'accuracy': round(correct / total, 4) if total else None,
        'selected_known_unique_urls': len(selected_known_urls),
        'known_non_exemplar_urls': len(known_target_urls),
        'known_url_coverage': round(len(selected_known_urls & known_target_urls) / len(known_target_urls), 4)
        if known_target_urls
        else None,
        'by_contract': {
            contract: {
                'total': counts['total'],
                'correct': counts['correct'],
                'wrong': counts['wrong'],
                'accuracy': round(counts['correct'] / counts['total'], 4) if counts['total'] else None,
                'actual_breakdown': {
                    key: value for key, value in counts.items() if key not in {'total', 'correct', 'wrong'}
                },
                'wrong_examples': wrong_examples.get(contract, []),
            }
            for contract, counts in sorted(by_contract.items())
        },
    }


def _qscrape_frontier_generalization_summary(
    urls: list[str], *, predictions: dict[str, str], exemplar_urls: set[str]
) -> dict[str, Any]:
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    false_positive_examples: list[dict[str, Any]] = []
    false_negative_examples: list[dict[str, Any]] = []
    wrong_contract_examples: list[dict[str, Any]] = []
    total = correct = target_total = contrastive_total = 0
    true_positive = false_positive = false_negative = true_negative = 0

    for url in urls:
        if url in exemplar_urls:
            continue
        actual = _qscrape_target_oracle_label(url)
        predicted = predictions.get(url, 'NoContract')
        is_correct = predicted == actual
        total += 1
        correct += int(is_correct)
        confusion[actual][predicted] += 1
        if actual == 'NoContract':
            contrastive_total += 1
            if predicted == 'NoContract':
                true_negative += 1
            else:
                false_positive += 1
                if len(false_positive_examples) < 10:
                    false_positive_examples.append({'predicted': predicted, 'url': url})
        else:
            target_total += 1
            if predicted == actual:
                true_positive += 1
            elif predicted == 'NoContract':
                false_negative += 1
                if len(false_negative_examples) < 10:
                    false_negative_examples.append({'actual': actual, 'url': url})
            else:
                false_positive += 1
                false_negative += 1
                if len(wrong_contract_examples) < 10:
                    wrong_contract_examples.append({'actual': actual, 'predicted': predicted, 'url': url})

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {
        'total_eval_urls': total,
        'target_urls': target_total,
        'contrastive_urls': contrastive_total,
        'correct': correct,
        'accuracy': round(correct / total, 4) if total else None,
        'target_precision': round(precision, 4) if precision is not None else None,
        'target_recall': round(recall, 4) if recall is not None else None,
        'target_f1': round(f1, 4) if f1 is not None else None,
        'true_positive': true_positive,
        'false_positive': false_positive,
        'false_negative': false_negative,
        'true_negative': true_negative,
        'confusion': {actual: dict(predicted) for actual, predicted in sorted(confusion.items())},
        'false_positive_examples': false_positive_examples,
        'false_negative_examples': false_negative_examples,
        'wrong_contract_examples': wrong_contract_examples,
    }


async def main() -> None:
    docker_page = ys.PagePolicy(fetcher_type='auto', chrome_ws_urls=CHROME_WS_URLS)
    crawl_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            crawl=ys.CrawlPolicy(
                budget=ys.CrawlBudget(max_pages=1_000, max_depth=4, max_attempts=1_200),
                scheduler=ys.SchedulerPolicy(
                    max_workers=16,
                    per_host_concurrency=16,
                    politeness_delay=0,
                    fetch_timeout_seconds=5,
                    max_fetch_retries=1,
                ),
                safety=ys.CrawlSafety(
                    respect_robots=False,
                    allow_redirects=True,
                    allowed_hosts=('qscrape.dev',),
                    blocked_path_prefixes=('/cdn-cgi/',),
                ),
                escalation=ys.EscalationPolicy(allow_model_discovery=False, max_llm_calls=0),
                scrape_contracts=False,
                fetcher_type='auto',
            ),
            fingerprint=ys.FingerprintPolicy(),
            page=docker_page,
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    scrape_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            scrape=ys.ScrapePolicy(fetcher_type='auto'),
            page=docker_page,
            download=ys.DownloadPolicy(allow=True, allowed_types=('pdf', 'csv', 'json')),
            fingerprint=ys.FingerprintPolicy(),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    result = await crawl_contract_targets(
        SEED,
        CONTRACTS,
        crawl_policy=crawl_policy,
        scrape_policy=scrape_policy,
        output_dir=OUT,
        include_query_strings=True,
        max_targets_per_contract=TOP,
        contract_exemplars=QSCRAPE_EXEMPLARS,
        min_exemplar_score=MIN_EXEMPLAR_SCORE,
        min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
        exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
        scrape_top_per_contract=SCRAPE_TOP,
        scrape_max_concurrency=4,
    )
    eval_path = _write_qscrape_accuracy_eval(result)
    level_eval_path = _write_qscrape_exemplar_level_eval(result)
    frontier_eval_path = _write_qscrape_frontier_generalization_eval(result)
    ys.show(result.summary)
    ys.show(result.plan.as_rows(), title='Validated-exemplar fingerprint target ranking')
    ys.show(
        {
            **result.inventory_paths,
            'qscrape_accuracy_eval': str(eval_path),
            'qscrape_exemplar_level_eval': str(level_eval_path),
            'qscrape_frontier_generalization_eval': str(frontier_eval_path),
        },
        title='Full crawl v2 inventory files',
    )
    if result.scrape_results:
        ys.show(result.scrape_results, title='Verified scrape results for planned targets')


if __name__ == '__main__':
    asyncio.run(main())
