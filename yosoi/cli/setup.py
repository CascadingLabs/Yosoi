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
) -> Policy:
    """Build the CLI call-site policy layer and cascade it with env."""
    from dotenv import load_dotenv

    from yosoi.policy import ModelPolicy, OutputPolicy, Policy, ScrapePolicy

    load_dotenv()
    try:
        model_policy = ModelPolicy.from_string(model_arg) if model_arg else None
        scrape_policy = ScrapePolicy(
            force=force,
            skip_verification=skip_verification,
            fetcher_type=cast(FetcherName, fetcher_type),
            selector_level=selector_level if selector_level is not None else ScrapePolicy().selector_level,
            max_concurrency=max_concurrency,
        )
        output_policy = OutputPolicy(
            formats=tuple(output_formats),
            quiet=quiet,
            json_output=json_output,
            debug_html=debug,
        )
        call_policy = Policy(model=model_policy, scrape=scrape_policy, output=output_policy)
        policy = Policy.cascade(Policy.from_env(), call_policy)
        spec = policy.resolve_run_spec()
    except (KeyError, ValueError, ValidationError) as e:
        raise click.ClickException(str(e)) from e
    console.print(
        f'[bold]Using[/bold] [green]{spec.llm_config.provider}[/green] / [cyan]{spec.llm_config.model_name}[/cyan]'
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
