"""Full qscrape.dev crawl v3: binary NewsArticle classification → scrape gate.

Run:
    uv run python examples/qscrape.dev/full_crawl_v3.py

This is an end-to-end stress example for one contract. It crawls all qscrape.dev
from one seed, uses positive-only NewsArticle fingerprint generalization to pick
candidate article URLs, then scrapes every accepted candidate with the
``NewsArticle`` contract. The scrape phase is the final validation gate: accepted
fingerprint candidates that do not produce validated records are reported as
scrape-gate failures.

Unlike ``full_crawl_v2_alt.py``, this script intentionally performs scraping by
default. Scrape discovery defaults to OpenCode with Codex
(``opencode:openai/gpt-5-codex``), so the first run can spend LLM calls creating
selectors while later replay runs can set ``YOSOI_FULL_CRAWL_V3_REPLAY_ONLY=1``
to forbid model discovery. Set ``YOSOI_FULL_CRAWL_V3_SCRAPE=0`` to run only
crawl/classification.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from _fingerprint_plan import crawl_contract_targets

import yosoi as ys

SEED = 'https://qscrape.dev/'
DEFAULT_OUT = Path(chr(46) + 'yosoi') / 'full_crawl_v3'
OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V3_OUTPUT_DIR') or DEFAULT_OUT)
TOP = int(os.getenv('YOSOI_FULL_CRAWL_V3_TOP', '200'))
SCRAPE_ENABLED = os.getenv('YOSOI_FULL_CRAWL_V3_SCRAPE', '1').strip().lower() not in {'0', 'false', 'no'}
REPLAY_ONLY = os.getenv('YOSOI_FULL_CRAWL_V3_REPLAY_ONLY', '0').strip().lower() in {'1', 'true', 'yes'}
SCRAPE_MAX_CONCURRENCY = int(os.getenv('YOSOI_FULL_CRAWL_V3_SCRAPE_MAX_CONCURRENCY', '4'))
DISCOVERY_TOP = int(os.getenv('YOSOI_FULL_CRAWL_V3_DISCOVERY_TOP', '1'))
MIN_EXEMPLAR_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V3_MIN_EXEMPLAR_SCORE', '0.70'))
MIN_EXEMPLAR_MARGIN = float(os.getenv('YOSOI_FULL_CRAWL_V3_MIN_EXEMPLAR_MARGIN', '0.00'))
EXEMPLAR_SUPPORT_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V3_EXEMPLAR_SUPPORT_SCORE', '0.70'))
CHROME_WS_URLS = tuple(
    url.strip()
    for url in os.getenv('YOSOI_CHROME_WS_URLS', 'http://127.0.0.1:9222,http://127.0.0.1:9223').split(',')
    if url.strip()
)
OPENCODE_MODEL = os.getenv('YOSOI_FULL_CRAWL_V3_OPENCODE_MODEL', 'openai/gpt-5-codex')


class NewsArticle(ys.Contract):
    """News article record."""

    headline: str = ys.Title(description='Article headline')
    author: str | None = ys.Author(description='Article author or byline')
    date: str | None = ys.Datetime(description='Article publication date')
    category: str | None = ys.Field(description='Article category or section')
    body_text: str = ys.BodyText(description='Article body, summary, or excerpt')


NEWS_ARTICLE_EXEMPLARS = (
    'https://qscrape.dev/l3/news/article/MHH-001/',
    'https://qscrape.dev/l3/news/article/MHH-002/',
    'https://qscrape.dev/l3/news/article/MHH-003/',
    'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-001%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-003%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
)


def _news_binary_oracle(url: str) -> str:
    """qscrape.dev evaluation oracle; not used by planner scoring or scraping."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if path.startswith('/l3/news/article/'):
        return 'NewsArticle'
    if path.startswith('/l1/news/article') and 'postData' in query:
        return 'NewsArticle'
    return 'NoContract'


