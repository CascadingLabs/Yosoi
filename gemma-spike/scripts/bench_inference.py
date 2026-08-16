"""Measure multimodal inference latency through an OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from client import image_dimensions, payload, resolve_model, stream_completion


def main() -> None:
    """Run repeated warm/cold-labelled microbench requests and write JSONL."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output', type=Path, default=Path('results/gemma4.jsonl'))
    parser.add_argument(
        '--append', action='store_true', help='append to an existing JSONL artifact instead of replacing it'
    )
    parser.add_argument('--base-url', default=os.getenv('INFERENCE_BASE_URL', 'http://echo:8096/v1'))
    parser.add_argument('--model', default=os.getenv('MODEL_ID'), help='defaults to whatever the endpoint serves')
    parser.add_argument('--api-key', default=os.getenv('INFERENCE_API_KEY', 'EMPTY'))
    parser.add_argument('--prompt', default='Inspect the screenshot and describe the visible page state.')
    parser.add_argument('--max-tokens', type=int, default=256)
    args = parser.parse_args()
    model = resolve_model(args.base_url, args.api_key, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dimensions = image_dimensions(args.image)
    # The first request is labelled cold and later requests warm. This is an
    # experimental label: the server may already have a populated prefix cache.
    mode = 'a' if args.append else 'w'
    with args.output.open(mode, encoding='utf-8') as handle:
        for run in range(args.runs):
            metrics = stream_completion(
                f'{args.base_url.rstrip("/")}/chat/completions',
                payload(model, args.prompt, args.image, args.max_tokens),
                args.api_key,
            )
            metrics.pop('text', None)
            usage = metrics.pop('usage')
            prompt_details = usage.get('prompt_tokens_details') or {}
            output_tokens = metrics['output_tokens'] or usage.get('completion_tokens') or 0
            input_tokens = usage.get('prompt_tokens') or usage.get('input_tokens')
            # Current vLLM streaming usage usually omits vision-token and
            # prefill-rate fields; preserve raw usage and emit null when absent.
            vision_tokens = usage.get('vision_tokens') or prompt_details.get('vision_tokens')
            prefill_tps = usage.get('prefill_tps') or usage.get('prefill_tokens_per_second')
            row = {
                'timestamp': datetime.now(UTC).isoformat(),
                'model': model,
                'endpoint': args.base_url,
                'run': run + 1,
                'cache_state': 'cold' if run == 0 else 'warm',
                'image_count': 1,
                'image': str(args.image),
                'image_dimensions': {'width': dimensions[0], 'height': dimensions[1]} if dimensions else None,
                'prompt': args.prompt,
                'input_tokens': input_tokens,
                'vision_tokens': vision_tokens,
                'output_tokens': output_tokens,
                'prefill_tps': prefill_tps,
                'usage_raw': usage,
                **metrics,
            }
            handle.write(json.dumps(row) + '\n')
            print(json.dumps(row))


if __name__ == '__main__':
    main()
