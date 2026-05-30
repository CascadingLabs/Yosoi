"""Tests for MCPDiscoveryOrchestrator: SelectorMap parity, persistence, replay-first."""

import pytest
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_agent import MCPDiscoveryDraft, MCPFieldFinding
from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator
from yosoi.models.defaults import NewsArticle
from yosoi.models.replay import ActKind, LessonKey, ReplayAct, ReplayNode, ReplayPlan
from yosoi.models.selectors import SelectorEntry
from yosoi.storage.lesson import LessonStorage
from yosoi.utils import observability as obs
from yosoi.utils.signatures import contract_signature

_URL = 'https://news.example.com/article'


class _FakeAgent:
    """Stand-in for MCPDiscoveryAgent — returns a canned draft and counts calls."""

    def __init__(self, draft: MCPDiscoveryDraft):
        self._draft = draft
        self.calls = 0

    async def discover(self, url, fields, field_rules):
        self.calls += 1
        return self._draft


def _draft() -> MCPDiscoveryDraft:
    return MCPDiscoveryDraft(
        fields=[
            MCPFieldFinding(
                field='headline', selector=SelectorEntry(type='css', value='h1.title'), sample_value='Title'
            ),
            MCPFieldFinding(
                field='author', selector=SelectorEntry(type='css', value='span.author'), sample_value='Jane'
            ),
        ],
        root=SelectorEntry(type='css', value='article.card'),
        replay_plan=ReplayPlan(
            nodes=[
                ReplayNode(
                    id='nav',
                    intent='open article',
                    act=ReplayAct(kind=ActKind.NAVIGATE, url=_URL),
                )
            ]
        ),
    )


@pytest.fixture
def llm_config():
    return LLMConfig(provider='groq', model_name='test-model', api_key='test-key', temperature=0.0)


@pytest.fixture
def lesson_storage(tmp_path, mocker):
    lesson_dir = tmp_path / 'lessons'
    lesson_dir.mkdir()
    mocker.patch('yosoi.storage.lesson.init_yosoi', return_value=lesson_dir)
    return LessonStorage()


def _orchestrator(llm_config, lesson_storage, agent):
    return MCPDiscoveryOrchestrator(
        contract=NewsArticle,
        llm_config=llm_config,
        console=Console(quiet=True),
        lesson_storage=lesson_storage,
        agent=agent,
    )


class TestSelectorMapParity:
    async def test_returns_static_shaped_map(self, llm_config, lesson_storage):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft()))

        result = await orch.discover_selectors('', _URL)

        assert result is not None
        assert result['headline'] == {'primary': {'type': 'css', 'value': 'h1.title'}}
        assert result['author'] == {'primary': {'type': 'css', 'value': 'span.author'}}
        assert result['root'] == {'primary': {'type': 'css', 'value': 'article.card'}}

    async def test_persists_lesson(self, llm_config, lesson_storage):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft()))

        await orch.discover_selectors('', _URL)

        key = LessonKey(
            domain=obs.normalize_user_id(_URL) or 'unknown',
            contract_signature=contract_signature(NewsArticle),
        )
        lesson = await lesson_storage.load_active(key)
        assert lesson is not None
        assert lesson.selectors['headline'].primary == {'type': 'css', 'value': 'h1.title'}
        assert lesson.validation.sample_values == {'headline': 'Title', 'author': 'Jane'}
        assert not lesson.replay_plan.is_empty

    async def test_returns_none_when_no_url(self, llm_config, lesson_storage):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft()))

        assert await orch.discover_selectors('', None) is None


class TestReplayFirst:
    async def test_second_run_replays_without_llm(self, llm_config, lesson_storage):
        agent = _FakeAgent(_draft())
        orch = _orchestrator(llm_config, lesson_storage, agent)

        first = await orch.discover_selectors('', _URL)
        second = await orch.discover_selectors('', _URL)

        assert agent.calls == 1  # second run hit the cached lesson
        assert second is not None
        assert second['headline'] == first['headline']

    async def test_force_bypasses_cache(self, llm_config, lesson_storage):
        agent = _FakeAgent(_draft())
        orch = _orchestrator(llm_config, lesson_storage, agent)

        await orch.discover_selectors('', _URL)
        await orch.discover_selectors('', _URL, force=True)

        assert agent.calls == 2


class TestValidationGate:
    async def test_rejects_findings_that_fail_validation(self, llm_config, lesson_storage, mocker):
        from yosoi.core.verification.semantic import FieldSemanticIssue

        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft()))

        # Reject only the 'author' value; headline passes.
        def fake_validate(item, rules):
            field = next(iter(item))
            if field == 'author':
                return [FieldSemanticIssue('author', 'Jane', 'looked wrong')]
            return []

        mocker.patch.object(orch._validator, 'validate', side_effect=fake_validate)

        result = await orch.discover_selectors('', _URL)

        assert 'headline' in result
        assert 'author' not in result
        assert 'root' in result  # root is structural, not value-validated
