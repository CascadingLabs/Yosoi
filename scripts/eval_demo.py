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

    Stubs ONLY the fetcher (no network) and lets the real ``DiscoveryOrchestrator``
    + ``FieldDiscoveryAgent`` run with ``Agent.override(model=TestModel())``
    swapping in a deterministic fake LLM. This causes pydantic-ai's
    instrumentation to emit ``agent run`` and ``chat <model>`` spans visible
    in localhost Langfuse — the visibility gap Phase 3 was meant to close.
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from yosoi.core import pipeline as _pipeline_mod
    from yosoi.core.discovery.config import LLMConfig
    from yosoi.core.pipeline import Pipeline
    from yosoi.models.defaults import NewsArticle
    from yosoi.models.results import ContentMetadata, FetchResult
    from yosoi.utils import observability as obs

    sess_id = os.environ.setdefault('YOSOI_SESSION_ID', 'eval-demo-concurrent-session')
    Agent.instrument_all()

    llm_config = LLMConfig(
        provider='groq',
        model_name='llama-3.3-70b-versatile',
        api_key='unused-test-key',
        temperature=0.0,
    )

    canned_html = (
        '<html><body><h1 class="title">demo</h1><span class="author">a</span>'
        '<span class="date">2026-01-01</span><article>x</article>'
        '<div class="related"><a>x</a></div></body></html>'
    )

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

    original_create_fetcher = _pipeline_mod.create_fetcher
    _pipeline_mod.create_fetcher = lambda *_a, **_kw: _FakeFetcher()  # type: ignore[assignment]

    pipeline = Pipeline(llm_config, contract=NewsArticle, quiet=True)

    urls = [
        'https://a.example.com/1',
        'https://b.example.com/1',
        'https://a.example.com/2',
        'https://b.example.com/2',
    ]

    inner_agent = pipeline.discovery._agent._agent
    try:
        with (
            inner_agent.override(model=TestModel()),
            propagate_attributes(tags=['yosoi', 'eval', 'regression']),
        ):
            await pipeline.process_urls(urls, workers=2, force=True, origin='script')
    finally:
        _pipeline_mod.create_fetcher = original_create_fetcher  # type: ignore[assignment]

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
