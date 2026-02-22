import json
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from yosoi.discovery import SelectorDiscovery
from yosoi.models import ScrapingConfig
from yosoi.verifier import SelectorVerifier

# Load Manifest
TEST_DATA_DIR = Path(__file__).parent.parent / 'data'
MANIFEST_PATH = TEST_DATA_DIR / 'manifest.json'


def get_snapshots():
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return list(data.items())


@pytest.mark.parametrize(('url', 'meta'), get_snapshots())
def test_snapshot_health_check(url, meta):
    """
    Fast health check using TestModel and manifest data.
    Verifies extraction logic and verification against the snapshot HTML.
    """
    snapshot_path = TEST_DATA_DIR / 'snapshots' / meta['filename']
    if not snapshot_path.exists():
        pytest.skip(f'Snapshot file not found: {meta["filename"]}')

    html_content = snapshot_path.read_text(encoding='utf-8')
    expected_data = meta['expected_selectors']
    ScrapingConfig(**expected_data)

    # Mock Agent with TestModel
    # This ensures that ScrapingConfig is actually used and validated by Pydantic AI

    agent = Agent(
        TestModel(custom_output_args=expected_data),
        output_type=ScrapingConfig,
    )

    discovery = SelectorDiscovery(agent=agent)
    # Updated: use discover_selectors instead of discover_from_html
    # Note: discover_selectors expects (html, url) not (url, html)
    result = discovery.discover_selectors(html_content, url)

    # Verify discovery output matches snapshot baseline
    assert result == expected_data

    # Verify verifier logic on this snapshot
    verifier = SelectorVerifier()
    verified = verifier.verify_selectors_with_html(url, html_content, result)

    # We expect that the baseline selectors should still work on the snapshot they were recorded from
    assert verified is not None
    assert len(verified) > 0, 'No selectors verified on original snapshot'
