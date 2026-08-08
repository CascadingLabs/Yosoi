"""Send one text-plus-image request to the Echo vLLM endpoint."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from client import get_json, payload, post_json, resolve_model


def main() -> None:
    """Run the multimodal smoke request."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--base-url', default=os.getenv('INFERENCE_BASE_URL', 'http://echo:8096/v1'))
    parser.add_argument('--model', default=os.getenv('MODEL_ID'), help='defaults to whatever the endpoint serves')
    parser.add_argument('--api-key', default=os.getenv('INFERENCE_API_KEY', 'EMPTY'))
    parser.add_argument('--prompt', default='Describe this screenshot in one concise sentence.')
    args = parser.parse_args()
    models = get_json(f'{args.base_url.rstrip("/")}/models', args.api_key)
    model = resolve_model(args.base_url, args.api_key, args.model)
    result = post_json(
        f'{args.base_url.rstrip("/")}/chat/completions', payload(model, args.prompt, args.image, 128), args.api_key
    )
    print(json.dumps({'models': models, 'completion': result}, indent=2))


if __name__ == '__main__':
    main()
