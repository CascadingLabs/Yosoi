"""Branch coverage for machine-readable CLI and cache target helpers."""

from __future__ import annotations

import json

import pytest
import rich_click as click
from click.testing import CliRunner

from yosoi.cli.cache_target import classify_cache_status_target, explicit_cache_status_target
from yosoi.cli.machine import MachineReadableCommand, MachineReadableGroup, command_doc


@pytest.mark.parametrize(
    ('raw', 'kind', 'domain', 'route'),
    [
        ('  @Article  ', 'contract', None, None),
        ('https://www.EXAMPLE.com/a/b?x=1', 'url', 'example.com', '/a/b'),
        ('/route', 'route', None, '/route'),
        ('localhost', 'domain', 'localhost', None),
        ('Example.COM', 'domain', 'example.com', None),
    ],
)
def test_classify_cache_status_target_successes(raw, kind, domain, route):
    target = classify_cache_status_target(raw)
    assert target.kind == kind
    assert target.domain == domain
    assert target.route == route


@pytest.mark.parametrize(
    ('raw', 'message'),
    [
        ('   ', 'cannot be empty'),
        ('@', 'must include'),
        ('ftp://example.com', 'Unsupported URL scheme'),
        ('http:///missing-host', 'must include a host'),
        ('//example.com/path', 'Ambiguous schemeless URL'),
        ('not a domain', 'Ambiguous cache status target'),
    ],
)
def test_classify_cache_status_target_errors(raw, message):
    with pytest.raises(ValueError, match=message):
        classify_cache_status_target(raw)


def test_explicit_cache_status_target_successes_and_errors():
    assert explicit_cache_status_target(None, None, None) is None
    assert explicit_cache_status_target('WWW.Example.COM', None, None).domain == 'example.com'
    assert explicit_cache_status_target(None, 'https://example.com/p', None).route == '/p'
    assert explicit_cache_status_target(None, None, '/r').kind == 'route'

    with pytest.raises(ValueError, match='Use only one explicit'):
        explicit_cache_status_target('example.com', 'https://example.com', None)
    with pytest.raises(ValueError, match='Invalid --domain'):
        explicit_cache_status_target('/bad', None, None)
    with pytest.raises(ValueError, match='URLs must include'):
        explicit_cache_status_target(None, 'example.com', None)
    with pytest.raises(ValueError, match='routes must begin'):
        explicit_cache_status_target(None, None, 'route')


def test_command_doc_covers_arguments_choices_and_jsonable_defaults():
    @click.command(cls=MachineReadableCommand)
    @click.argument('name')
    @click.option('--choice', type=click.Choice(['a', 'b']), default='a')
    @click.option('--many', multiple=True, default=('x', 'y'))
    def cmd(name: str, choice: str, many: tuple[str, ...]) -> None:
        pass

    with click.Context(cmd, info_name='cmd') as ctx:
        doc = command_doc(cmd, ctx)

    assert doc['arguments'][0]['name'] == 'name'
    choice = next(opt for opt in doc['options'] if opt['name'] == 'choice')
    many = next(opt for opt in doc['options'] if opt['name'] == 'many')
    assert choice['choices'] == ['a', 'b']
    assert many['default'] == ['x', 'y']


def test_machine_readable_command_json_error_and_help_paths():
    @click.group(cls=MachineReadableGroup)
    def cli() -> None:
        pass

    @cli.command(cls=MachineReadableCommand)
    @click.option('--fail', is_flag=True)
    @click.option('--json', 'json_output', is_flag=True)
    def child(fail: bool, json_output: bool) -> None:
        _ = json_output
        if fail:
            raise click.ClickException('boom')
        click.echo('ok')

    runner = CliRunner()
    help_result = runner.invoke(cli, ['--help', '--json'])
    assert help_result.exit_code == 0
    assert json.loads(help_result.output)['type'] == 'help'

    child_help = runner.invoke(cli, ['child', '--help', '--json'])
    assert child_help.exit_code == 0
    assert json.loads(child_help.output)['command_path'].endswith('child')

    error = runner.invoke(cli, ['child', '--fail', '--json'])
    assert error.exit_code == 1
    assert json.loads(error.output)['message'] == 'boom'

    with pytest.raises(click.ClickException):
        cli.main(args=['child', '--fail', '--json'], standalone_mode=False)
