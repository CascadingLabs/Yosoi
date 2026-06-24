"""Full crawl v3 domain-axis eval: sub-path vs same-domain vs cross-domain.

Run:
    uv run python examples/qscrape.dev/full_crawl_v3_domain_axis.py

This example answers a narrow generalization question: given a frontier produced
by ``ys.crawl``, how do fingerprint classifications perform when evaluation URLs
are on the same route family as the exemplars, elsewhere on the same domain, or
on a different domain?

Two classifier views are emitted from the same weighted-Jaccard plan:

* binary: ``NewsArticle`` vs ``NoContract``
* multi: ``NewsArticle | TaxInfo | ScoreContract | ProductContract | NoContract``

The domain axis and URL oracles are evaluation-only metadata. They are not passed
to the planner and must not influence weighted-Jaccard scoring.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from _fingerprint_plan import CrawlInventory, plan_contract_targets, write_target_inventory

import yosoi as ys
from yosoi.models.contract import Contract
from yosoi.models.download import DownloadRecord

SEEDS = tuple(
    url.strip()
    for url in os.getenv(
        'YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_SEEDS',
        ','.join(
            (
                'https://qscrape.dev/',
                'https://www.cnn.com/',
                'https://finance.yahoo.com/',
                'https://www.miamidade.gov/global/service.page?Mduid_service=ser1499797463767131',
                'https://www.vlr.gg/',
            )
        ),
    ).split(',')
    if url.strip()
)
DEFAULT_OUT = Path(chr(46) + 'yosoi') / 'full_crawl_v3_domain_axis'
OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_OUTPUT_DIR') or DEFAULT_OUT)
TOP = int(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_TOP_PER_CONTRACT', '200'))
MAX_PAGES = int(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_MAX_PAGES', '1200'))
MAX_DEPTH = int(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_MAX_DEPTH', '3'))
MIN_EXEMPLAR_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_MIN_EXEMPLAR_SCORE', '0.0'))
MIN_EXEMPLAR_MARGIN = float(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_MIN_EXEMPLAR_MARGIN', '-1.0'))
EXEMPLAR_SUPPORT_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_EXEMPLAR_SUPPORT_SCORE', '0.70'))
CONTRASTIVE_WEIGHT = float(os.getenv('YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_CONTRASTIVE_WEIGHT', '0.50'))
ALLOWED_HOSTS = tuple(
    host.strip()
    for host in os.getenv(
        'YOSOI_FULL_CRAWL_V3_DOMAIN_AXIS_ALLOWED_HOSTS',
        'qscrape.dev,www.cnn.com,cnn.com,finance.yahoo.com,www.miamidade.gov,www.vlr.gg,vlr.gg',
    ).split(',')
    if host.strip()
)
CHROME_WS_URLS = tuple(
    url.strip()
    for url in os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223').split(',')
    if url.strip()
)


class NewsArticle(ys.Contract):
    """News article record."""

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
    """Match, game, or standings row."""

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
TARGET_LABELS = tuple(contract.__name__ for contract in CONTRACTS)
NO_CONTRACT = 'NoContract'
AXES = ('sub_path', 'same_domain', 'cross_domain')

QSCRAPE_EXEMPLARS: dict[type[Contract] | str, tuple[str, ...]] = {
    NewsArticle: (
        'https://qscrape.dev/l3/news/article/MHH-001/',
        'https://qscrape.dev/l3/news/article/MHH-002/',
        'https://qscrape.dev/l3/news/article/MHH-003/',
        'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-001%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
        'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-003%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
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
        'https://qscrape.dev/l1/scoretap/event?id=iem-katowice-2026',
        'https://qscrape.dev/l1/scoretap/team?id=vitality',
    ),
    ProductContract: (
        'https://qscrape.dev/l3/eshop/product/VM-FDB-001/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-002/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-003/',
        'https://qscrape.dev/l3/eshop/product/VM-FDB-004/',
    ),
}

QSCRAPE_CONTRASTIVE_EXEMPLARS = (
    'https://qscrape.dev/',
    'https://qscrape.dev/l3/eshop/',
    'https://qscrape.dev/l1/scoretap/',
    'https://qscrape.dev/l1/scoretap/article/',
    'https://qscrape.dev/l3/taxes/',
    'https://qscrape.dev/l1/news/about/',
    'https://qscrape.dev/l1/news/staff/',
)
TRAINING_URLS = tuple(url for urls in QSCRAPE_EXEMPLARS.values() for url in urls) + QSCRAPE_CONTRASTIVE_EXEMPLARS
CRITICAL_CRAWL_SEEDS = (
    *SEEDS,
    *(urls[0] for urls in QSCRAPE_EXEMPLARS.values()),
    *QSCRAPE_CONTRASTIVE_EXEMPLARS[:2],
)


def _unique_prefer_last(urls: Sequence[str]) -> tuple[str, ...]:
    """Deduplicate while keeping later entries later for the DFS/LIFO crawler."""
    return tuple(reversed(tuple(dict.fromkeys(reversed(tuple(urls))))))


CRAWL_SEEDS = _unique_prefer_last((*TRAINING_URLS, *QSCRAPE_CONTRASTIVE_EXEMPLARS, *CRITICAL_CRAWL_SEEDS))


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower().split('@')[-1].split(':')[0]
    return host[4:] if host.startswith('www.') else host


def _route_key(url: str) -> tuple[str, tuple[str, ...]]:
    parsed = urlparse(url)
    parts = tuple(part for part in parsed.path.lower().strip('/').split('/') if part)
    if _host(url) == 'qscrape.dev' and len(parts) >= 3:
        return (_host(url), parts[:3])
    if _host(url) in {'cnn.com', 'finance.yahoo.com'}:
        return (_host(url), parts[:1] if parts else ())
    if _host(url) == 'vlr.gg':
        return (_host(url), parts[:1] if parts else ())
    if 'miamidade.gov' in _host(url):
        return (_host(url), parts[:2] if len(parts) >= 2 else parts)
    return (_host(url), parts[:2] if len(parts) >= 2 else parts)


def _domain_axis(url: str, *, actual_label: str, exemplars: Mapping[type[Contract] | str, Sequence[str]]) -> str:
    exemplar_urls = _exemplar_urls_for_label(actual_label, exemplars)
    if not exemplar_urls:
        exemplar_urls = tuple(ex for values in exemplars.values() for ex in values)
    host = _host(url)
    route = _route_key(url)
    exemplar_hosts = {_host(exemplar) for exemplar in exemplar_urls}
    if any(route == _route_key(exemplar) for exemplar in exemplar_urls):
        return 'sub_path'
    if host in exemplar_hosts:
        return 'same_domain'
    return 'cross_domain'


def _exemplar_urls_for_label(label: str, exemplars: Mapping[type[Contract] | str, Sequence[str]]) -> tuple[str, ...]:
    for key, urls in exemplars.items():
        name = key if isinstance(key, str) else key.__name__
        if name == label:
            return tuple(urls)
    return ()


def _oracle_label(url: str) -> str:
    """Evaluation oracle for demo frontiers; not used by scoring."""
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    parts = tuple(part for part in path.strip('/').split('/') if part)

    if host == 'qscrape.dev':
        if path.startswith('/l3/news/article/') or (path.startswith('/l1/news/article') and 'postData' in query):
            return 'NewsArticle'
        if path.startswith('/l3/taxes/viewer/'):
            return 'TaxInfo'
        if path.startswith('/l1/scoretap/') and {'match', 'team', 'event'} & set(parts):
            return 'ScoreContract'
        if '/eshop/product/' in path and not path.rstrip('/').endswith('/product'):
            return 'ProductContract'
        return NO_CONTRACT

    if host == 'cnn.com':
        if any(part.isdigit() and len(part) == 4 and part.startswith('20') for part in parts) or '/article/' in path:
            return 'NewsArticle'
        return NO_CONTRACT
    if host == 'finance.yahoo.com':
        return 'NewsArticle' if path.startswith('/news/') and path.rstrip('/') != '/news' else NO_CONTRACT
    if host == 'vlr.gg':
        return 'ScoreContract' if parts and parts[0].isdigit() else NO_CONTRACT
    if 'miamidade.gov' in host:
        tax_words = ('tax', 'property', 'folio', 'parcel', 'deed', 'record')
        return 'TaxInfo' if any(word in path or word in parsed.query.lower() for word in tax_words) else NO_CONTRACT
    return NO_CONTRACT


def _binary_prediction(label: str) -> str:
    return 'NewsArticle' if label == 'NewsArticle' else NO_CONTRACT


def _metrics_from_counts(tp: int, fp: int, fn: int, tn: int, correct: int, total: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        'total_eval_urls': total,
        'accuracy': round(correct / total, 4) if total else 0.0,
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1': round(f1, 4),
        'zero_division': 0,
        'true_positive': tp,
        'false_positive': fp,
        'false_negative': fn,
        'true_negative': tn,
    }


def _classification_summary(
    urls: Sequence[str],
    *,
    predictions: Mapping[str, str],
    training_urls: set[str],
    mode: str,
    exemplars: Mapping[type[Contract] | str, Sequence[str]] = QSCRAPE_EXEMPLARS,
) -> dict[str, Any]:
    if mode not in {'binary', 'multi'}:
        raise ValueError(f'unknown classification mode: {mode}')

    by_axis: dict[str, dict[str, Any]] = {}
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    global_counts = Counter()

    for url in urls:
        if url in training_urls:
            continue
        actual_multi = _oracle_label(url)
        predicted_multi = predictions.get(url, NO_CONTRACT)
        actual = _binary_prediction(actual_multi) if mode == 'binary' else actual_multi
        predicted = _binary_prediction(predicted_multi) if mode == 'binary' else predicted_multi
        axis = _domain_axis(url, actual_label=actual_multi, exemplars=exemplars)
        is_correct = predicted == actual
        is_actual_positive = actual != NO_CONTRACT
        is_predicted_positive = predicted != NO_CONTRACT

        axis_counts = by_axis.setdefault(axis, {'counts': Counter(), 'confusion': defaultdict(Counter), 'examples': []})
        for counts in (axis_counts['counts'], global_counts):
            counts['total'] += 1
            counts['correct'] += int(is_correct)
            counts['tp'] += int(is_actual_positive and is_predicted_positive and is_correct)
            counts['tn'] += int(not is_actual_positive and not is_predicted_positive)
            counts['fp'] += int(
                (not is_actual_positive and is_predicted_positive)
                or (is_actual_positive and is_predicted_positive and not is_correct)
            )
            counts['fn'] += int(is_actual_positive and (not is_predicted_positive or not is_correct))
        axis_counts['confusion'][actual][predicted] += 1
        confusion[actual][predicted] += 1
        if not is_correct and len(axis_counts['examples']) < 10:
            example = {'actual': actual, 'predicted': predicted, 'url': url}
            axis_counts['examples'].append(example)
            if len(examples[axis]) < 10:
                examples[axis].append(example)

    axis_payload = {}
    for axis in AXES:
        bucket = by_axis.get(axis, {'counts': Counter(), 'confusion': defaultdict(Counter), 'examples': []})
        counts = bucket['counts']
        axis_payload[axis] = {
            **_metrics_from_counts(
                counts['tp'], counts['fp'], counts['fn'], counts['tn'], counts['correct'], counts['total']
            ),
            'confusion': {actual: dict(predicted) for actual, predicted in sorted(bucket['confusion'].items())},
            'wrong_examples': bucket['examples'],
        }

    return {
        'mode': mode,
        'excluded_training_urls': len(training_urls),
        **_metrics_from_counts(
            global_counts['tp'],
            global_counts['fp'],
            global_counts['fn'],
            global_counts['tn'],
            global_counts['correct'],
            global_counts['total'],
        ),
        'confusion': {actual: dict(predicted) for actual, predicted in sorted(confusion.items())},
        'by_domain_axis': axis_payload,
    }


def _write_domain_axis_eval(inventory: CrawlInventory, predictions: Mapping[str, str]) -> Path:
    training_urls = {url for urls in QSCRAPE_EXEMPLARS.values() for url in urls} | set(QSCRAPE_CONTRASTIVE_EXEMPLARS)
    payload = {
        'artifact_kind': 'full_crawl_v3_domain_axis_eval',
        'oracle_scope': 'evaluation_only_not_planner_input',
        'frontier_source': 'ys.crawl',
        'scoring': 'positive_exemplar_weighted_jaccard_minus_optional_contrastive_similarity',
        'seeds': list(SEEDS),
        'training_urls_seeded_for_single_crawl': len(TRAINING_URLS),
        'crawl_seed_count': len(CRAWL_SEEDS),
        'allowed_hosts': list(ALLOWED_HOSTS),
        'axes': list(AXES),
        'binary': _classification_summary(
            inventory.urls, predictions=predictions, training_urls=training_urls, mode='binary'
        ),
        'multi': _classification_summary(
            inventory.urls, predictions=predictions, training_urls=training_urls, mode='multi'
        ),
    }
    path = OUT / 'domain_axis_classification_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


async def main() -> None:
    docker_page = ys.PagePolicy(fetcher_type='auto', chrome_ws_urls=CHROME_WS_URLS)
    policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            crawl=ys.CrawlPolicy(
                budget=ys.CrawlBudget(max_pages=MAX_PAGES, max_depth=MAX_DEPTH, max_attempts=MAX_PAGES * 2),
                scheduler=ys.SchedulerPolicy(
                    max_workers=16,
                    per_host_concurrency=4,
                    politeness_delay=0,
                    fetch_timeout_seconds=8,
                    max_fetch_retries=1,
                ),
                safety=ys.CrawlSafety(
                    respect_robots=False,
                    allow_redirects=True,
                    allowed_hosts=ALLOWED_HOSTS,
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
    summary = await ys.crawl(CRAWL_SEEDS, policy=policy)
    inventory = CrawlInventory.from_summary(summary)
    plan = plan_contract_targets(
        inventory,
        CONTRACTS,
        max_targets_per_contract=TOP,
        contract_exemplars=QSCRAPE_EXEMPLARS,
        contrastive_exemplars=QSCRAPE_CONTRASTIVE_EXEMPLARS,
        contrastive_weight=CONTRASTIVE_WEIGHT,
        min_exemplar_score=MIN_EXEMPLAR_SCORE,
        min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
        exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
    )
    await asyncio.to_thread(OUT.mkdir, parents=True, exist_ok=True)
    inventory_paths = write_target_inventory(summary, plan, OUT, include_query_strings=True)
    predictions = {str(row['url']): str(row['fanout_contract']) for row in plan.as_rows()}
    eval_path = _write_domain_axis_eval(inventory, predictions)

    ys.show(summary)
    ys.show(plan.as_rows(), title='V3 domain-axis weighted-Jaccard candidates')
    ys.show(
        {**inventory_paths, 'domain_axis_classification_eval': str(eval_path)}, title='Full crawl v3 domain-axis files'
    )


if __name__ == '__main__':
    asyncio.run(main())
