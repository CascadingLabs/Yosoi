"""Structured configuration for Yosoi pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from yosoi.core.discovery import LLMConfig


@dataclass
class DebugConfig:
    """Configuration for debug output."""

    save_html: bool = True
    html_dir: Path = field(default_factory=lambda: Path('.yosoi/debug_html'))


@dataclass
class TelemetryConfig:
    """Configuration for observability / telemetry."""

    logfire_token: str | None = None


@dataclass
class YosoiConfig:
    """Top-level Yosoi configuration bundling LLM, debug, and telemetry settings.

    Example::

        config = YosoiConfig(
            llm=ys.groq('llama-3.3-70b-versatile', api_key),
            debug=DebugConfig(save_html=False),
        )
        pipeline = Pipeline(config, contract=MyContract)

    """

    llm: LLMConfig
    debug: DebugConfig = field(default_factory=DebugConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    logs: bool = True