def _write_binary_classification_eval(result: Any) -> Path:
    rows = result.plan.as_rows()
    predicted_urls = {str(row['url']) for row in rows}
    training_urls = set(NEWS_ARTICLE_EXEMPLARS)
    payload = {
        'artifact_kind': 'qscrape_news_article_binary_classification_eval',
        'oracle_scope': 'evaluation_only_not_planner_input',
        'scoring_inputs': 'positive_news_article_exemplars_only',
        **_binary_summary(result.inventory.urls, predicted_urls=predicted_urls, training_urls=training_urls),
    }
    path = OUT / 'news_article_binary_classification_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def _binary_summary(urls: list[str], *, predicted_urls: set[str], training_urls: set[str]) -> dict[str, Any]:
    confusion: dict[str, Counter[str]] = {'NewsArticle': Counter(), 'NoContract': Counter()}
    false_positive_examples: list[str] = []
    false_negative_examples: list[str] = []
    total = correct = true_positive = false_positive = false_negative = true_negative = 0

    for url in urls:
        if url in training_urls:
            continue
        actual = _news_binary_oracle(url)
        predicted = 'NewsArticle' if url in predicted_urls else 'NoContract'
        total += 1
        correct += int(predicted == actual)
        confusion[actual][predicted] += 1
        if actual == 'NewsArticle' and predicted == 'NewsArticle':
            true_positive += 1
        elif actual == 'NewsArticle':
            false_negative += 1
            if len(false_negative_examples) < 20:
                false_negative_examples.append(url)
        elif predicted == 'NewsArticle':
            false_positive += 1
            if len(false_positive_examples) < 20:
                false_positive_examples.append(url)
        else:
            true_negative += 1

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {
        'excluded_training_urls': len(training_urls),
        'total_eval_urls': total,
        'accuracy': round(correct / total, 4) if total else None,
        'precision': round(precision, 4) if precision is not None else None,
        'recall': round(recall, 4) if recall is not None else None,
        'f1': round(f1, 4) if f1 is not None else None,
        'true_positive': true_positive,
        'false_positive': false_positive,
        'false_negative': false_negative,
        'true_negative': true_negative,
        'confusion': {label: dict(counts) for label, counts in confusion.items()},
        'false_positive_examples': false_positive_examples,
        'false_negative_examples': false_negative_examples,
    }


def _write_scrape_gate_eval(result: Any) -> Path:
    rows = result.plan.as_rows()
    scrape_results = result.scrape_results.get('NewsArticle') if result.scrape_results else None
    if not isinstance(scrape_results, dict):
        payload: dict[str, Any] = {
            'artifact_kind': 'qscrape_news_article_scrape_gate_eval',
            'scrape_enabled': SCRAPE_ENABLED,
            'replay_only': REPLAY_ONLY,
            'discovery_model': None if REPLAY_ONLY else f'opencode:{OPENCODE_MODEL}',
            'candidate_urls': len(rows),
            'skipped': 'scrape disabled or unavailable',
        }
    else:
        per_url: list[dict[str, Any]] = []
        passed = failed = 0
        for row in rows:
            url = str(row['url'])
            value = scrape_results.get(url, {})
            if isinstance(value, dict):
                error = value.get('error')
                phase = value.get('phase')
                records = value.get('records', [])
            else:
                error = None
                phase = 'unknown'
                records = value if isinstance(value, list) else []
            record_count = len(records)
            ok = record_count > 0 and error is None
            passed += int(ok)
            failed += int(not ok)
            per_url.append(
                {
                    'url': url,
                    'oracle_label': _news_binary_oracle(url),
                    'fingerprint_score': row['score'],
                    'phase': phase,
                    'scrape_passed': ok,
                    'record_count': record_count,
                    'error': error,
                    'sample_keys': sorted(records[0].keys()) if records and isinstance(records[0], dict) else [],
                }
            )
        payload = {
            'artifact_kind': 'qscrape_news_article_scrape_gate_eval',
            'scrape_enabled': True,
            'replay_only': REPLAY_ONLY,
            'discovery_model': None if REPLAY_ONLY else f'opencode:{OPENCODE_MODEL}',
            'candidate_urls': len(rows),
            'discovery_candidate_limit': 0 if REPLAY_ONLY else DISCOVERY_TOP,
            'scrape_passed_urls': passed,
            'scrape_failed_urls': failed,
            'scrape_pass_rate': round(passed / len(rows), 4) if rows else None,
            'rows': per_url,
        }
    path = OUT / 'news_article_scrape_gate_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


