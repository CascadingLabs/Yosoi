"""Inspect the LLM-judge's edge cases: false alarms, the costume case, the trap."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / 'results'


def main() -> int:
    """Print the decisions that matter for the writeup."""
    truth = json.loads((OUT / 'judge_truth.json').read_text())
    packets = {p['id']: p for s in range(3) for p in json.loads((OUT / f'judge_slice_{s}.json').read_text())}
    verd = {e['id']: e for s in range(3) for e in json.loads((OUT / f'judge_verdicts_{s}.json').read_text())}

    print('FALSE ALARMS (judge refused a must-transfer):')
    for pid, w in truth.items():
        v = verd.get(pid)
        if w == 'allow' and v and v['verdict'] == 'refuse':
            pk = packets[pid]
            print(
                f'  {pid}: seed_rows={pk["seed"]["rows"]} '
                f'replay_rows={pk["replay"]["rows"]} '
                f'title={pk["replay"]["title"][:45]!r}'
            )
            print(f'    reason: {v.get("reason", "")}')

    print('\nCOSTUME CASE /user/spez:')
    for pid, v in verd.items():
        if 'spez' in packets[pid]['replay']['url']:
            print(f'  {pid}: {v["verdict"].upper()} conf={v.get("confidence")} :: {v.get("reason", "")}')

    print('\nHN 190-row trap (more rows than seed, but wrong kind):')
    for pid, v in verd.items():
        pk = packets[pid]
        if 'ycombinator' in pk['replay']['url'] and pk['replay']['rows'] > 100:
            print(f'  {pid}: {v["verdict"].upper()} replay_rows={pk["replay"]["rows"]} :: {v.get("reason", "")}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
