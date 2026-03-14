"""Tests that validate Yosoi type stubs are correct via mypy."""

import subprocess
import sys
import textwrap
from pathlib import Path

SNIPPETS_DIR = Path(__file__).parent / 'snippets'


def _run_mypy(code: str) -> subprocess.CompletedProcess[str]:
    """Run mypy on a code snippet, return the result."""
    SNIPPETS_DIR.mkdir(exist_ok=True)
    snippet_file = SNIPPETS_DIR / '_check.py'
    snippet_file.write_text(code)
    try:
        return subprocess.run(
            [sys.executable, '-m', 'mypy', '--strict', '--no-error-summary', str(snippet_file)],
            capture_output=True,
            text=True,
            timeout=30,
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
    """Verify that provider helpers are seen as returning LLMConfig."""

    def test_groq_returns_llmconfig(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys
            from yosoi.core.discovery.config import LLMConfig

            c: LLMConfig = ys.groq('llama-3.3-70b-versatile')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_provider_returns_llmconfig(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys
            from yosoi.core.discovery.config import LLMConfig

            c: LLMConfig = ys.provider('groq:llama-3.3-70b-versatile')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_gemini_with_api_key(self) -> None:
        result = _run_mypy(
            textwrap.dedent("""\
            import yosoi as ys
            from yosoi.core.discovery.config import LLMConfig

            c: LLMConfig = ys.gemini('gemini-2.0-flash', api_key='test')
        """)
        )
        assert result.returncode == 0, result.stdout + result.stderr
