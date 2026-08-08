"""Run one pruned static-HTML question through Gemma with native JSON output."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from urllib.request import Request, urlopen

from lxml import html
from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


class WikipediaAnswer(BaseModel):
    """The deterministic answer shape for the small static Wikipedia boss fight."""

    article_title: str = Field(description='The exact article title shown in the supplied HTML.')
    article_summary: str = Field(description='A concise summary using only the supplied HTML.')


def fetch_static_html(url: str) -> str:
    """Fetch one static HTML document without browser rendering."""
    request = Request(url, headers={'User-Agent': 'yosoi-gemma-spike/0.1'})
    with urlopen(request, timeout=60) as response:
        return response.read().decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def prune_static_html(source: str) -> str:
    """Keep one article title and its first three paragraphs from static HTML."""
    document = html.fromstring(source)
    main = document.xpath('//main')
    body = document.find('body')
    content = main[0] if main else body if body is not None else document
    pruned = html.Element('article')
    for element in content.xpath('.//h1|.//p'):
        if element.tag == 'h1' or len(pruned.xpath('.//p')) < 3:
            pruned.append(deepcopy(element))
    return html.tostring(pruned, encoding='unicode', method='html')


def build_agent(base_url: str, model_name: str, api_key: str) -> Agent[None, WikipediaAnswer]:
    """Build a native-schema agent for an OpenAI-compatible vLLM endpoint."""
    model = OpenAIChatModel(model_name, provider=OpenAIProvider(base_url=base_url, api_key=api_key))
    return Agent(
        model,
        output_type=NativeOutput(WikipediaAnswer),
        instructions=(
            'Answer only from the supplied static HTML. Do not use outside knowledge. '
            'Return the requested JSON object through the native structured-output schema.'
        ),
        retries=2,
    )


async def run(args: argparse.Namespace) -> dict[str, object]:
    """Fetch/read, prune once, and ask Gemma one structured question."""
    source = args.html.read_text(encoding='utf-8') if args.html else fetch_static_html(args.url)
    pruned = prune_static_html(source)
    answer = await build_agent(args.base_url, args.model, args.api_key).run(
        f'URL: {args.url}\n\nStatic HTML:\n{pruned}', model_settings={'temperature': 0}
    )
    return {
        'url': args.url,
        'raw_html_chars': len(source),
        'pruned_html_chars': len(pruned),
        'model': args.model,
        'base_url': args.base_url,
        'answer': answer.output.model_dump(),
    }


def main() -> None:
    """Run the single-document static HTML boss fight."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://en.wikipedia.org/wiki/Web_scraping')
    parser.add_argument('--html', type=Path, help='Use a frozen static HTML file instead of fetching --url.')
    parser.add_argument('--base-url', default=os.getenv('INFERENCE_BASE_URL', 'http://echo:8096/v1'))
    parser.add_argument('--model', default=os.getenv('MODEL_ID', 'google/gemma-4-12b-it-qat-w4a16-ct'))
    parser.add_argument('--api-key', default=os.getenv('INFERENCE_API_KEY', 'EMPTY'))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == '__main__':
    main()
