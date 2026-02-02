import json
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from yosoi.discovery import SelectorDiscovery
from yosoi.models import ScrapingConfig
from yosoi.validator import SelectorValidator

# Load Manifest
TEST_DATA_DIR = Path(__file__).parent.parent / 'data'
MANIFEST_PATH = TEST_DATA_DIR / 'manifest.json'


def get_snapshots():
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return list(data.items())


@pytest.mark.parametrize('url, meta', get_snapshots())
def test_snapshot_health_check(url, meta):
    """
    Fast health check using TestModel and manifest data.
    Verifies extraction logic and validator against the snapshot HTML.
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
    result = discovery.discover_from_html(url, html_content)

    # Verify discovery output matches snapshot baseline
    assert result == expected_data

    # Verify validator logic on this snapshot
    validator = SelectorValidator()
    validated = validator.validate_selectors_with_html(url, html_content, result)

    # We expect that the baseline selectors should still work on the snapshot they were recorded from
    assert len(validated) > 0, 'No selectors validated on original snapshot'
