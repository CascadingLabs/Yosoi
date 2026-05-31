"""Print the distilled detector's verdict + rule-firing breakdown over fixtures."""

from __future__ import annotations

import glob
import json
from pathlib import Path

from detector import Obs, Verdict, decide


def obs(p: dict) -> Obs:
    """Fixture record -> Obs."""
    return Obs(
        url=p.get('href', ''),
        title=p.get('title', ''),
        rows=int(p.get('rows', 0) or 0),
        body_class=p.get('bodyClass', '') or '',
        tag_hist=dict(p.get('tagHist', [])),
    )


def main() -> int:
    """Tally verdicts, leaks, false alarms, abstains, and which rule fired."""
    allow = refuse = abstain = leaks = fa = 0
    abstained: list[str] = []
    firings: dict[str, int] = {}
    for f in sorted(glob.glob('fixtures/domains/*.json')):
        d = json.loads(Path(f).read_text())
        pages = [p for p in d['pages'] if not p.get('blocked')]
        seed = next((p for p in pages if p['role'] == 'seed'), None)
        if not seed:
            continue
        s = obs(seed)
        for p in pages:
            if p['role'] == 'seed':
                continue
            dec = decide(s, obs(p))
            should = p['role'] == 'must-transfer'
            firings[dec.rule] = firings.get(dec.rule, 0) + 1
            if dec.verdict is Verdict.ALLOW:
                allow += 1
            elif dec.verdict is Verdict.REFUSE:
                refuse += 1
            else:
                abstain += 1
                abstained.append(f'{d["domain"]}:{p["role"]}:{p["href"][-30:]}')
            if not should and dec.verdict is Verdict.ALLOW:
                leaks += 1
            if should and dec.verdict is Verdict.REFUSE:
                fa += 1
    n = allow + refuse + abstain
    print(f'TOTAL {n}  allow={allow} refuse={refuse} abstain={abstain}')
    print(f'LEAKS={leaks}  false_alarms={fa}  abstain_rate={round(100 * abstain / n)}pct')
    print('rule firings:', dict(sorted(firings.items(), key=lambda kv: -kv[1])))
    print('abstained (= paid LLM call) cases:')
    for a in abstained:
        print('  ', a)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
