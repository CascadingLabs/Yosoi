"""Small dependency-free OpenAI-compatible multimodal client for the spike."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any
from urllib import request


def image_data_url(path: Path) -> str:
    """Encode a local image as a data URL."""
    media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    encoded = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{media_type};base64,{encoded}'


def image_dimensions(path: Path) -> tuple[int, int] | None:
    """Read common PNG/JPEG dimensions without adding an image dependency."""
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    if data.startswith(b'\xff\xd8'):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = int.from_bytes(data[index : index + 2], 'big')
            if marker in range(0xC0, 0xC4) or marker in range(0xC5, 0xC8):
                return int.from_bytes(data[index + 5 : index + 7], 'big'), int.from_bytes(
                    data[index + 7 : index + 9], 'big'
                )
            index += length
    return None


def payload(model: str, prompt: str, image: Path, max_tokens: int) -> dict[str, Any]:
    """Build one chat completion request."""
    return {
        'model': model,
        'messages': [
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': image_data_url(image)}},
                ],
            }
        ],
        'max_tokens': max_tokens,
        'temperature': 0,
    }


def get_json(url: str, api_key: str) -> dict[str, Any]:
    """Send a JSON GET request."""
    req = request.Request(url, headers={'Authorization': f'Bearer {api_key}'})
    with request.urlopen(req, timeout=30) as response:
        return json.load(response)


def post_json(url: str, body: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Send a non-streaming JSON request."""
    data = json.dumps(body).encode()
    req = request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )
    with request.urlopen(req, timeout=300) as response:
        return json.load(response)


def stream_completion(url: str, body: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Stream a completion and return timing plus the final usage payload."""
    data = json.dumps(body | {'stream': True, 'stream_options': {'include_usage': True}}).encode()
    req = request.Request(
        url,
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
    )
    started = time.perf_counter()
    first_token_at: float | None = None
    text = ''
    usage: dict[str, Any] = {}
    with request.urlopen(req, timeout=300) as response:
        for raw_line in response:
            line = raw_line.decode('utf-8').strip()
            if not line.startswith('data: '):
                continue
            chunk = line[6:]
            if chunk == '[DONE]':
                break
            event = json.loads(chunk)
            usage.update(event.get('usage') or {})
            choices = event.get('choices') or []
            if choices:
                delta = choices[0].get('delta') or {}
                piece = delta.get('content') or ''
                if piece and first_token_at is None:
                    first_token_at = time.perf_counter()
                text += piece
    finished = time.perf_counter()
    output_tokens = int(usage.get('completion_tokens') or 0)
    ttft_ms = (first_token_at - started) * 1000 if first_token_at else None
    wall_ms = (finished - started) * 1000
    decode_ms = (finished - first_token_at) * 1000 if first_token_at else None
    return {
        'ttft_ms': ttft_ms,
        'wall_ms': wall_ms,
        'output_tokens': output_tokens,
        'decode_tps': output_tokens / (decode_ms / 1000) if decode_ms and output_tokens else None,
        'text': text,
        'usage': usage,
    }
