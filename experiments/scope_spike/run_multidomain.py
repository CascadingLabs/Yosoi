"""Multi-domain reuse-safety shootout (statistical run, 13 domains).

Run:  uv run python experiments/scope_spike/run_multidomain.py

Loads every fixtures/domains/*.json (live voidcrawl captures, one identical
generic extract per page) and scores four GENERIC reuse-safety mechanisms across
all domains at once, so the result is a cross-site statistic — not a Reddit
anecdote. Each domain contributes one 'seed' (the page a recipe was learned on)
and several replays labelled must-transfer / must-refuse.

Mechanisms (all site-agnostic — derive expectation from the seed only):
  DISCOVERY    rows > 0                         (status quo; the bug)
  CARDINALITY  replay rows within band of seed  (VALIDATION, content invariant)
  ROUTE        same URL route template          (TAGGING via URL)
  STRUCTURAL   tag-histogram cosine >= T         (TAGGING via DOM shape; URL-free)
plus two layered, fail-closed combos.

The point of the cross-domain run: show that NO single mechanism wins everywhere
(route dies on Wikipedia where category & article share /wiki/X; cardinality dies
on Reddit /user and partial-match landings; structural is the steadiest but can
false-split), and quantify it over ~50 samples.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

DOMAINS_DIR = Path(__file__).parent / 'fixtures' / 'domains'
CARD_RATIO = 0.2  # cardinality floor = seed_rows * ratio
STRUCT_T = 0.90  # structural cosine threshold (sensitivity reported below)


@dataclass(frozen=True)
class Page:
    """One captured page observation (generic schema, any domain)."""

    role: str
    url: str
    title: str
    rows: int
    body_class: str
    tag_hist: dict[str, int]
    blocked: bool


def load_pages(path: Path) -> tuple[str, list[Page]]:
    """Return (domain, [Page,...]) from one fixture file, dropping blocked pages."""
    d = json.loads(path.read_text())
    pages = []
    for p in d.get('pages', []):
        if p.get('blocked'):
            continue
        pages.append(
            Page(
                role=p.get('role', ''),
                url=p.get('href', ''),
                title=p.get('title', ''),
                rows=int(p.get('rows', 0) or 0),
                body_class=p.get('bodyClass', '') or '',
                tag_hist=dict(p.get('tagHist', [])),
                blocked=False,
            )
        )
    return d.get('domain', path.stem), pages


# --------------------------------------------------------------------------- #
# Mechanisms (each: seed, replay -> (allow: bool, reason: str))
# --------------------------------------------------------------------------- #
def m_discovery(seed: Page, r: Page) -> tuple[bool, str]:
    """Status quo: any non-empty match counts as success."""
    return (r.rows > 0, f'rows={r.rows}')


def m_cardinality(seed: Page, r: Page) -> tuple[bool, str]:
    """Replay row count must be within a band of the discovery count."""
    if seed.rows == 0:
        return (True, 'seed empty (abstain)')
    floor = max(1, int(seed.rows * CARD_RATIO))
    if r.rows < floor:
        return (False, f'rows {r.rows} < floor {floor} (seed {seed.rows})')
    return (True, f'rows {r.rows} >= floor {floor}')


_NUM = re.compile(r'\d')


def route_template(url: str) -> str:
    """Generic URL -> route template; collapse id-ish segments, mask one slug.

    No per-site rules: digits/long tokens -> {id}; the value after the first
    collection segment -> {slug} (so /r/ted/top == /r/python/top, /quote/AAPL
    == /quote/MSFT), query string dropped. Cannot, by design, tell apart two
    page-classes that share a URL shape (e.g. Wikipedia /wiki/X) -- that gap is
    a finding, not a bug.
    """
    path = re.sub(r'https?://[^/]+', '', url).split('?')[0].rstrip('/')
    out = []
    for seg in path.split('/'):
        if not seg:
            continue
        out.append('{id}' if (_NUM.search(seg) or len(seg) >= 24) else seg)
    if len(out) >= 2:
        out[1] = '{slug}'
    return '/' + '/'.join(out)


def m_route(seed: Page, r: Page) -> tuple[bool, str]:
    """Same normalized route template => same page class."""
    st, rt = route_template(seed.url), route_template(r.url)
    return (st == rt, f'{st} vs {rt}')


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def m_structural(seed: Page, r: Page, t: float = STRUCT_T) -> tuple[bool, str]:
    """DOM tag-histogram cosine similarity >= threshold => same page class.

    URL-free, so it works where route tagging can't (garbage URLs / shared URL
    shapes). The threshold is the one knob; sensitivity is reported in main().
    """
    sim = _cosine(seed.tag_hist, r.tag_hist)
    return (sim >= t, f'cosine {sim:.3f}')


def layered(mechs, seed: Page, r: Page) -> tuple[bool, str]:
    """Fail-closed AND of mechanisms; first refusal wins."""
    for name, fn in mechs:
        ok, why = fn(seed, r)
        if not ok:
            return (False, f'[{name}] {why}')
    return (True, 'all ok')


APPROACHES = {
    'discovery': [('discovery', m_discovery)],
    'cardinality': [('cardinality', m_cardinality)],
    'route': [('route', m_route)],
    'structural': [('structural', m_structural)],
    'card+struct': [('cardinality', m_cardinality), ('structural', m_structural)],
    'card+route+struct': [
        ('cardinality', m_cardinality),
        ('route', m_route),
        ('structural', m_structural),
    ],
}


def should_allow(role: str) -> bool:
    """Ground truth: same-class siblings allow; different-class refuse."""
    return role in ('seed', 'must-transfer')


def score_approach(mechs, domains) -> dict:
    """Confusion stats for one approach across all domains (positive = block)."""
    tp = tn = fp = fn = 0
    misses, false_alarms_list = [], []
    for domain, pages in domains:
        seed = next((p for p in pages if p.role == 'seed'), None)
        if not seed:
            continue
        for p in pages:
            if p.role == 'seed':
                continue
            allow, _why = layered(mechs, seed, p)
            want = should_allow(p.role)
            tag = f'{domain}:{p.url.split("/")[-1][:24] or p.url[-24:]}'
            if want and allow:
                tp += 1
            elif want and not allow:
                fp += 1
                false_alarms_list.append(tag)
            elif not want and not allow:
                tn += 1
            else:  # not want and allow == LEAK
                fn += 1
                misses.append(tag)
    acc = (tp + tn) / max(1, tp + tn + fp + fn)
    return {
        'good': tp,
        'bad': tn,
        'leaks': fn,
        'false_alarms': fp,
        'acc': acc,
        'misses': misses,
        'fa': false_alarms_list,
    }


def structural_separation(domains) -> tuple[list[float], list[float]]:
    """Cosine of every replay to its seed, split by ground-truth class."""
    t_cos, r_cos = [], []
    for _, pages in domains:
        seed = next((p for p in pages if p.role == 'seed'), None)
        if not seed:
            continue
        for p in pages:
            if p.role == 'seed':
                continue
            c = _cosine(seed.tag_hist, p.tag_hist)
            (t_cos if should_allow(p.role) else r_cos).append(c)
    return t_cos, r_cos


def main() -> int:
    """Score every approach across all domains and print the aggregate stats."""
    files = sorted(DOMAINS_DIR.glob('*.json'))
    domains = [load_pages(f) for f in files]

    # ---- sample inventory ------------------------------------------------- #
    total_replays = transfers = refuses = 0
    for _, pages in domains:
        for p in pages:
            if p.role == 'seed':
                continue
            total_replays += 1
            if should_allow(p.role):
                transfers += 1
            else:
                refuses += 1
    print('=' * 80)
    print(f'MULTI-DOMAIN REUSE-SAFETY SHOOTOUT — {len(domains)} domains')
    print(f'  samples: {total_replays} replay decisions ({transfers} must-transfer, {refuses} must-refuse)')
    print(f'  knobs: cardinality floor ratio={CARD_RATIO}, structural cosine T={STRUCT_T}')
    print('=' * 80)

    # ---- structural separation (does cosine actually separate the classes?)  #
    t_cos, r_cos = structural_separation(domains)
    if t_cos and r_cos:
        print('\nStructural cosine separation:')
        print(f'  must-transfer: min={min(t_cos):.3f} mean={sum(t_cos) / len(t_cos):.3f} max={max(t_cos):.3f}')
        print(f'  must-refuse:   min={min(r_cos):.3f} mean={sum(r_cos) / len(r_cos):.3f} max={max(r_cos):.3f}')
        print(f'  -> overlap zone: refuse-max {max(r_cos):.3f} vs transfer-min {min(t_cos):.3f}')

    # ---- per-approach confusion across all domains ------------------------ #
    print('\n' + '=' * 80)
    print('AGGREGATE CONFUSION (positive event = a wrong-page reuse that should be blocked)')
    print('=' * 80)
    header = f'{"approach":20s} {"good✓":6s} {"bad✓":6s} {"LEAKS":6s} {"false_alarm":12s} {"acc":6s}'
    print(header)
    results = {name: score_approach(mechs, domains) for name, mechs in APPROACHES.items()}
    for name, s in results.items():
        print(f'{name:20s} {s["good"]:<6d} {s["bad"]:<6d} {s["leaks"]:<6d} {s["false_alarms"]:<12d} {s["acc"]:.2f}')

    # ---- where each mechanism fails (the interesting part) ---------------- #
    print('\n' + '=' * 80)
    print('FAILURE DETAIL')
    print('=' * 80)
    for name, s in results.items():
        if s['leaks'] or s['false_alarms']:
            print(f'\n{name}:')
            if s['leaks']:
                print(f'  LEAKS ({s["leaks"]}): {", ".join(s["misses"])}')
            if s['false_alarms']:
                print(f'  false alarms ({s["false_alarms"]}): {", ".join(s["fa"])}')

    # ---- verdict ---------------------------------------------------------- #
    print('\n' + '=' * 80)
    print('VERDICT')
    print('=' * 80)
    zero_leak = [n for n, s in results.items() if s['leaks'] == 0]
    perfect = [n for n, s in results.items() if s['leaks'] == 0 and s['false_alarms'] == 0]
    best = max(results.items(), key=lambda kv: (kv[1]['leaks'] == 0, kv[1]['acc']))
    print(f'  zero-leak approaches : {zero_leak or "NONE"}')
    print(f'  perfect approaches   : {perfect or "NONE"}')
    print(
        f'  best by (no-leak, accuracy): {best[0]}  (acc={best[1]["acc"]:.2f}, '
        f'leaks={best[1]["leaks"]}, false_alarms={best[1]["false_alarms"]})'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
