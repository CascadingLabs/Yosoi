"""pydantic-ai model transport backed by an OpenCode server."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage

from yosoi.integrations.utils.messages import flatten_messages
from yosoi.integrations.utils.usage import build_request_usage
from yosoi.utils import observability as obs


class OpenCodeModel(Model):
    """pydantic-ai model backed by a running OpenCode server."""

    def __init__(
        self,
        *,
        provider_id: str = 'openai',
        model_id: str = 'gpt-5-codex',
        base_url: str | None = None,
    ) -> None:
        """Initialize the transport with OpenCode provider, model, and server settings."""
        # pydantic-ai's base Model expects subclasses to set ``_provider``; this
        # transport has no pydantic-ai Provider object, so None. Without it,
        # entering an Agent as an async context manager (required to start MCP
        # toolsets) raises AttributeError in Model.__aenter__.
        # Base Model annotates ``_provider`` non-optional, but the ``provider``
        # property and Model.__aenter__ both handle None — which is correct for a
        # transport with no pydantic-ai Provider object.
        self._provider = None  # type: ignore[assignment]
        self._provider_id = provider_id
        self._model_id = model_id
        self._base_url: str = base_url or os.getenv('OPENCODE_BASE_URL') or 'http://localhost:4096'
        self._profile = ModelProfile(
            supports_tools=False,
            supports_json_schema_output=True,
            default_structured_output_mode='native',
        )

    @property
    def model_name(self) -> str:
        """Return provider and model ids in OpenCode notation."""
        return f'{self._provider_id}:{self._model_id}'

    @property
    def system(self) -> str:
        """Return the pydantic-ai provider system identifier."""
        return 'opencode'

    async def request(
        self,
        messages: list[ModelMessage],
        _model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Run one OpenCode request."""
        system_prompt, user_prompt = flatten_messages(messages)
        output_format = _json_schema_format(model_request_parameters)
        text, usage = await self._call_opencode(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_format=output_format,
        )
        return ModelResponse(
            parts=[TextPart(content=text)],
            model_name=self.model_name,
            timestamp=datetime.now(timezone.utc),
            usage=usage,
        )

    async def _call_opencode(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_format: dict[str, Any] | None,
    ) -> tuple[str, RequestUsage]:
        import httpx2

        debug = os.getenv('YOSOI_SDK_DEBUG') == '1'
        t0 = time.monotonic()

        def log(msg: str) -> None:
            if debug:
                with obs.span('opencode.debug', message=msg, elapsed=f'{time.monotonic() - t0:6.2f}'):
                    pass

        body: dict[str, Any] = {
            'model': {'providerID': self._provider_id, 'modelID': self._model_id},
            'system': system_prompt or '',
            'parts': [{'type': 'text', 'text': user_prompt}],
            'tools': {},
        }
        if output_format is not None:
            body['format'] = output_format

        with obs.transport_span(
            obs.BACKEND_OPENCODE,
            self.model_name,
            structured_output=output_format is not None,
            base_url=self._base_url,
            subprovider=self._provider_id,
        ):
            try:
                async with httpx2.AsyncClient(base_url=self._base_url, timeout=180) as client:
                    session_resp = await client.post('/session')
                    session_resp.raise_for_status()
                    session = session_resp.json()
                    sid = session['id']
                    log(f'session {sid} format={"json_schema" if output_format else "text"}')

                    resp = await client.post(f'/session/{sid}/message', json=body)
                    resp.raise_for_status()
                    data = resp.json()
                    info = data.get('info', {})
                    usage = _usage_from_info(info)

                    if output_format is not None and isinstance(info.get('structured'), dict):
                        out = json.dumps(info['structured'])
                        log(f'returning structured {len(out)}c')
                        return out, usage

                    chunks = [
                        part['text']
                        for part in data.get('parts', [])
                        if part.get('type') == 'text' and part.get('text')
                    ]
                    log(f'returning text {sum(len(c) for c in chunks)}c')
                    return ''.join(chunks), usage
            except Exception as e:
                obs.warning(
                    'OpenCode message failed',
                    provider=self._provider_id,
                    model=self._model_id,
                    base_url=self._base_url,
                    error=str(e),
                )
                raise


def _json_schema_format(model_request_parameters: ModelRequestParameters) -> dict[str, Any] | None:
    output_object = model_request_parameters.output_object
    if output_object is None:
        return None
    return {'type': 'json_schema', 'schema': output_object.json_schema, 'retryCount': 2}


def _usage_from_info(info: dict[str, Any]) -> RequestUsage:
    """Map OpenCode's assistant-message token counts onto pydantic-ai usage.

    OpenCode reports usage under ``info.tokens`` as
    ``{input, output, reasoning, cache: {read, write}}``. Returns a zeroed
    ``RequestUsage`` when the server omits ``tokens`` (e.g. an error or an older
    server build). See :mod:`yosoi.integrations.utils.usage` for why this matters.
    """
    tokens = info.get('tokens')
    if not isinstance(tokens, dict):
        return RequestUsage()
    cache = tokens.get('cache')
    if not isinstance(cache, dict):
        cache = {}
    return build_request_usage(
        input_tokens=tokens.get('input'),
        output_tokens=tokens.get('output'),
        cache_read_tokens=cache.get('read'),
        cache_write_tokens=cache.get('write'),
        reasoning_tokens=tokens.get('reasoning'),
    )
