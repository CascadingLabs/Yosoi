import json
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from yosoi.core.discovery import SelectorDiscovery
from yosoi.core.verification import SelectorVerifier
from yosoi.models.defaults import NewsArticle

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
    """Fast health check using TestModel and manifest data."""
    snapshot_path = TEST_DATA_DIR / 'snapshots' / meta['filename']
    if not snapshot_path.exists():
        pytest.skip(f'Snapshot file not found: {meta["filename"]}')

    html_content = snapshot_path.read_text(encoding='utf-8')
    expected_data = meta['expected_selectors']
    SelectorModel = NewsArticle.to_selector_model()
    SelectorModel(**expected_data)

    agent = Agent(
        TestModel(custom_output_args=expected_data),
        output_type=SelectorModel,
    )

    discovery = SelectorDiscovery(agent=agent, contract=NewsArticle)
    result = discovery.discover_selectors(html_content, url)

    assert result == expected_data

    verifier = SelectorVerifier()
    verification = verifier.verify(html_content, result)

    assert verification is not None
    assert verification.verified_count > 0, 'No selectors verified on original snapshot'
