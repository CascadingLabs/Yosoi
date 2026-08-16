"""Summarize JSONL benchmark artifacts for checkpoint comparison."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def percentile(values: list[float], fraction: float) -> float | None:
    """Return a nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def main() -> None:
    """Print grouped latency and throughput summaries as JSON."""
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in args.files:
        with path.open(encoding='utf-8') as handle:
            for line in handle:
                row = json.loads(line)
                groups[(row['model'], row['endpoint'], Path(row['image']).name)].append(row)
    summaries = []
    for (model, endpoint, image), rows in groups.items():
        wall = [float(row['wall_ms']) for row in rows]
        ttft = [float(row['ttft_ms']) for row in rows if row.get('ttft_ms') is not None]
        decode = [float(row['decode_tps']) for row in rows if row.get('decode_tps') is not None]
        summaries.append(
            {
                'model': model,
                'endpoint': endpoint,
                'image': image,
                'runs': len(rows),
                'wall_p50_ms': percentile(wall, 0.50),
                'wall_p95_ms': percentile(wall, 0.95),
                'ttft_p50_ms': percentile(ttft, 0.50),
                'decode_tps_p50': percentile(decode, 0.50),
                'input_tokens': rows[0].get('input_tokens'),
                'vision_tokens': rows[0].get('vision_tokens'),
                'note': 'Correctness and VRAM are not measured by this microbench; join boss-fight and nvidia-smi artifacts before selecting a checkpoint.',
            }
        )
    print(json.dumps(sorted(summaries, key=lambda item: item['wall_p50_ms'] or float('inf')), indent=2))


if __name__ == '__main__':
    main()
