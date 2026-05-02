"""Mocked-eval demo: ingest tagged traces into local Langfuse.

Demonstrates the eval-tagging workflow documented at observability/evals-and-tagging.md.
Run with the local Langfuse stack running on http://localhost:3000.

Two modes:
- (default) one traced "scrape" emitting a single trace tagged regression.
- --concurrent: workers=2, 4 URLs across 2 (sub)domains, real Pipeline +
  Agent.override(model=TestModel()) — verifies session/user propagation across
  the concurrent dispatch path.
"""

from __future__ import annotations

import argparse
import asyncio
import os

from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace

# Local Langfuse stack defaults from docker-compose.langfuse.yml.
os.environ.setdefault('LANGFUSE_PUBLIC_KEY', 'pk-lf-yosoi-local')
os.environ.setdefault('LANGFUSE_SECRET_KEY', 'sk-lf-yosoi-local')
os.environ.setdefault('LANGFUSE_HOST', 'http://localhost:3000')


def _single_trace_demo() -> str:
    client = Langfuse(should_export_span=lambda _s: True)
    tracer = trace.get_tracer('yosoi-eval-demo')

    with (
        propagate_attributes(
            session_id='eval-demo-session',
            user_id='shop.example.com',
            tags=['yosoi', 'eval', 'regression'],
        ),
        tracer.start_as_current_span('scrape shop.example.com/x') as root,
    ):
        root.set_attribute('url', 'https://shop.example.com/x')
        with tracer.start_as_current_span('fetch') as fetch:
            fetch.set_attribute('status', 200)
        with tracer.start_as_current_span('discover') as discover:
            discover.set_attribute('fields', 2)
        with tracer.start_as_current_span('extract') as extract:
            extract.set_attribute('items', 1)
        trace_id = format(root.get_span_context().trace_id, '032x')

    client.flush()
    return trace_id


async def _concurrent_demo() -> str:
    """Real Pipeline + workers=2 + 4 URLs across 2 (sub)domains under TestModel.

    Stubs fetcher and discovery so the demo doesn't hit the network or call
    a real LLM. The point is to verify session/user propagation across the
    concurrent dispatch path in live Langfuse data, not to actually scrape.
    """
    from pydantic_ai import Agent

    from yosoi.core import pipeline as _pipeline_mod
    from yosoi.core.discovery import orchestrator as _orch_mod
    from yosoi.core.discovery.config import LLMConfig
    from yosoi.core.pipeline import Pipeline
    from yosoi.models.defaults import NewsArticle
    from yosoi.models.results import ContentMetadata, FetchResult
    from yosoi.utils import observability as obs

    # Pin the session id BEFORE any Pipeline construction so process_session_id()
    # resolves to it lazily. Honour an env-provided value so callers can re-run
    # with a fresh session id.
    sess_id = os.environ.setdefault('YOSOI_SESSION_ID', 'eval-demo-concurrent-session')

    Agent.instrument_all()

    llm_config = LLMConfig(
        provider='groq',
        model_name='llama-3.3-70b-versatile',
        api_key='unused-test-key',
        temperature=0.0,
    )

    canned_html = '<html><body><h1 class="title">demo</h1><span class="author">a</span><span class="date">2026-01-01</span><article>x</article><div class="related"><a>x</a></div></body></html>'
    discovered_map = {
        'headline': {'primary': {'strategy': 'css', 'level': 1, 'value': 'h1.title'}},
        'author': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.author'}},
        'date': {'primary': {'strategy': 'css', 'level': 1, 'value': 'span.date'}},
        'body_text': {'primary': {'strategy': 'css', 'level': 1, 'value': 'article'}},
        'related_content': {'primary': {'strategy': 'css', 'level': 1, 'value': '.related'}},
    }

    class _FakeFetcher:
        async def fetch(self, _url: str) -> FetchResult:
            return FetchResult(
                url='http://example.com',
                html=canned_html,
                status_code=200,
                metadata=ContentMetadata(content_length=len(canned_html)),
            )

        async def __aenter__(self) -> _FakeFetcher:
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

    async def _fake_discover(*_args: object, **_kwargs: object) -> dict:
        return discovered_map

    # Manual stubs in place of unittest.mock — script doesn't depend on the
    # pytest-mock plugin, and the project bans `unittest` imports outright.
    original_create_fetcher = _pipeline_mod.create_fetcher
    original_discover = _orch_mod.DiscoveryOrchestrator.discover_selectors
    _pipeline_mod.create_fetcher = lambda *_a, **_kw: _FakeFetcher()  # type: ignore[assignment]
    _orch_mod.DiscoveryOrchestrator.discover_selectors = _fake_discover  # type: ignore[assignment]

    pipeline = Pipeline(llm_config, contract=NewsArticle, quiet=True)

    urls = [
        'https://a.example.com/1',
        'https://b.example.com/1',
        'https://a.example.com/2',
        'https://b.example.com/2',
    ]

    try:
        with propagate_attributes(tags=['yosoi', 'eval', 'regression']):
            await pipeline.process_urls(urls, workers=2, force=True, origin='script')
    finally:
        _pipeline_mod.create_fetcher = original_create_fetcher  # type: ignore[assignment]
        _orch_mod.DiscoveryOrchestrator.discover_selectors = original_discover  # type: ignore[assignment]

    obs.flush()
    return sess_id


def main() -> None:
    """Parse CLI args and run the chosen demo mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--concurrent',
        action='store_true',
        help='Run a real-Pipeline concurrent demo (workers=2, 4 URLs, 2 sub-domains).',
    )
    args = parser.parse_args()

    if args.concurrent:
        sess_id = asyncio.run(_concurrent_demo())
        print(f'SESSION_ID={sess_id}')
        print('Verify with:')
        print(f'  npx -y langfuse-cli api traces list --session-id {sess_id} --limit 10')
        print(f'  npx -y langfuse-cli api traces list --user-id a.example.com --session-id {sess_id}')
        print(f'  npx -y langfuse-cli api traces list --user-id b.example.com --session-id {sess_id}')
    else:
        trace_id = _single_trace_demo()
        print(f'TRACE_ID={trace_id}')
        print(f'URL=http://localhost:3000/project/00000000-0000-0000-0000-000000000002/traces/{trace_id}')


if __name__ == '__main__':
    main()
