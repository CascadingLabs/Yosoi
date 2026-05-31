"""JS orchestrator coverage via pydantic-ai TestModel — no live LLM needed.

Uses the same Agent.override(model=TestModel()) pattern established in
test_pipeline_observability.py to exercise the real JsDiscoveryOrchestrator
constructor and discovery loop with deterministic, zero-cost responses.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel
from pytest_mock import MockerFixture

from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.js_orchestrator import JsDiscoveryOrchestrator
from yosoi.storage.js_scripts import JsScriptStorage

# ---------------------------------------------------------------------------
# Shared fake DOM objects
# ---------------------------------------------------------------------------

_DOM_CONTEXT: dict[str, Any] = {
    'script_srcs': ['https://cdn.example.com/app.js'],
    'iframe_srcs': [],
    'window_keys': ['__appState'],
    'cookie_names': ['session'],
    'meta_names': ['description'],
}


class _PreProbeTab:
    """Fake browser tab: returns a real DOM context on first eval, then per-call results."""

    def __init__(self, *, verify_results: list[Any] | None = None) -> None:
        self._calls: list[str] = []
        self._verify_results: list[Any] = verify_results or ['extracted-value']

    async def eval_js(self, script: str) -> Any:
        self._calls.append(script)
        if len(self._calls) == 1:
            # First call is always _pre_probe — return DOM context dict
            return _DOM_CONTEXT
        # Subsequent calls are script verifications
        idx = len(self._calls) - 2  # 0-based after pre_probe
        if idx < len(self._verify_results):
            return self._verify_results[idx]
        return 'fallback-value'

    async def content(self) -> str:
        return '<main><h1>Test</h1></main>'


class _BrowseableFetcher:
    """Fake fetcher with browse() context manager yielding _PreProbeTab."""

    supports_browse = True

    def __init__(self, *, verify_results: list[Any] | None = None) -> None:
        self._verify_results = verify_results

    async def __aenter__(self) -> _BrowseableFetcher:
        return self

    async def __aexit__(self, *_: Any) -> None:
        pass

    @asynccontextmanager
    async def browse(self, url: str):
        yield _PreProbeTab(verify_results=self._verify_results)


@pytest.fixture
def llm_cfg() -> LLMConfig:
    """Real LLMConfig with a fake key — create_model() succeeds, TestModel swaps it."""
    return LLMConfig(
        provider='groq',
        model_name='llama-3.3-70b-versatile',
        api_key='test-key',
        temperature=0.0,
    )


@pytest.fixture
def mock_storage(mocker: MockerFixture):
    storage = mocker.MagicMock(spec=JsScriptStorage)
    storage.save_entries = mocker.AsyncMock(return_value=None)
    storage.get_scripts = mocker.AsyncMock(return_value={})
    return storage


# ---------------------------------------------------------------------------
# Track 2 tests — cover lines 80-87, 120, 143, 205, 227-228, 230-237
# ---------------------------------------------------------------------------


def test_constructor_instantiates_real_agent(llm_cfg, mock_storage):
    """JsDiscoveryOrchestrator.__init__ creates a real pydantic-ai Agent (lines 80-87)."""
    from pydantic_ai import Agent

    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage)

    assert isinstance(orch._agent, Agent)
    assert orch.model_name == llm_cfg.model_name
    assert orch._max_attempts == 3


async def test_discover_empty_fields_returns_immediately(mocker: MockerFixture, llm_cfg, mock_storage):
    """discover() with empty fields dict returns {} without opening a tab (line 120)."""
    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage)
    fetcher = mocker.MagicMock()  # browse() should never be called

    with orch._agent.override(model=TestModel()):
        result = await orch.discover(
            url='https://example.com',
            domain='example.com',
            fields={},
            fetcher=fetcher,
        )

    assert result == {}
    fetcher.browse.assert_not_called()


async def test_discover_logs_failure_when_llm_returns_nothing(mocker: MockerFixture, llm_cfg, mock_storage):
    """When all LLM attempts return empty string, discover() logs the failure (line 143)."""
    from rich.console import Console

    console = mocker.MagicMock(spec=Console)
    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage, console=console)
    fetcher = _BrowseableFetcher()

    # TestModel with empty text_response → _call_llm returns None → _VerificationFailed
    with orch._agent.override(model=TestModel(custom_output_text='')):
        result = await orch.discover(
            url='https://example.com',
            domain='example.com',
            fields={'signals': 'Detect third-party widgets'},
            fetcher=fetcher,
        )

    assert result == {}
    # Verify the failure console print was called (line 143)
    printed_args = [str(c) for c in console.print.call_args_list]
    assert any('no valid script' in arg or 'signals' in arg for arg in printed_args)


async def test_discover_strips_code_fences_from_llm_output(llm_cfg, mock_storage):
    """_call_llm strips ```js...``` code fences before using the script (lines 227-228)."""
    fenced_script = '```js\n(() => document.title)()\n```'
    expected_script = '(() => document.title)()'

    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage)
    # Tab verifies the stripped (fence-free) script
    fetcher = _BrowseableFetcher(verify_results=['My Page Title'])

    with orch._agent.override(model=TestModel(custom_output_text=fenced_script)):
        result = await orch.discover(
            url='https://example.com',
            domain='example.com',
            fields={'title': 'Page title'},
            fetcher=fetcher,
        )

    # Discovery succeeds — the fenced script was stripped and verified
    assert 'title' in result
    assert result['title'] == expected_script


async def test_call_llm_returns_none_on_agent_exception(mocker: MockerFixture, llm_cfg, mock_storage):
    """_call_llm catches agent exceptions and returns None (lines 230-237)."""
    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage)

    # Force _agent.run to raise to exercise the exception path in _call_llm
    with orch._agent.override(model=TestModel()):
        orch._agent.run = mocker.AsyncMock(side_effect=RuntimeError('LLM API error'))

        result = await orch._call_llm(
            deps=_make_deps('signals'),
            field_name='signals',
            attempt=1,
        )

    assert result is None


async def test_discover_field_returns_none_when_script_empty(llm_cfg, mock_storage):
    """_discover_field raises _VerificationFailed when script is empty/None (line 205)."""
    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage, max_attempts=1)
    tab = _PreProbeTab()

    with orch._agent.override(model=TestModel(custom_output_text='')):
        result = await orch._discover_field(
            tab=tab,
            field_name='signals',
            description='Tech detection',
            dom_context=_DOM_CONTEXT,
        )

    assert result is None


async def test_discover_caches_verified_scripts(llm_cfg, mock_storage):
    """discover() persists verified scripts to storage when discovery succeeds."""
    orch = JsDiscoveryOrchestrator(llm_config=llm_cfg, storage=mock_storage)
    fetcher = _BrowseableFetcher(verify_results=['CRM-value', 'chat-value'])
    script = '(() => window.__crm__)()'

    with orch._agent.override(model=TestModel(custom_output_text=script)):
        result = await orch.discover(
            url='https://example.com',
            domain='example.com',
            fields={'crm': 'CRM vendor', 'chat': 'Chat widget'},
            fetcher=fetcher,
        )

    assert 'crm' in result
    mock_storage.save_entries.assert_called_once()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_deps(field_name: str) -> Any:
    from yosoi.prompts.js_discovery import JsDiscoveryDeps

    return JsDiscoveryDeps(
        field_name=field_name,
        field_description='Test field',
        dom_context=_DOM_CONTEXT,
    )
