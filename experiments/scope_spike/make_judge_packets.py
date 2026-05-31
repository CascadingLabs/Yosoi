"""Build LLM-judge packets from the 13-domain fixtures.

The hypothesis (the user's "sauce"): a human/LLM can read a page's title + URL +
body-class + tag shape and *tell* it's the wrong page-class even when every
numeric signal (structural cosine, row band) says "same" — e.g. reddit /user/spez
('overview for spez') scores 0.993 cosine to a subreddit listing but is obviously
a profile. Can we capture that judgment as a validation guard?

This script emits one judge packet per replay decision, WITHHOLDING the
ground-truth role so the judge can't cheat. A separate truth file keeps the
labels for scoring. Each packet carries exactly what the algorithms saw
(title, url, body_class, rows, top tags) — a fair, identical-input comparison.
"""

from __future__ import annotations

import json
from pathlib import Path

from run_multidomain import load_pages  # type: ignore

HERE = Path(__file__).parent
DOMAINS = HERE / 'fixtures' / 'domains'
OUT = HERE / 'results'


def view(p) -> dict:
    """The exact observation the algorithms used — title/url/class/rows/shape."""
    top = sorted(p.tag_hist.items(), key=lambda kv: -kv[1])[:12]
    return {
        'url': p.url,
        'title': p.title,
        'body_class': p.body_class,
        'rows': p.rows,
        'top_tags': top,
    }


def main() -> int:
    """Emit judge_packets.json (no labels) + judge_truth.json (labels)."""
    packets, truth = [], {}
    for f in sorted(DOMAINS.glob('*.json')):
        domain, pages = load_pages(f)
        seed = next((p for p in pages if p.role == 'seed'), None)
        if not seed:
            continue
        for i, p in enumerate(pages):
            if p.role == 'seed':
                continue
            pid = f'{domain}#{i}'
            packets.append({'id': pid, 'domain': domain, 'seed': view(seed), 'replay': view(p)})
            truth[pid] = 'allow' if p.role in ('seed', 'must-transfer') else 'refuse'
    (OUT / 'judge_packets.json').write_text(json.dumps(packets, indent=2))
    (OUT / 'judge_truth.json').write_text(json.dumps(truth, indent=2))
    print(f'wrote {len(packets)} packets, {len(truth)} truth labels')
    # quick split into 3 slices for parallel judging
    n = len(packets)
    for s in range(3):
        sl = packets[s::3]
        (OUT / f'judge_slice_{s}.json').write_text(json.dumps(sl, indent=2))
        print(f'  slice {s}: {len(sl)} packets')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