async def _scrape_news_targets(result: Any, *, discovery_policy: ys.Policy, replay_policy: ys.Policy) -> dict[str, Any]:
    if not SCRAPE_ENABLED:
        return {}
    urls = result.plan.neutral_candidate_urls(NewsArticle, limit=TOP)
    discovery_urls = [] if REPLAY_ONLY else urls[: max(0, DISCOVERY_TOP)]
    replay_urls = urls if REPLAY_ONLY else urls[max(0, DISCOVERY_TOP) :]
    output: dict[str, dict[str, object]] = {}

    async def scrape_one(url: str, *, phase: str, policy: ys.Policy) -> None:
        try:
            records = await ys.scrape(url, NewsArticle, policy=policy)
        except Exception as exc:
            output[url] = {'phase': phase, 'records': [], 'error': f'{type(exc).__name__}: {exc}'}
            return
        output[url] = {'phase': phase, 'records': cast(list[dict[str, object]], records), 'error': None}

    for url in discovery_urls:
        await scrape_one(url, phase='discovery', policy=discovery_policy)

    semaphore = asyncio.Semaphore(SCRAPE_MAX_CONCURRENCY)

    async def replay_one(url: str) -> None:
        async with semaphore:
            await scrape_one(url, phase='replay', policy=replay_policy)

    await asyncio.gather(*(replay_one(url) for url in replay_urls))
    return {'NewsArticle': output}


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
    discovery_scrape_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            model=None if REPLAY_ONLY else ys.opencode(OPENCODE_MODEL),
            scrape=ys.ScrapePolicy(fetcher_type='auto', force=not REPLAY_ONLY),
            discovery=ys.DiscoveryPolicy(lesson_cache=True),
            page=docker_page,
            fingerprint=ys.FingerprintPolicy(),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    replay_scrape_policy = ys.Policy.cascade(
        ys.Policy.from_env(),
        ys.Policy(
            model=None,
            scrape=ys.ScrapePolicy(fetcher_type='auto', force=False),
            discovery=ys.DiscoveryPolicy(lesson_cache=True),
            page=docker_page,
            fingerprint=ys.FingerprintPolicy(),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    result = await crawl_contract_targets(
        SEED,
        (NewsArticle,),
        crawl_policy=crawl_policy,
        scrape_policy=discovery_scrape_policy,
        output_dir=OUT,
        include_query_strings=True,
        max_targets_per_contract=TOP,
        contract_exemplars={NewsArticle: NEWS_ARTICLE_EXEMPLARS},
        min_exemplar_score=MIN_EXEMPLAR_SCORE,
        min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
        exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
        scrape_top_per_contract=0,
    )
    result.scrape_results.update(
        await _scrape_news_targets(
            result,
            discovery_policy=discovery_scrape_policy,
            replay_policy=replay_scrape_policy,
        )
    )
    classification_eval_path = _write_binary_classification_eval(result)
    scrape_gate_eval_path = _write_scrape_gate_eval(result)
    ys.show(result.summary)
    ys.show(result.plan.as_rows(), title='V3 NewsArticle fingerprint candidates')
    ys.show(
        {
            **result.inventory_paths,
            'news_article_binary_classification_eval': str(classification_eval_path),
            'news_article_scrape_gate_eval': str(scrape_gate_eval_path),
        },
        title='Full crawl v3 files',
    )
    if result.scrape_results:
        ys.show(result.scrape_results, title='V3 NewsArticle scrape gate results')


if __name__ == '__main__':
    asyncio.run(main())
