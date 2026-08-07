"""CLI framing tests for the intentionally unwired QA arm."""

from __future__ import annotations

import json

from click.testing import CliRunner

from yosoi.cli.main import main


def test_qa_group_exists_and_shows_help() -> None:
    result = CliRunner().invoke(main, ['qa'])

    assert result.exit_code == 0
    assert 'Yosoi QA arm' in result.output
    assert 'status' in result.output


def test_qa_status_is_explicitly_unwired() -> None:
    result = CliRunner().invoke(main, ['qa', 'status', '--json'])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload['status'] == 'scaffolded'
    assert payload['runtime_wired'] is False
    assert payload['observations_wired'] is False
