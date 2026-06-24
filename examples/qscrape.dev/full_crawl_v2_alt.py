"""Full qscrape.dev crawl v2-alt: binary NewsArticle target generalization.

Run:
    uv run python examples/qscrape.dev/full_crawl_v2_alt.py

This variant cares only about finding NewsArticle target pages. It intentionally
uses positive NewsArticle exemplars only; non-news URLs are evaluation labels, not
contrastive scoring inputs. That makes the demo simpler and exposes where
positive-only same-domain generalization cracks. The crawler still starts from
the single site seed, uses ``fetcher_type='auto'``, and writes all-pairs
fingerprint scores. Verified scraping remains opt-in with
``YOSOI_FULL_CRAWL_V2_ALT_SCRAPE_TOP_PER_CONTRACT``.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from _fingerprint_plan import crawl_contract_targets, plan_contract_targets

import yosoi as ys

SEED = 'https://qscrape.dev/'
DEFAULT_OUT = Path(chr(46) + 'yosoi') / 'full_crawl_v2_alt'
OUT = Path(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_OUTPUT_DIR') or DEFAULT_OUT)
TOP = int(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_TOP', '80'))
SCRAPE_TOP = int(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_SCRAPE_TOP_PER_CONTRACT', '0'))
MIN_EXEMPLAR_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_MIN_EXEMPLAR_SCORE', '0.70'))
MIN_EXEMPLAR_MARGIN = float(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_MIN_EXEMPLAR_MARGIN', '0.00'))
EXEMPLAR_SUPPORT_SCORE = float(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_EXEMPLAR_SUPPORT_SCORE', '0.70'))
CONTRASTIVE_WEIGHT = float(os.getenv('YOSOI_FULL_CRAWL_V2_ALT_CONTRASTIVE_WEIGHT', '0.0'))
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


NEWS_ARTICLE_EXEMPLARS = (
    'https://qscrape.dev/l3/news/article/MHH-001/',
    'https://qscrape.dev/l3/news/article/MHH-002/',
    'https://qscrape.dev/l3/news/article/MHH-003/',
    'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-001%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
    'https://qscrape.dev/l1/news/article?postData=MHH_v1_Kp9rXm2bQsXXXNNNXXXID%3DMHH-003%26HASH%3Dcrawl-XXXNNNXXXtR7vYw1hF3dGXXXNNNXXX',
)


def _news_binary_oracle(url: str) -> str:
    """qscrape.dev evaluation oracle; not used by planner scoring."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if path.startswith('/l3/news/article/'):
        return 'NewsArticle'
    if path.startswith('/l1/news/article') and 'postData' in query:
        return 'NewsArticle'
    return 'NoContract'


def _write_news_binary_eval(result: Any) -> Path:
    levels: list[dict[str, Any]] = []
    for exemplar_count in (5, 4, 3, 2, 1, 0):
        positives = NEWS_ARTICLE_EXEMPLARS[:exemplar_count]
        training_urls = set(positives)
        if positives:
            plan = plan_contract_targets(
                result.inventory,
                (NewsArticle,),
                max_targets_per_contract=None,
                contract_exemplars={NewsArticle: positives},
                contrastive_exemplars=None,
                contrastive_weight=CONTRASTIVE_WEIGHT,
                min_exemplar_score=MIN_EXEMPLAR_SCORE,
                min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
                exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
            )
            predictions = {row['url']: row['fanout_contract'] for row in plan.as_rows()}
        else:
            predictions = {}
        levels.append(
            {
                'exemplars': exemplar_count,
                **_binary_summary(result.inventory.urls, predictions=predictions, training_urls=training_urls),
            }
        )

    payload = {
        'artifact_kind': 'qscrape_news_article_binary_eval',
        'oracle_scope': 'evaluation_only_not_planner_input',
        'positive_label': 'NewsArticle',
        'negative_label': 'NoContract',
        'scoring_inputs': 'positive_news_article_exemplars_only',
        'levels': levels,
    }
    path = OUT / 'news_article_binary_eval.json'
    path.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    return path


def _binary_summary(urls: list[str], *, predictions: dict[str, str], training_urls: set[str]) -> dict[str, Any]:
    confusion: dict[str, Counter[str]] = {'NewsArticle': Counter(), 'NoContract': Counter()}
    false_positive_examples: list[str] = []
    false_negative_examples: list[str] = []
    total = correct = true_positive = false_positive = false_negative = true_negative = 0

    for url in urls:
        if url in training_urls:
            continue
        actual = _news_binary_oracle(url)
        predicted = predictions.get(url, 'NoContract')
        total += 1
        correct += int(predicted == actual)
        confusion[actual][predicted] += 1
        if actual == 'NewsArticle' and predicted == 'NewsArticle':
            true_positive += 1
        elif actual == 'NewsArticle':
            false_negative += 1
            if len(false_negative_examples) < 10:
                false_negative_examples.append(url)
        elif predicted == 'NewsArticle':
            false_positive += 1
            if len(false_positive_examples) < 10:
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
            fingerprint=ys.FingerprintPolicy(),
            output=ys.OutputPolicy(quiet=False),
        ),
    )
    result = await crawl_contract_targets(
        SEED,
        (NewsArticle,),
        crawl_policy=crawl_policy,
        scrape_policy=scrape_policy,
        output_dir=OUT,
        include_query_strings=True,
        max_targets_per_contract=TOP,
        contract_exemplars={NewsArticle: NEWS_ARTICLE_EXEMPLARS},
        contrastive_exemplars=None,
        contrastive_weight=CONTRASTIVE_WEIGHT,
        min_exemplar_score=MIN_EXEMPLAR_SCORE,
        min_exemplar_margin=MIN_EXEMPLAR_MARGIN,
        exemplar_support_score=EXEMPLAR_SUPPORT_SCORE,
        scrape_top_per_contract=SCRAPE_TOP,
        scrape_max_concurrency=4,
    )
    eval_path = _write_news_binary_eval(result)
    ys.show(result.summary)
    ys.show(result.plan.as_rows(), title='Binary NewsArticle fingerprint target ranking')
    ys.show({**result.inventory_paths, 'news_article_binary_eval': str(eval_path)}, title='Full crawl v2-alt files')
    if result.scrape_results:
        ys.show(result.scrape_results, title='Verified scrape results for planned NewsArticle targets')


if __name__ == '__main__':
    asyncio.run(main())
