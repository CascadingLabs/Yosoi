"""CLI framing tests for the read-only QA index surface."""

from __future__ import annotations

import json

from click.testing import CliRunner

from yosoi.cli.main import main


def test_qa_group_exists_and_shows_help() -> None:
    result = CliRunner().invoke(main, ['qa'])

    assert result.exit_code == 0
    assert 'Yosoi QA arm' in result.output
    assert 'status' in result.output
    assert 'mcp' in result.output


def test_qa_status_distinguishes_the_ready_index_from_unwired_capture_and_provider() -> None:
    result = CliRunner().invoke(main, ['qa', 'status', '--json'])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload['status'] == 'index_surface_ready'
    assert payload['runtime_wired'] is False
    assert payload['observations_wired'] is True
    assert payload['capture_wired'] is False
    assert payload['provider_wired'] is False
    assert payload['model_safe_only'] is True
    assert payload['mcp_injected_session_required'] is True


def test_qa_mcp_command_delegates_to_the_shared_launcher(monkeypatch) -> None:
    launched: list[bool] = []
    monkeypatch.setattr('yosoi.integrations.qa_index_mcp.main', lambda: launched.append(True))

    result = CliRunner().invoke(main, ['qa', 'mcp'])

    assert result.exit_code == 0, result.output
    assert launched == [True]
