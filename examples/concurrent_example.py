"""Example: scripted multi-worker URL processing with auto Live display.

When workers > 1, Pipeline.process_urls() automatically shows a Rich Live
table — no extra setup required.

Reads YOSOI_MODEL (or provider-specific API keys) from your .env file.

Usage:
    uv run python examples/concurrent_example.py
"""

import asyncio

import yosoi as ys
from yosoi import Pipeline
from yosoi.utils.files import init_yosoi, is_initialized

URLS = [
    'https://news.ycombinator.com',
    'https://lobste.rs',
    'https://thenewstack.io',
]


async def main() -> None:
    if not is_initialized():
        init_yosoi()

    config = ys.auto_config()  # picks up YOSOI_MODEL / provider keys from .env

    pipeline = Pipeline(config, contract=ys.NewsArticle)

    # workers > 1 → Live progress table appears automatically
    results = await pipeline.process_urls(URLS, workers=3)

    print(f'\nDone: {len(results["successful"])} succeeded, {len(results["failed"])} failed')


if __name__ == '__main__':
    asyncio.run(main())
