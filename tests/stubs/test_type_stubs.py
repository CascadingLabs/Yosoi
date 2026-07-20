"""Tests that validate Yosoi type stubs are correct via mypy."""

import subprocess
import sys
import textwrap
import uuid

from tests.stubs.conftest import SNIPPETS_DIR


def _run_mypy(code: str) -> subprocess.CompletedProcess[str]:
    """Run mypy on a code snippet, return the result."""
    SNIPPETS_DIR.mkdir(exist_ok=True)
    snippet_file = SNIPPETS_DIR / f'_check_{uuid.uuid4().hex}.py'
    snippet_file.write_text(code)
    try:
        return subprocess.run(
            [sys.executable, '-m', 'mypy', '--strict', '--no-incremental', '--no-error-summary', str(snippet_file)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        snippet_file.unlink(missing_ok=True)


class TestFieldFactoryStubs:
    """Verify that semantic type factories are seen as returning FieldInfo."""

    def test_contract_with_title_and_price(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Product(ys.Contract):
                name: str = ys.Title(description='Product name')
                price: float = ys.Price(currency_symbol='\\u20ac')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_field_is_assignable(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Item(ys.Contract):
                name: str = ys.Field(description='test')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_rating_kwargs(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Review(ys.Contract):
                score: float = ys.Rating(as_float=True, scale=10)
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_url_kwargs(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Page(ys.Contract):
                link: str = ys.Url(require_https=False, strip_tracking=True)
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_datetime_kwargs(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Article(ys.Contract):
                published: str = ys.Datetime(past_only=True, as_iso=True)
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_extractor_plans_and_bound_decorators(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            def normalize(value: str) -> str:
                return value.strip()

            class Company(ys.Contract):
                name: str = ys.css('h1').text()
                links: list[str] = ys.css('a[href]').attr('href').map(normalize)
                industry: str = ys.Extractor()

                @ys.extraction(industry)
                async def industry_value(row: ys.ExtractionRow) -> str:
                    return str(row.text('.industry'))
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_body_text_and_author(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            class Blog(ys.Contract):
                body: str = ys.BodyText()
                writer: str = ys.Author()
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestProviderStubs:
    """Verify that provider helpers are seen as returning ModelPolicy."""

    def test_groq_returns_model_policy(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            c: ys.ModelPolicy = ys.groq('llama-3.3-70b-versatile')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestPolicyStubs:
    """Verify that top-level policy constructors expose keyword signatures."""

    def test_top_level_policy_kwargs_typecheck(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            policy = ys.Policy.for_crawl(
                'crawl.conservative',
                budget=ys.CrawlBudget(
                    max_pages=200,
                    max_depth=2,
                    max_attempts=240,
                    max_pages_per_host=80,
                    crawl_session_id='sports-news-candidates-001',
                ),
                scheduler=ys.SchedulerPolicy(
                    max_workers=5,
                    per_host_concurrency=1,
                    politeness_delay=1.0,
                    fetch_timeout_seconds=15.0,
                    max_fetch_retries=2,
                ),
                safety=ys.CrawlSafety(
                    respect_robots=True,
                    allow_redirects=False,
                    allowed_hosts=('www.espn.com',),
                    blocked_path_prefixes=('/login',),
                ),
                escalation=ys.EscalationPolicy(
                    allow_model_discovery=False,
                    allow_paid_scrapers=False,
                    max_llm_calls=0,
                    max_paid_scraper_calls=0,
                ),
                target_contracts=['NewsArticle'],
                fetcher_type='auto',
            )
            check = ys.check_policy(policy, seeds=('https://www.espn.com/nfl/',))
            assert check.runtime is not None
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_crawl_public_api_typechecks(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            async def main() -> ys.CrawlRunSummary:
                single = await ys.crawl(
                    'https://example.com/',
                    contracts=ys.NewsArticle,
                    limit=10,
                    policy=ys.Policy.for_crawl('crawl.conservative'),
                )
                await ys.crawl(
                    ['https://example.com/'],
                    contracts=[ys.NewsArticle, ys.Product],
                    limit=10,
                    policy=ys.Policy.for_crawl('crawl.conservative'),
                )
                return single
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_crawl_representative_url_api_typechecks(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            async def main() -> None:
                summary = await ys.crawl(
                    'https://example.com/',
                    contracts=ys.NewsArticle,
                    policy=ys.Policy.for_crawl('crawl.conservative'),
                )
                scrape_targets: list[str] = summary.scrape_target_urls(limit=5)
                representatives: list[str] = summary.representative_urls(limit=5)
                assert scrape_targets is not None
                assert representatives is not None
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_top_level_policy_kwargs_fail_static_on_misspelling(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            ys.EscalationPolicy(allow_model_discover=True)
        """)
        )
        assert result.returncode != 0
        assert 'Unexpected keyword argument "allow_model_discover"' in result.stdout + result.stderr

    def test_provider_returns_model_policy(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            c: ys.ModelPolicy = ys.provider('groq:llama-3.3-70b-versatile')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gemini_with_api_key(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys

            c: ys.ModelPolicy = ys.gemini('gemini-2.0-flash', api_key='test')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr
