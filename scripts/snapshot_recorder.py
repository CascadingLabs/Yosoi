import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Ensure we can import from src
sys.path.append(str(Path(__file__).parent.parent / 'src'))

from rich.console import Console

from yosoi.discovery import SelectorDiscovery
from yosoi.fetcher import create_fetcher
from yosoi.llm_config import LLMConfig

CONSOLE = Console()
TEST_DATA_DIR = Path(__file__).parent.parent / 'tests' / 'data'
SNAPSHOTS_DIR = TEST_DATA_DIR / 'snapshots'
MANIFEST_PATH = TEST_DATA_DIR / 'manifest.json'


def ensure_dirs():
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, 'w') as f:
            json.dump({}, f)


def record_snapshot(url: str, provider: str = 'groq', model_name: str = 'llama-3.3-70b-versatile', api_key: str = None):
    if not api_key:
        api_key = os.getenv('GROQ_KEY') or os.getenv('GEMINI_KEY') or os.getenv('OPENAI_KEY')

    if not api_key:
        CONSOLE.print(
            '[bold red]Error: No API key found. Set GROQ_KEY, GEMINI_KEY, or OPENAI_KEY environment variable.[/bold red]'
        )
        return

    ensure_dirs()

    # 1. Fetch Real HTML
    CONSOLE.print(f'[bold blue]Fetching {url}...[/bold blue]')
    fetcher = create_fetcher('smart')
    result = fetcher.fetch(url)

    if not result.success:
        CONSOLE.print(f'[bold red]Failed to fetch {url}: {result.block_reason}[/bold red]')
        return

    # 2. Generate Filename
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '').replace('.', '_')
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    filename = f'{domain}_{url_hash}.html'
    filepath = SNAPSHOTS_DIR / filename

    # 3. Save Raw HTML
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(result.html)
    CONSOLE.print(f'[green]✓ Saved HTML to {filename}[/green]')

    # 4. Run AI to generate 'Ground Truth' selectors
    CONSOLE.print(f'[bold purple]Running AI ({provider}/{model_name}) to generate baseline selectors...[/bold purple]')

    config = LLMConfig(provider=provider, model_name=model_name, api_key=api_key)

    discovery = SelectorDiscovery(llm_config=config)
    selectors = discovery.discover_from_html(url, result.html)

    if not selectors:
        CONSOLE.print('[bold red]AI failed to find selectors. Snapshot aborted.[/bold red]')
        return

    # 5. Update Manifest
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    manifest[url] = {
        'filename': filename,
        'domain': domain,
        'expected_selectors': selectors,
        'recorded_at': str(Path(filepath).stat().st_mtime),
    }

    with open(MANIFEST_PATH, 'w') as f:
        json.dump(manifest, f, indent=2)

    CONSOLE.print(f'[bold green]✓ Snapshot recorded for {url}[/bold green]')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Record a snapshot and baseline selectors for a URL.')
    parser.add_argument('url', help='URL to snapshot')
    parser.add_argument('--provider', default='groq', help='LLM provider (default: groq)')
    parser.add_argument('--model', default='llama-3.3-70b-versatile', help='LLM model name')
    parser.add_argument('--key', help='API Key (optional if env var set)')

    args = parser.parse_args()
    record_snapshot(args.url, provider=args.provider, model_name=args.model, api_key=args.key)
