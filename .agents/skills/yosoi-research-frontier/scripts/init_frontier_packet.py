#!/usr/bin/env python3
"""Create a Yosoi research-frontier packet skeleton."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILL_DIR = Path(__file__).resolve().parents[1]
ZERO_POLICY = SKILL_DIR / 'assets' / 'frontier-zero-policy.yaml'
BUDGETED_POLICY = SKILL_DIR / 'assets' / 'frontier-budgeted-policy.yaml'


def _slug(value: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '-', value.strip().lower()).strip('-')
    return cleaned[:64] or 'research'


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + '\n')


def main() -> int:
    """Parse CLI arguments and write the packet files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('topic', help='Research topic or decision.')
    parser.add_argument('--llm-budget-usd', type=float, default=0.0)
    parser.add_argument('--api-budget-usd', type=float, default=0.0)
    parser.add_argument('--packet-dir', type=Path, default=None)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    run_id = f'{now.strftime("%Y%m%dT%H%M%SZ")}-{_slug(args.topic)}'
    packet_dir = args.packet_dir or ROOT / '.yosoi' / 'research' / run_id
    packet_dir.mkdir(parents=True, exist_ok=False)

    for child in ('sources', 'candidate-contracts', 'scrape-results', 'notes'):
        (packet_dir / child).mkdir(parents=True, exist_ok=True)

    budgeted = args.llm_budget_usd > 0 or args.api_budget_usd > 0
    shutil.copyfile(BUDGETED_POLICY if budgeted else ZERO_POLICY, packet_dir / 'policy.yaml')

    meta = {
        'run_id': run_id,
        'topic': args.topic,
        'created_at': now.isoformat(),
        'mode': 'budgeted' if budgeted else 'zero-cost',
        'budget': {
            'llm_usd': args.llm_budget_usd,
            'api_usd': args.api_budget_usd,
        },
        'status': 'frontier',
    }
    _write_json(packet_dir / 'frontier.json', meta)
    _write_json(
        packet_dir / 'query-plan.json',
        {
            'topic': args.topic,
            'queries': [],
            'source_hypotheses': [],
            'must_answer': [],
            'known_limits': [],
        },
    )
    _write_json(
        packet_dir / 'source-map.json',
        {
            'sources': [],
            'paid_provider_candidates': [],
            'blocked_or_unavailable': [],
        },
    )
    _write_text(packet_dir / 'observations.jsonl', '')
    _write_text(packet_dir / 'evidence.jsonl', '')
    _write_text(packet_dir / 'claims.json', '{\n  "claims": []\n}\n')
    _write_text(
        packet_dir / 'brief.md',
        f'# Research Frontier Brief\n\nTopic: {args.topic}\n\nDecision this run should support:\n\n- \n\n',
    )
    _write_text(packet_dir / 'limitations.md', '# Limitations\n\n- Unknown until source survey is complete.\n')
    _write_text(
        packet_dir / 'mvp-plan.md',
        '# MVP Plan\n\n- Smallest useful deliverable:\n- Data sources:\n- Manual checks:\n',
    )
    _write_text(
        packet_dir / 'pipeline-plan.md',
        '# Production Pipeline Plan\n\n- Deterministic sources:\n- Yosoi contracts to promote:\n- Schedule:\n- Storage/index needs:\n- LLM/API work removed from hot path:\n',
    )
    _write_text(
        packet_dir / 'commands.md',
        '# Commands\n\n'
        '```bash\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi search "{args.topic}" --limit 10 --json > {packet_dir}/sources/search-001.json\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi crawl "SEED_URL" --limit 20 --json --policy {packet_dir}/policy.yaml > {packet_dir}/sources/crawl-001.json\n'
        f'UV_CACHE_DIR=/tmp/uv-cache uv run yosoi scrape "URL" --json --policy {packet_dir}/policy.yaml > {packet_dir}/scrape-results/scrape-001.json\n'
        '```\n',
    )

    print(packet_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
