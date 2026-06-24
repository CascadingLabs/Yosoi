"""pydantic-ai model transport backed by the Claude Agent SDK."""

from __future__ import annotations

import json
import os
import time
from contextlib import aclosing
from datetime import datetime, timezone
from typing import Any, cast

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from yosoi.integrations.utils.messages import flatten_messages
from yosoi.integrations.utils.usage import build_request_usage
from yosoi.utils import observability as obs


class ClaudeSDKModel(Model):
    """pydantic-ai model backed by the Claude Agent SDK CLI transport."""

    def __init__(self, *, model_name: str = 'claude-opus-4-7') -> None:
        """Initialize the transport with a Claude model name."""
        # pydantic-ai's base Model expects subclasses to set ``_provider``; this
        # transport has no pydantic-ai Provider object, so None. Without it,
        # entering an Agent as an async context manager (required to start MCP
        # toolsets) raises AttributeError in Model.__aenter__.
        # Base Model annotates ``_provider`` non-optional, but the ``provider``
        # property and Model.__aenter__ both handle None — which is correct for a
        # transport with no pydantic-ai Provider object.
        self._provider = None  # type: ignore[assignment]
        self._model_name = model_name
        self._profile = ModelProfile(
            supports_tools=False,
            supports_json_schema_output=True,
            default_structured_output_mode='native',
        )

    @property
    def model_name(self) -> str:
        """Return the configured Claude model name."""
        return self._model_name

    @property
    def system(self) -> str:
        """Return the pydantic-ai provider system identifier."""
        return 'claude-sdk'

    async def request(
        self,
        messages: list[ModelMessage],
        _model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Run one Claude Agent SDK request."""
        system_prompt, user_prompt = flatten_messages(messages)
        output_format = _json_schema_format(model_request_parameters)
        text, usage = await _call_sdk(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._model_name,
            output_format=output_format,
        )
        return ModelResponse(
            parts=[TextPart(content=text)],
            model_name=self._model_name,
            timestamp=datetime.now(timezone.utc),
            usage=usage,
        )


def _json_schema_format(model_request_parameters: ModelRequestParameters) -> dict[str, Any] | None:
    output_object = model_request_parameters.output_object
    if output_object is None:
        return None
    return {'type': 'json_schema', 'schema': output_object.json_schema}


def _usage_from_result(usage: dict[str, Any] | None) -> RequestUsage:
    """Map the Claude Agent SDK ``ResultMessage.usage`` onto pydantic-ai usage.

    The SDK surfaces Anthropic's usage shape:
    ``{input_tokens, output_tokens, cache_creation_input_tokens,
    cache_read_input_tokens}``. Returns a zeroed ``RequestUsage`` when the SDK
    reports no usage. See :mod:`yosoi.integrations.utils.usage` for why this matters.
    """
    if not isinstance(usage, dict):
        return RequestUsage()
    return build_request_usage(
        input_tokens=usage.get('input_tokens'),
        output_tokens=usage.get('output_tokens'),
        cache_read_tokens=usage.get('cache_read_input_tokens'),
        cache_write_tokens=usage.get('cache_creation_input_tokens'),
    )


async def _call_sdk(
    *, system_prompt: str, user_prompt: str, model: str, output_format: dict[str, Any] | None
) -> tuple[str, RequestUsage]:
    """Drive the Claude Agent SDK and return assistant text or structured JSON text."""
    from claude_agent_sdk import ClaudeAgentOptions, query

    debug = os.getenv('YOSOI_SDK_DEBUG') == '1'
    t0 = time.monotonic()

    def log(msg: str) -> None:
        if debug:
            with obs.span('claude_sdk.debug', message=msg, elapsed=f'{time.monotonic() - t0:6.2f}'):
                pass

    options = ClaudeAgentOptions(
        system_prompt=system_prompt or None,
        model=model,
        allowed_tools=[],
        output_format=output_format,
    )

    log(f'query start format={"json_schema" if output_format else "text"}')
    chunks: list[str] = []
    structured: object | None = None
    usage = RequestUsage()
    with obs.transport_span(obs.BACKEND_CLAUDE_SDK, model, structured_output=output_format is not None):
        try:
            async with aclosing(cast(Any, query(prompt=user_prompt, options=options))) as stream:
                async for message in stream:
                    content = getattr(message, 'content', None)
                    if isinstance(content, list):
                        for block in content:
                            text = getattr(block, 'text', None)
                            if isinstance(text, str):
                                chunks.append(text)
                    if type(message).__name__ == 'ResultMessage':
                        structured = getattr(message, 'structured_output', None)
                        usage = _usage_from_result(getattr(message, 'usage', None))
                        break
        except Exception as e:
            obs.warning('Claude SDK query failed', model=model, error=str(e))
            raise

    if output_format is not None and structured is not None:
        out = json.dumps(structured)
        log(f'returning structured {len(out)}c')
        return out, usage

    log(f'returning text {sum(len(c) for c in chunks)}c')
    return ''.join(chunks), usage
