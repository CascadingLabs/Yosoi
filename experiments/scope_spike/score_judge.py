"""Score the LLM-judge guard against ground truth + the algorithmic guards.

Merges the three judge verdict slices, compares to judge_truth.json, and prints
the same confusion frame used in run_multidomain.py so the LLM judge sits in one
table next to discovery/cardinality/route/structural/card+struct.

The question: does human-style judgment (reading title+url+shape) beat the
threshold classifiers on identical inputs — and crucially, does it close the
'right costume, wrong page' leak (reddit /user/spez) that NO numeric signal can?
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / 'results'

_BASELINES = """  (compare to the algorithmic run:)
  structural       26     22     4      0            0.92
  card+struct      21     25     1      5            0.88
  cardinality      21     24     2      5            0.87
  discovery        24     18     8      2            0.81
  route            13     19     7      13           0.62"""


def load_verdicts() -> dict[str, dict]:
    """Merge judge_verdicts_{0,1,2}.json into {id: {verdict, confidence, reason}}."""
    v: dict[str, dict] = {}
    for s in range(3):
        f = OUT / f'judge_verdicts_{s}.json'
        if not f.exists():
            print(f'WARNING: missing {f.name}')
            continue
        for e in json.loads(f.read_text()):
            v[e['id']] = e
    return v


def confusion(truth: dict, verdicts: dict) -> dict:
    """Count tp/tn/fp/fn plus the leak and false-alarm id lists."""
    tp = tn = fp = fn = 0
    leaks, false_alarms = [], []
    for pid, want in truth.items():
        v = verdicts.get(pid)
        if not v:
            continue
        allow = v['verdict'] == 'allow'
        should_allow = want == 'allow'
        if should_allow and allow:
            tp += 1
        elif should_allow and not allow:
            fp += 1
            false_alarms.append((pid, v.get('reason', '')))
        elif not should_allow and not allow:
            tn += 1
        else:  # should refuse but allowed == leak
            fn += 1
            leaks.append((pid, v.get('reason', '')))
    return {'tp': tp, 'tn': tn, 'fp': fp, 'fn': fn, 'leaks': leaks, 'false_alarms': false_alarms}


def main() -> int:
    """Print the LLM judge's confusion vs the algorithmic baselines."""
    truth = json.loads((OUT / 'judge_truth.json').read_text())
    verdicts = load_verdicts()
    c = confusion(truth, verdicts)
    total = c['tp'] + c['tn'] + c['fp'] + c['fn']
    acc = (c['tp'] + c['tn']) / max(1, total)

    print('=' * 78)
    print('LLM-JUDGE GUARD — scored on the same 52 samples, identical inputs')
    print('=' * 78)
    print(f'  scored {total} of {len(truth)} packets\n')
    print(f'{"approach":16s} {"good":6s} {"bad":6s} {"LEAKS":6s} {"false_alarm":12s} acc')
    print(f'{"llm_judge":16s} {c["tp"]:<6d} {c["tn"]:<6d} {c["fn"]:<6d} {c["fp"]:<12d} {acc:.2f}\n')
    print(_BASELINES)

    if c['leaks']:
        print(f'\nLEAKS ({len(c["leaks"])}):')
        for pid, why in c['leaks']:
            print(f'  {pid}: {why}')
    else:
        print('\nLEAKS: 0  <-- zero wrong-page reuses allowed')
    print(f'false alarms: {len(c["false_alarms"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
