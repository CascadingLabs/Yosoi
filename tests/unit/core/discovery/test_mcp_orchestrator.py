"""Tests for MCPDiscoveryOrchestrator: SelectorMap parity, persistence, replay-first."""

import pytest
from rich.console import Console

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_agent import MCPDiscoveryDraft, MCPFieldFinding
from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator
from yosoi.models.defaults import NewsArticle
from yosoi.models.replay import LessonKey
from yosoi.models.selectors import SelectorEntry
from yosoi.prompts.mcp_discovery import mcp_discovery_instructions
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
    )


def _draft_no_root() -> MCPDiscoveryDraft:
    return MCPDiscoveryDraft(
        fields=[
            MCPFieldFinding(
                field='headline', selector=SelectorEntry(type='css', value='h1.title'), sample_value='Title'
            ),
            MCPFieldFinding(
                field='author', selector=SelectorEntry(type='css', value='span.author'), sample_value='Jane'
            ),
        ],
    )


def _draft_relative_to_root() -> MCPDiscoveryDraft:
    return MCPDiscoveryDraft(
        fields=[
            MCPFieldFinding(field='headline', selector=SelectorEntry(type='css', value='h1'), sample_value='Title'),
        ],
        root=SelectorEntry(type='css', value='article.card'),
    )


@pytest.fixture
def llm_config():
    return LLMConfig(provider='groq', model_name='test-model', api_key='test-key', temperature=0.0)


@pytest.fixture
def lesson_storage(tmp_path, mocker):
    lesson_dir = tmp_path / 'lessons'
    lesson_dir.mkdir()
    mocker.patch('yosoi.storage.lesson.get_yosoi_storage_path', return_value=lesson_dir)
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

    async def test_rejects_findings_that_do_not_replay_against_cleaned_html(self, llm_config, lesson_storage):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft_no_root()))

        result = await orch.discover_selectors('<html><body><p>No matching fields here.</p></body></html>', _URL)

        assert result is None

    async def test_replay_validation_uses_discovered_root(self, llm_config, lesson_storage):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft_relative_to_root()))
        html = '<main><h1>Wrong page title</h1><article class="card"><h1>Title</h1></article></main>'

        result = await orch.discover_selectors(html, _URL)

        assert result is not None
        key = LessonKey(
            domain=obs.normalize_user_id(_URL) or 'unknown',
            contract_signature=contract_signature(NewsArticle),
        )
        lesson = await lesson_storage.load_active(key)
        assert lesson is not None
        assert lesson.validation.sample_values['headline'] == 'Title'

    async def test_returns_none_when_all_fields_fail_validation(self, llm_config, lesson_storage, mocker):
        from yosoi.core.verification.semantic import FieldSemanticIssue

        def _always_fail(item, _rules):
            field = next(iter(item))
            return [FieldSemanticIssue(field, next(iter(item.values())), 'bad')]

        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft_no_root()))
        mocker.patch.object(orch._validator, 'validate', side_effect=_always_fail)

        result = await orch.discover_selectors('', _URL)

        assert result is None

    async def test_reextract_returns_empty_on_extractor_failure(self, llm_config, lesson_storage, mocker):
        orch = _orchestrator(llm_config, lesson_storage, _FakeAgent(_draft()))

        class _FailingExtractor:
            def __init__(self, **kwargs):
                self._kwargs = kwargs

            def extract_content_with_html(self, *args, **kwargs):
                raise RuntimeError('extractor failure')

        extractor_module = __import__('yosoi.core.extraction.extractor', fromlist=['ContentExtractor'])
        mocker.patch.object(extractor_module, 'ContentExtractor', _FailingExtractor)

        result = await orch.discover_selectors('', _URL)

        assert result is not None
        assert result['headline']['primary']['value'] == 'h1.title'


def test_mcp_prompt_requires_expression_safe_eval_js() -> None:
    instructions = mcp_discovery_instructions()

    assert 'JavaScript expression, not a statement' in instructions
    assert '(() => { const out = {}; return out; })()' in instructions
    assert 'Never send a\ntop-level `return`' in instructions
    assert 'avoid top-level `const`/`let` names' in instructions
    assert 'visible document body' in instructions
