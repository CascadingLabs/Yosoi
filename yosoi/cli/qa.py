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
        'status': 'index_surface_ready',
        'runtime_wired': False,
        'index_surface_wired': True,
        'capture_wired': False,
        'observations_wired': True,
        'provider_wired': False,
        'model_safe_only': True,
        'mcp_injected_session_required': True,
        'mcp_launcher': 'yosoi-qa-index-mcp',
        'next_slice': 'existing capture -> snapshot/index session injection',
        'roadmaps': ['yosoi/observations/ROADMAP.md', 'yosoi/qa/ROADMAP.md'],
    }
    if json_output:
        echo_json(payload)
        return

    click.echo('Yosoi QA arm: typed index surface ready; capture/provider wiring absent')
    click.echo(f'Launcher: {payload["mcp_launcher"]} (fail-closed without injected evidence)')
    click.echo(f'Next: {payload["next_slice"]}')
    click.echo('Roadmaps:')
    for roadmap in payload['roadmaps']:
        click.echo(f'  - {roadmap}')


@qa_group.command('mcp')
def qa_mcp() -> None:
    """Launch the read-only QA-index MCP transport (unwired by default)."""
    from yosoi.integrations.qa_index_mcp import main

    main()


__all__ = ['qa_group', 'qa_mcp', 'qa_status']
