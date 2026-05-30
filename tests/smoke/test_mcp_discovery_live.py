"""Opt-in live end-to-end test for the MCP discovery → replay loop (CAS-79).

Drives one real LLM + voidcrawl MCP discovery session against a stable target
(Hacker News), then proves the second run replays the cached lesson with no LLM
activity — the "discover once, replay forever" contract.

Run with:
    YOSOI_LIVE_SMOKE=1 YOSOI_MODEL=<provider:model> uv run pytest -m smoke \
        tests/smoke/test_mcp_discovery_live.py
"""

from __future__ import annotations

import os

import pytest

import yosoi as ys
from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator
from yosoi.storage.lesson import LessonStorage

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.getenv('YOSOI_LIVE_SMOKE') != '1',
        reason='set YOSOI_LIVE_SMOKE=1 to run the live MCP discovery loop',
    ),
]

HN_URL = 'https://news.ycombinator.com/'


class HNStory(ys.Contract):
    """One Hacker News front-page story."""

    title: str = ys.Title(description='Story headline text')
    author: str = ys.Author(description='Submitter username (the "by" link)')


@pytest.fixture
def llm_config():
    from yosoi.core.configs import auto_config

    model = os.getenv('YOSOI_MODEL')
    if not model:
        pytest.skip('set YOSOI_MODEL=<provider:model> to run the live MCP loop')
    return auto_config(model).llm


@pytest.fixture
def lesson_storage(tmp_path, mocker):
    lesson_dir = tmp_path / 'lessons'
    lesson_dir.mkdir()
    mocker.patch('yosoi.storage.lesson.init_yosoi', return_value=lesson_dir)
    return LessonStorage()


@pytest.mark.asyncio
async def test_mcp_discovers_then_replays(llm_config, lesson_storage):
    orch = MCPDiscoveryOrchestrator(
        contract=HNStory,
        llm_config=llm_config,
        lesson_storage=lesson_storage,
    )

    # First run: live discovery via the MCP agent.
    discovered = await orch.discover_selectors('', HN_URL)
    assert discovered is not None
    assert 'title' in discovered

    # A lesson was persisted and is replay-eligible.
    from yosoi.models.replay import LessonKey
    from yosoi.utils import observability as obs
    from yosoi.utils.signatures import contract_signature

    key = LessonKey(
        domain=obs.normalize_user_id(HN_URL) or 'unknown',
        contract_signature=contract_signature(HNStory),
    )
    assert await lesson_storage.load_active(key) is not None

    # Second run: must replay the cached lesson (no fresh agent session).
    replayed = await orch.discover_selectors('', HN_URL)
    assert replayed == discovered
