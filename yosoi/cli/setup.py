"""LLM config setup and CLI configuration helpers."""

import os

import rich_click as click

from yosoi.cli.utils import console, console_err


def setup_llm_config(model_arg: str | None = None):
    """Set up LLM configuration from -m/--model flag or environment variables.

    When no ``--model`` flag is given, walks all known providers and picks the
    first one whose API key is present in the environment.  The actual key
    resolution (and cross-provider fallback) is handled by
    ``YosoiConfig.validate_api_key_env``, so the LLMConfig returned here may
    have an empty ``api_key``.

    Args:
        model_arg: Model string in ``provider/model-name`` format.

    Returns:
        LLMConfig instance.

    Raises:
        click.ClickException: If the provider format is invalid.

    """
    from yosoi.core.configs import find_available_provider
    from yosoi.core.discovery.config import LLMConfig

    if model_arg:
        if '/' not in model_arg:
            raise click.ClickException(
                '--model must be in provider/model-name format (e.g. groq/llama-3.3-70b-versatile)'
            )
        provider, model_name = model_arg.split('/', 1)
        return LLMConfig(provider=provider, model_name=model_name, api_key='')

    found = find_available_provider()
    if found:
        provider, model_name, _ = found
        return LLMConfig(provider=provider, model_name=model_name, api_key='')

    return LLMConfig(provider='groq', model_name='llama-3.3-70b-versatile', api_key='')


def build_yosoi_config(model_arg: str | None, debug: bool):
    """Build a YosoiConfig from CLI args, with provider fallback and user warnings.

    Args:
        model_arg: Model string in ``provider/model-name`` format, or None.
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


def print_fetcher_info(fetcher_type: str):
    """Print information about the selected fetcher.

    Args:
        fetcher_type: Type of fetcher ('simple').

    """
    console.print('[cyan]ℹ Using Simple fetcher[/cyan] [dim](fast, works for most sites)[/dim]')
