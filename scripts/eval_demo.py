"""Eval demo: ingest tagged traces into local Langfuse for visual inspection.

Documented at observability/evals-and-tagging.md. Three modes:

- ``python scripts/eval_demo.py`` — single trace via direct OTel (no Pipeline).
- ``python scripts/eval_demo.py --workers N`` — real Pipeline with N workers
  using ``pydantic-ai`` ``TestModel`` (deterministic, no LLM cost). Default N=1.
- ``python scripts/eval_demo.py --workers N --live`` — real Pipeline with real
  OpenRouter LLM calls. Requires ``OPENROUTER_KEY``; default model
  ``openrouter:openai/gpt-4o-mini``. Cost ceiling: ~$0.20/run worst case.

The legacy ``--concurrent`` flag is accepted as a deprecated alias for
``--workers 2``.

Run with the local Langfuse stack on http://localhost:3000.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace

# Local Langfuse stack defaults from docker-compose.langfuse.yml.
# Force-override (NOT setdefault) so a user's ``.env`` pointing at cloud
# Langfuse doesn't silently send the demo's traces there. The demo always
# targets the local stack — that's the whole point.
os.environ['LANGFUSE_PUBLIC_KEY'] = 'pk-lf-yosoi-local'
os.environ['LANGFUSE_SECRET_KEY'] = 'sk-lf-yosoi-local'
os.environ['LANGFUSE_HOST'] = 'http://localhost:3000'
os.environ['LANGFUSE_BASE_URL'] = 'http://localhost:3000'


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


async def _pipeline_demo(*, workers: int, live: bool) -> str:
    """Real Pipeline + N workers + 4 URLs across 2 (sub)domains.

    Stubs the fetcher (no network). The LLM is either:

    - ``TestModel`` (default, deterministic, no cost), OR
    - real OpenRouter (``--live``, default ``openrouter:openai/gpt-4o-mini``).

    Selector storage is routed through a fresh ``tempfile.mkdtemp()`` so the
    user's ``.yosoi/`` is never touched and every run sees a cold cache (no
    accidental cache-hit when re-running, which masks per-field fan-out).
    """
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from yosoi.core import pipeline as _pipeline_mod
    from yosoi.core.discovery.config import LLMConfig
    from yosoi.core.discovery.config import provider as resolve_provider
    from yosoi.core.pipeline import Pipeline
    from yosoi.models.defaults import NewsArticle
    from yosoi.models.results import ContentMetadata, FetchResult
    from yosoi.utils import observability as obs

    sess_id = os.environ.setdefault('YOSOI_SESSION_ID', 'eval-demo-pipeline-session')
    Agent.instrument_all()

    # Resolve LLM config + the override model.
    if live:
        if not os.environ.get('OPENROUTER_KEY'):
            print(
                'ERROR: --live requires OPENROUTER_KEY. Set it in the environment '
                '(or your .env) and re-run. Cost ceiling: ~$0.20 per run on the '
                'default openrouter:openai/gpt-4o-mini.',
                file=sys.stderr,
            )
            raise SystemExit(2)
        llm_config: LLMConfig = resolve_provider(os.environ.get('YOSOI_MODEL', 'openrouter:openai/gpt-4o-mini'))
        override_model: object | None = None  # real LLM — no override
        print(f'[live] Using {llm_config.provider}:{llm_config.model_name} via OpenRouter. Cost ceiling: ~$0.20.')
    else:
        llm_config = LLMConfig(
            provider='groq',
            model_name='llama-3.3-70b-versatile',
            api_key='unused-test-key',
            temperature=0.0,
        )
        override_model = TestModel()
        print(f'[deterministic] Using TestModel (no LLM cost) with workers={workers}.')

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
    cast(Any, _pipeline_mod).create_fetcher = lambda *_a, **_kw: _FakeFetcher()

    # Isolate selector storage in a tempdir so the user's .yosoi/ is never
    # touched and every run sees a cold cache (cold cache → real per-field
    # fan-out → visible LLM spans for the manual gate).
    tempdir = tempfile.mkdtemp(prefix='yosoi-eval-')
    original_cwd = Path.cwd()
    os.chdir(tempdir)
    print(f'[isolated] Selector cache at {tempdir} (rm -rf when you no longer need it).')

    try:
        pipeline = Pipeline(llm_config, contract=NewsArticle, quiet=True)

        urls = [
            'https://a.example.com/1',
            'https://b.example.com/1',
            'https://a.example.com/2',
            'https://b.example.com/2',
        ]

        inner_agent = pipeline.discovery._agent._agent
        if override_model is not None:
            with (
                inner_agent.override(model=override_model),
                propagate_attributes(tags=['yosoi', 'eval', 'regression']),
            ):
                await pipeline.process_urls(urls, workers=workers, force=True, origin='script')
        else:
            with propagate_attributes(tags=['yosoi', 'eval', 'regression']):
                await pipeline.process_urls(urls, workers=workers, force=True, origin='script')
    finally:
        cast(Any, _pipeline_mod).create_fetcher = original_create_fetcher
        os.chdir(original_cwd)

    obs.flush()
    return sess_id


def main() -> None:
    """Parse CLI args and run the chosen demo mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='Pipeline workers (omit for single-trace OTel-only demo; pass 1+ for real Pipeline mode).',
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Use real OpenRouter LLM instead of TestModel. Requires OPENROUTER_KEY. ~$0.20/run cost ceiling.',
    )
    parser.add_argument(
        '--concurrent',
        action='store_true',
        help='[deprecated] Alias for --workers 2.',
    )
    args = parser.parse_args()

    workers: int | None = args.workers
    if args.concurrent:
        if workers is not None:
            print('ERROR: --concurrent and --workers are mutually exclusive.', file=sys.stderr)
            raise SystemExit(2)
        print('WARNING: --concurrent is a deprecated alias for --workers 2. Use --workers 2.', file=sys.stderr)
        workers = 2

    pipeline_mode = workers is not None or args.live
    if pipeline_mode:
        effective_workers = workers if workers is not None else 1
        sess_id = asyncio.run(_pipeline_demo(workers=effective_workers, live=args.live))
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
