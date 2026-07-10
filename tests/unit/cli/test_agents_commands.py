from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from yosoi.cli.main import main


def test_agents_install_pi_writes_skills_and_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))

    result = CliRunner().invoke(main, ['agents', 'install', '--target', 'pi', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['written'] == 4
    assert (tmp_path / '.pi' / 'agent' / 'skills' / 'yosoi-web-workflows' / 'SKILL.md').exists()
    assert (tmp_path / '.pi' / 'agent' / 'skills' / 'yosoi-fetch' / 'SKILL.md').exists()
    assert (tmp_path / '.pi' / 'agent' / 'skills' / 'yosoi-research-frontier' / 'SKILL.md').exists()
    extension = tmp_path / '.pi' / 'agent' / 'extensions' / 'yosoi-workflows.ts'
    assert extension.exists()
    extension_text = extension.read_text(encoding='utf-8')
    assert 'uvx yosoi' in extension_text
    assert '--concurrency 5' in extension_text
    assert 'fetchInputSummary' in extension_text
    assert 'file URLs' in extension_text
    assert 'batches ≤${run.concurrency}' in extension_text


def test_project_agent_assets_match_packaged_assets() -> None:
    root = Path(__file__).parents[3]
    assert (root / '.pi/extensions/yosoi-workflows.ts').read_text(encoding='utf-8') == (
        root / 'yosoi/agent_assets/pi/yosoi-workflows.ts'
    ).read_text(encoding='utf-8')
    assert (root / '.agents/skills/yosoi-fetch/SKILL.md').read_text(encoding='utf-8') == (
        root / 'yosoi/agent_assets/skills/yosoi-fetch/SKILL.md'
    ).read_text(encoding='utf-8')


def test_agent_alias_and_dry_run_do_not_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))

    result = CliRunner().invoke(main, ['agent', 'install', '--target', 'claude', '--dry-run', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {record['status'] for record in payload['records']} == {'would-write'}
    assert not (tmp_path / '.claude').exists()


def test_agents_install_skips_existing_without_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))

    first = CliRunner().invoke(main, ['agents', 'install', '--target', 'pi', '--json'])
    assert first.exit_code == 0, first.output
    second = CliRunner().invoke(main, ['agents', 'install', '--target', 'pi', '--json'])

    assert second.exit_code == 0, second.output
    payload = json.loads(second.output)
    assert payload['written'] == 0
    assert payload['skipped'] == 4


def test_agents_install_all_targets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))

    result = CliRunner().invoke(main, ['agents', 'install', '--target', 'all', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    targets = {record['target'] for record in payload['records']}
    assert targets == {'pi', 'agents', 'claude', 'codex', 'opencode'}
    assert (tmp_path / '.agents' / 'skills' / 'yosoi-web-workflows' / 'SKILL.md').exists()
    assert (tmp_path / '.config' / 'opencode' / 'skills' / 'yosoi-web-workflows' / 'SKILL.md').exists()
    assert (tmp_path / '.codex' / 'skills' / 'yosoi-fetch' / 'SKILL.md').exists()


def test_agents_install_project_scope_writes_project_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))

    result = CliRunner().invoke(main, ['agents', 'install', '--scope', 'project', '--target', 'pi', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['written'] == 4
    assert (tmp_path / '.agents' / 'skills' / 'yosoi-web-workflows' / 'SKILL.md').exists()
    assert (tmp_path / '.agents' / 'skills' / 'yosoi-fetch' / 'SKILL.md').exists()
    assert (tmp_path / '.agents' / 'skills' / 'yosoi-research-frontier' / 'SKILL.md').exists()
    assert (tmp_path / '.pi' / 'extensions' / 'yosoi-workflows.ts').exists()
    assert not (tmp_path / 'home' / '.pi').exists()


def test_agents_update_overwrites_existing_assets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    runner = CliRunner()
    first = runner.invoke(main, ['agents', 'install', '--target', 'agents'])
    assert first.exit_code == 0, first.output
    skill = tmp_path / '.agents' / 'skills' / 'yosoi-web-workflows' / 'SKILL.md'
    skill.write_text('old', encoding='utf-8')

    result = runner.invoke(main, ['agents', 'update', '--target', 'agents', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['type'] == 'agents.update'
    assert payload['written'] == 3
    assert 'uvx yosoi' in skill.read_text(encoding='utf-8')


def test_installed_skills_use_uvx(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    result = CliRunner().invoke(main, ['agents', 'install', '--target', 'pi'])
    assert result.exit_code == 0, result.output

    skill_paths = (tmp_path / '.pi' / 'agent' / 'skills').glob('*/SKILL.md')
    for path in skill_paths:
        text = Path(path).read_text(encoding='utf-8')
        assert 'uvx yosoi' in text
        assert 'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi' not in text
