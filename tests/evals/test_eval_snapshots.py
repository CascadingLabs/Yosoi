import json
import os
from pathlib import Path

import pytest

from yosoi.discovery import SelectorDiscovery

# Load Manifest
# Note: Path is relative to project root or absolute
PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_DATA_DIR = PROJECT_ROOT / 'tests' / 'data'
MANIFEST_PATH = TEST_DATA_DIR / 'manifest.json'


def get_snapshots():
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return list(data.items())


@pytest.mark.eval
@pytest.mark.parametrize('url, meta', get_snapshots())
def test_snapshot_evaluation(url, meta):
    """
    Slow evaluation test using real LLM.
    Compares current LLM performance against the recorded baseline.
    """
    snapshot_path = TEST_DATA_DIR / 'snapshots' / meta['filename']
    if not snapshot_path.exists():
        pytest.skip(f'Snapshot file not found: {meta["filename"]}')

    html_content = snapshot_path.read_text(encoding='utf-8')
    expected_data = meta['expected_selectors']

    # This requires a real API key
    api_key = os.getenv('GROQ_KEY') or os.getenv('GEMINI_KEY')
    if not api_key:
        pytest.skip('No API key found for evaluation')

    from yosoi.llm_config import LLMConfig

    config = LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key=api_key)
    discovery = SelectorDiscovery(llm_config=config)

    # ACT: Run real AI discovery
    new_selectors = discovery.discover_from_html(url, html_content)

    if not new_selectors:
        pytest.fail('AI failed to discover selectors for evaluation')

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'html.parser')

    # Metrics: Compare new selectors with baseline
    # 1. Headline match
    new_sel_str = new_selectors.get('headline', {}).get('primary')
    old_sel_str = expected_data.get('headline', {}).get('primary')

    # Extract text using OLD baseline selector
    old_element = soup.select_one(old_sel_str) if old_sel_str and old_sel_str != 'NA' else None
    expected_text = old_element.get_text(strip=True) if old_element else None

    # Extract text using NEW AI selector
    new_element = soup.select_one(new_sel_str) if new_sel_str and new_sel_str != 'NA' else None
    actual_text = new_element.get_text(strip=True) if new_element else None

    assert actual_text == expected_text, (
        f"New selector '{new_sel_str}' extracted different text than baseline '{old_sel_str}'"
    )

    # 2. Coverage count
    new_count = len(new_selectors)
    old_count = len(expected_data)
    assert new_count >= old_count, f'AI discovered fewer fields ({new_count}) than baseline ({old_count})'
