"""Head-to-head: VALIDATION vs TAGGING vs DISCOVERY on real reddit fixtures.

Run:  uv run python experiments/scope_spike/run_comparison.py

Loads fixtures/reddit_observations.json (live voidcrawl captures), treats the
'seed' page as the discovered recipe, and asks every approach: "is reuse on this
replay page safe?" Ground truth comes from each fixture's `role`:
  must-transfer => reuse SHOULD be allowed
  must-refuse   => reuse SHOULD be refused

Emits a per-approach confusion matrix and the per-page decisions so we can see
*which* mechanism catches *which* failure. No network; pure replay of captures.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from guards import APPROACHES, evaluate, load_observations

FIXTURE = Path(__file__).parent / 'fixtures' / 'reddit_observations.json'


def ground_truth_allow(role: str) -> bool:
    """must-transfer -> should allow; must-refuse -> should refuse."""
    return role in ('seed', 'must-transfer')


def main() -> int:
    """Run the shootout over all approaches and print the confusion summary."""
    obs = load_observations(FIXTURE)
    seed = next(o for o in obs if o.role == 'seed')
    replays = [o for o in obs if o.role != 'seed']

    print('=' * 78)
    print('REUSE-SAFETY SHOOTOUT — recipe discovered on:', seed.url)
    print('  field/selectors learned once; replayed on each page below')
    print('=' * 78)

    # Per-page truth table first (what each page actually is).
    print('\nGround truth (from live captures):')
    for o in [seed, *replays]:
        want = 'ALLOW' if ground_truth_allow(o.role) else 'REFUSE'
        print(
            f'  {o.role:13s} {o.url:62s}\n'
            f'      rows={o.rows:<3d} subs={o.distinct_sub_count} '
            f"body='{o.body_class}' -> want {want}"
        )

    summary: dict[str, dict[str, int]] = {}

    for approach in APPROACHES:
        print('\n' + '-' * 78)
        print(f'APPROACH: {approach}')
        print('-' * 78)
        tp = tn = fp = fn = 0  # for the safety question: positive = "refuse"
        for o in replays:
            allow, why = evaluate(approach, seed, o)
            should_allow = ground_truth_allow(o.role)
            correct = allow == should_allow
            # Confusion framed on the dangerous event = a wrong-page reuse.
            if not should_allow:  # must-refuse
                if not allow:
                    tn += 1  # correctly blocked a bad reuse
                else:
                    fn += 1  # LEAKED a bad reuse  <-- the CAS-83 failure
            else:  # must-transfer
                if allow:
                    tp += 1  # correctly allowed a good reuse
                else:
                    fp += 1  # false alarm: blocked a safe reuse
            mark = 'OK ' if correct else 'XX '
            verdict = 'ALLOW ' if allow else 'REFUSE'
            print(f'  {mark}{o.role:13s} {verdict}  {why}')
        leaks = fn
        false_alarms = fp
        summary[approach] = {
            'good_reuse_allowed': tp,
            'bad_reuse_blocked': tn,
            'LEAKS(bad reuse allowed)': leaks,
            'false_alarms(good reuse blocked)': false_alarms,
        }

    print('\n' + '=' * 78)
    print('SUMMARY  (leaks = CAS-83 silent wrong-data; false_alarms = needless re-discovery)')
    print('=' * 78)
    hdr = f'{"approach":22s} {"good✓":6s} {"bad✓":6s} {"LEAKS":6s} {"false_alarm":12s}'
    print(hdr)
    for approach, s in summary.items():
        print(
            f'{approach:22s} '
            f'{s["good_reuse_allowed"]:<6d} '
            f'{s["bad_reuse_blocked"]:<6d} '
            f'{s["LEAKS(bad reuse allowed)"]:<6d} '
            f'{s["false_alarms(good reuse blocked)"]:<12d}'
        )

    print('\nVERDICT:')
    perfect = [
        a
        for a, s in summary.items()
        if s['LEAKS(bad reuse allowed)'] == 0 and s['false_alarms(good reuse blocked)'] == 0
    ]
    zero_leak = [a for a, s in summary.items() if s['LEAKS(bad reuse allowed)'] == 0]
    print(f'  zero-leak approaches : {zero_leak or "NONE"}')
    print(f'  perfect approaches   : {perfect or "NONE"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
