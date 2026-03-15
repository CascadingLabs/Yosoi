"""LLM config setup and CLI configuration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import rich_click as click

from yosoi.cli.utils import console, console_err

if TYPE_CHECKING:
    from yosoi.core.configs import YosoiConfig


def build_yosoi_config(model_arg: str | None, debug: bool) -> YosoiConfig:
    """Build a YosoiConfig from CLI args, with provider fallback and user warnings.

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

    # Capture the requested provider so we can warn about fallbacks
    original_provider: str | None = None
    if model_arg:
        from yosoi.core.discovery.config import _parse_model_string

        try:
            prov, _ = _parse_model_string(model_arg)
            original_provider = prov
        except ValueError:
            pass

    try:
        yosoi_config = auto_config(model=model_arg, debug=debug)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    if original_provider and yosoi_config.llm.provider != original_provider:
        console_err.print(
            f'[yellow]Warning: {original_provider!r} has no API key — '
            f'fell back to {yosoi_config.llm.provider!r}[/yellow]'
        )
    console.print(
        f'[bold]Using[/bold] [green]{yosoi_config.llm.provider}[/green] / [cyan]{yosoi_config.llm.model_name}[/cyan]'
    )
    return yosoi_config


def print_fetcher_info(fetcher_type: str) -> None:
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple').

    """
    console.print('[cyan]ℹ Using Simple fetcher[/cyan] [dim](fast, works for most sites)[/dim]')
