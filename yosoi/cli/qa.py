"""CLI shell for the opt-in QA arm while its runtime remains unwired."""

from __future__ import annotations

import rich_click as click

from yosoi.cli.machine import MachineReadableGroup, echo_json

_CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help'], 'show_default': True}


@click.group(cls=MachineReadableGroup, invoke_without_command=True, context_settings=_CONTEXT_SETTINGS)
@click.pass_context
def qa_group(ctx: click.Context) -> None:
    """Inspect the staged Yosoi QA arm and its indexed-observation foundation."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@qa_group.command('status')
@click.option('--json', 'json_output', is_flag=True, default=False, help='Emit machine-readable status JSON.')
def qa_status(json_output: bool) -> None:
    """Show scaffold readiness without starting a browser or provider."""
    payload = {
        'type': 'qa.status',
        'status': 'scaffolded',
        'runtime_wired': False,
        'observations_wired': False,
        'next_slice': 'static HTML artifact -> pruned view -> flat index -> bounded inspection',
        'roadmaps': ['yosoi/observations/ROADMAP.md', 'yosoi/qa/ROADMAP.md'],
    }
    if json_output:
        echo_json(payload)
        return

    click.echo('Yosoi QA arm: scaffolded; runtime not wired')
    click.echo(f'Next: {payload["next_slice"]}')
    click.echo('Roadmaps:')
    for roadmap in payload['roadmaps']:
        click.echo(f'  - {roadmap}')


__all__ = ['qa_group', 'qa_status']
