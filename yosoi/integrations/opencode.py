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

from yosoi.integrations.messages import flatten_messages


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
        self._provider_id = provider_id
        self._model_id = model_id
        self._base_url = base_url or os.getenv('OPENCODE_BASE_URL', 'http://localhost:4096')
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
        text = await self._call_opencode(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            output_format=output_format,
        )
        return ModelResponse(
            parts=[TextPart(content=text)],
            model_name=self.model_name,
            timestamp=datetime.now(timezone.utc),
            usage=RequestUsage(),
        )

    async def _call_opencode(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_format: dict[str, Any] | None,
    ) -> str:
        import httpx

        debug = os.getenv('YOSOI_SDK_DEBUG') == '1'
        t0 = time.monotonic()

        def log(msg: str) -> None:
            if debug:
                print(f'[opencode +{time.monotonic() - t0:6.2f}s] {msg}', flush=True)

        body: dict[str, Any] = {
            'model': {'providerID': self._provider_id, 'modelID': self._model_id},
            'system': system_prompt or '',
            'parts': [{'type': 'text', 'text': user_prompt}],
            'tools': {},
        }
        if output_format is not None:
            body['format'] = output_format

        async with httpx.AsyncClient(base_url=self._base_url, timeout=180) as client:
            session = (await client.post('/session')).json()
            sid = session['id']
            log(f'session {sid} format={"json_schema" if output_format else "text"}')

            resp = await client.post(f'/session/{sid}/message', json=body)
            resp.raise_for_status()
            data = resp.json()
            info = data.get('info', {})

            if output_format is not None and isinstance(info.get('structured'), dict):
                out = json.dumps(info['structured'])
                log(f'returning structured {len(out)}c')
                return out

            chunks = [part['text'] for part in data.get('parts', []) if part.get('type') == 'text' and part.get('text')]
            log(f'returning text {sum(len(c) for c in chunks)}c')
            return ''.join(chunks)


def _json_schema_format(model_request_parameters: ModelRequestParameters) -> dict[str, Any] | None:
    output_object = model_request_parameters.output_object
    if output_object is None:
        return None
    return {'type': 'json_schema', 'schema': output_object.json_schema, 'retryCount': 2}
