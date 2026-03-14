"""LLM config setup and CLI configuration helpers."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import rich_click as click

from yosoi.cli.utils import console, console_err

if TYPE_CHECKING:
    from yosoi.core.configs import YosoiConfig
    from yosoi.core.discovery.config import LLMConfig


def setup_llm_config(model_arg: str | None = None) -> LLMConfig:
    """Set up LLM configuration from -m/--model flag or environment variables.

    Resolution order:
    1. ``--model`` CLI flag
    2. ``YOSOI_MODEL`` environment variable (from shell or .env)
    3. First provider with an available API key (auto-detect)
    4. Groq default fallback

    Args:
        model_arg: Model string in ``provider:model-name`` or ``provider/model-name`` format.

    Returns:
        LLMConfig instance.

    Raises:
        click.ClickException: If the provider format is invalid.

    """
    from dotenv import load_dotenv

    from yosoi.core.configs import find_available_provider
    from yosoi.core.discovery.config import LLMConfig, _parse_model_string

    load_dotenv()

    if model_arg:
        try:
            prov, model_name = _parse_model_string(model_arg)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        return LLMConfig(provider=prov, model_name=model_name, api_key='')

    yosoi_model = os.getenv('YOSOI_MODEL')
    if yosoi_model:
        try:
            prov, model_name = _parse_model_string(yosoi_model)
        except ValueError as e:
            raise click.ClickException(f'YOSOI_MODEL env var is invalid: {e}') from e
        return LLMConfig(provider=prov, model_name=model_name, api_key='')

    found = find_available_provider()
    if found:
        provider, model_name, _ = found
        return LLMConfig(provider=provider, model_name=model_name, api_key='')

    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')


def build_yosoi_config(model_arg: str | None, debug: bool) -> YosoiConfig:
    """Build a YosoiConfig from CLI args, with provider fallback and user warnings.

    Args:
        model_arg: Model string in ``provider:model-name`` format, or None.
        debug: Whether to enable debug HTML saving.

    Returns:
        Validated YosoiConfig.

    Raises:
        click.ClickException: On configuration errors.
    """
    from yosoi.core.configs import DebugConfig, TelemetryConfig, YosoiConfig

    llm_config = setup_llm_config(model_arg)
    original_provider = llm_config.provider

    try:
        yosoi_config = YosoiConfig(
            llm=llm_config,
            debug=DebugConfig(save_html=debug),
            telemetry=TelemetryConfig(logfire_token=os.getenv('LOGFIRE_TOKEN')),
        )
    except Exception as e:
        raise click.ClickException(f'Configuration Error: {e}') from e

    if yosoi_config.llm.provider != original_provider:
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
