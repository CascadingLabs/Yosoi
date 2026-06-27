"""LLM config setup and CLI configuration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal, cast

import rich_click as click
from pydantic import ValidationError

from yosoi.cli.utils import console

if TYPE_CHECKING:
    from yosoi.core.configs import YosoiConfig
    from yosoi.models.selectors import SelectorLevel
    from yosoi.policy import Policy

FetcherName = Literal['auto', 'simple', 'headless', 'headful', 'waterfall']


def _resolve_spec_for_cli(policy: Policy, model_arg: str | None):
    try:
        return policy.resolve_run_spec()
    except ValueError as e:
        if model_arg or 'No model specified and no API key found' not in str(e):
            raise
        return None


def build_policy(
    model_arg: str | None,
    debug: bool,
    *,
    force: bool = False,
    skip_verification: bool = False,
    fetcher_type: str = 'auto',
    selector_level: SelectorLevel | None = None,
    output_formats: Sequence[str] = (),
    quiet: bool = True,
    json_output: bool = False,
    max_concurrency: int | None = None,
    flat_files: bool = False,
    atom_reads: bool = False,
    policy_sources: Sequence[str] = (),
) -> Policy:
    """Build the CLI call-site policy layer and cascade it with env/global/project policy files."""
    from dotenv import load_dotenv

    from yosoi.policy import ModelPolicy, OutputPolicy, Policy, ScrapePolicy
    from yosoi.policy.files import discover_policy_files, load_policy_layers

    load_dotenv()
    try:
        # Only set fields that differ from the defaults, so the env layer
        # (YOSOI_MODEL / YOSOI_FORCE / YOSOI_FETCHER_TYPE / ...) is not clobbered
        # by CLI flags the user never passed.
        call_kwargs: dict[str, object] = {}
        if model_arg:
            call_kwargs['model'] = ModelPolicy.from_string(model_arg)
        if atom_reads:
            call_kwargs['atom_reads'] = True
        scrape_defaults = ScrapePolicy()
        scrape_payload: dict[str, object] = {}
        if force:
            scrape_payload['force'] = True
        if skip_verification:
            scrape_payload['skip_verification'] = True
        if fetcher_type != scrape_defaults.fetcher_type:
            scrape_payload['fetcher_type'] = cast(FetcherName, fetcher_type)
        if selector_level is not None and selector_level != scrape_defaults.selector_level:
            scrape_payload['selector_level'] = selector_level
        if max_concurrency is not None:
            scrape_payload['max_concurrency'] = max_concurrency
        if scrape_payload:
            call_kwargs['scrape'] = ScrapePolicy.model_validate(scrape_payload)
        call_kwargs['output'] = OutputPolicy(
            formats=tuple(output_formats),
            quiet=quiet,
            json_output=json_output,
            debug_html=debug,
            flat_files=flat_files,
        )
        call_policy = Policy.model_validate(call_kwargs)
        file_policy = load_policy_layers(policy_sources) if policy_sources or discover_policy_files() else None
        policy = Policy.cascade(Policy.from_env(), file_policy, call_policy)
        spec = _resolve_spec_for_cli(policy, model_arg)
    except (KeyError, ValueError, ValidationError) as e:
        raise click.ClickException(str(e)) from e
    if spec is not None and not quiet and not json_output:
        console.print(
            f'[bold]Using[/bold] [green]{spec.llm_config.provider}[/green] / [cyan]{spec.llm_config.model_name}[/cyan]'
        )
    elif spec is None and not quiet and not json_output:
        console.print(
            '[cyan]ℹ Model:[/cyan] [dim]not configured; cache/atom reads can run, discovery will require one[/dim]'
        )
    return policy


def build_yosoi_config(model_arg: str | None, debug: bool) -> YosoiConfig:
    """Build a legacy YosoiConfig from CLI args.

    Thin CLI wrapper around :func:`yosoi.core.configs.auto_config`.

    Args:
        model_arg: Model string in ``provider:model-name`` format, or None.
        debug: Whether to enable debug HTML saving.

    Returns:
        Validated YosoiConfig.

    Raises:
        click.ClickException: On configuration errors.
    """
    from yosoi.core.configs import auto_config

    try:
        yosoi_config = auto_config(model=model_arg, debug=debug)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    console.print(
        f'[bold]Using[/bold] [green]{yosoi_config.llm.provider}[/green] / [cyan]{yosoi_config.llm.model_name}[/cyan]'
    )
    return yosoi_config


def print_fetcher_info(fetcher_type: str) -> None:
    """Print information about the selected fetcher."""
    _FETCHER_LABELS: dict[str, tuple[str, str]] = {
        'auto': ('Auto fetcher', 'Simple -> Headless -> Headful as needed'),
        'simple': ('Simple fetcher', 'fast, works for most sites'),
        'waterfall': ('Auto fetcher', 'Simple -> Headless -> Headful as needed'),
        'headless': ('Headless fetcher', 'headless Chrome via VoidCrawl'),
        'headful': ('Headful fetcher', 'headful Chrome via VoidCrawl'),
    }
    label, hint = _FETCHER_LABELS.get(fetcher_type, (f'{fetcher_type} fetcher', ''))
    console.print(f'[cyan]ℹ Using {label}[/cyan] [dim]({hint})[/dim]')
    if fetcher_type in {'auto', 'waterfall', 'headless', 'headful'}:
        console.print('[cyan]ℹ A3Node cache:[/cyan] [dim]disabled by default; browser DOMLoader runs fresh[/dim]')
