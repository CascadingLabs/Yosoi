"""Pipeline ``discovery_mode`` flag — picks the right orchestrator at init.

Validates the integration point: ``Pipeline(..., discovery_mode='static')``
constructs a ``DiscoveryOrchestrator``; ``discovery_mode='mcp'`` constructs
an ``MCPDiscoveryOrchestrator``. Both attach to ``self.discovery`` so the
rest of the Pipeline (verify → extract → save) is mode-agnostic.

We don't run discovery here — that requires a live LLM + OpenCode server.
The mocked orchestrator tests in ``test_mcp_orchestrator.py`` cover output
shape parity.
"""

from __future__ import annotations

import pytest

import yosoi as ys
from yosoi.core.discovery.config import LLMConfig
from yosoi.core.discovery.mcp_orchestrator import MCPDiscoveryOrchestrator
from yosoi.core.discovery.orchestrator import DiscoveryOrchestrator
from yosoi.core.pipeline import Pipeline


class _Contract(ys.Contract):
    title: str = ys.Title()


def _opencode_cfg() -> LLMConfig:
    return LLMConfig(
        provider='opencode',
        model_name='gpt-5.4-mini',
        api_key=None,
        extra_params={'provider_id': 'openrouter', 'model_id': 'openai/gpt-5.4-mini'},
    )


def _openrouter_cfg() -> LLMConfig:
    return LLMConfig(provider='openrouter', model_name='openai/gpt-5.4-mini', api_key='fake')


def test_default_mode_attaches_static_orchestrator(mocker, tmp_path) -> None:
    """``discovery_mode`` defaults to 'static' — the existing path. No behavioural
    change for anyone who doesn't opt in."""
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=tmp_path / 'sel')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 't.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'l.log'))
    mocker.patch('yosoi.core.discovery.field_agent.create_model')
    mocker.patch('yosoi.core.discovery.field_agent.Agent')

    p = Pipeline(_openrouter_cfg(), contract=_Contract)
    assert isinstance(p.discovery, DiscoveryOrchestrator)
    assert p._discovery_mode == 'static'


def test_mcp_mode_attaches_mcp_orchestrator(mocker, tmp_path) -> None:
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=tmp_path / 'sel')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 't.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'l.log'))
    mocker.patch('yosoi.integrations.opencode.OpenCodeModel')
    mocker.patch('yosoi.core.discovery.mcp_orchestrator.Agent')

    p = Pipeline(_opencode_cfg(), contract=_Contract, discovery_mode='mcp')
    assert isinstance(p.discovery, MCPDiscoveryOrchestrator)
    assert p._discovery_mode == 'mcp'


def test_mcp_mode_with_non_opencode_config_fails_loudly(mocker, tmp_path) -> None:
    """MCP mode strictly requires an OpenCode-shaped LLMConfig — the voidcrawl
    MCP tooling is wired through OC. Mismatched configs should fail at Pipeline
    construction, not silently degrade."""
    mocker.patch('yosoi.storage.persistence.init_yosoi', return_value=tmp_path / 'sel')
    mocker.patch('yosoi.storage.tracking.get_tracking_path', return_value=tmp_path / 't.json')
    mocker.patch('yosoi.utils.files.is_initialized', return_value=True)
    mocker.patch('yosoi.utils.logging.setup_local_logging', return_value=str(tmp_path / 'l.log'))

    with pytest.raises(ValueError, match='requires an OpenCode-shaped'):
        Pipeline(_openrouter_cfg(), contract=_Contract, discovery_mode='mcp')
