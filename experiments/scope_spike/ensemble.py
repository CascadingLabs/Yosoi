"""Ensemble detector + BATCHED-judge economics — the "do both" architecture.

The design (user's proposal): don't choose rules vs LLM. Run an ENSEMBLE of cheap
signals on the hot path (deterministic, free), let it ALLOW/REFUSE what it's sure
of, and route only the uncertain band to an LLM judge that runs OFF the hot path,
in BATCHES. The LLM never blocks a replay; it adjudicates a queue.

Why batching kills the cost objection:
  - hot path is synchronous + free (ensemble); the abstain queue is async.
  - the queue is deduplicated by PAGE-CLASS SIGNATURE before judging — you don't
    pay to judge 10,000 reddit /user pages, you judge ONE signature and cache the
    verdict for all of them. The batch size is # distinct signatures, not # pages.
  - one batched prompt amortizes system-prompt / instruction tokens across many
    items (shared context), so $/decision drops further.

Signals in the ensemble (all O(1) over the captured observation):
  1. typed rules (detector.py) — high-precision refuse + a structural allow
  2. tag-histogram cosine — shape similarity
  3. SimHash(tag-histogram) Hamming distance — compact near-duplicate-template hash
  4. body_class kind-token agreement — the site's own page-kind tell

Combination is a COST-ASYMMETRIC CASCADE, not majority vote: a leak (allow a wrong
page) is catastrophic, a false alarm costs a re-discovery, an abstain costs one
(batched, dedup'd) LLM call. So: catch refuses first (high precision), allow only
on multi-signal agreement, else abstain to the batch.

Run: uv run python experiments/scope_spike/ensemble.py
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from detector import Obs, Verdict, decide

DOMAINS = Path(__file__).parent / 'fixtures' / 'domains'


# --------------------------------------------------------------------------- #
# SimHash over the tag histogram (a real fingerprint; weighted-feature variant).
# NOTE: classic web-dedup SimHash runs over DOM tag-PATHS; our fixtures only
# captured the tag-frequency histogram, so this hashes that. It is therefore
# partly redundant with cosine (same source signal) — its additive value lands
# once we capture richer features (tag-paths, CSS class set) at scrape time. We
# include it to wire the ensemble slot and measure whether it rescues abstains.
# --------------------------------------------------------------------------- #
def simhash(tag_hist: dict[str, int], bits: int = 64) -> int:
    """64-bit SimHash of a weighted feature bag (tag -> count)."""
    acc = [0] * bits
    for tag, w in tag_hist.items():
        h = int.from_bytes(hashlib.blake2b(tag.encode(), digest_size=8).digest(), 'big')
        for i in range(bits):
            acc[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(bits):
        if acc[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    """Hamming distance between two SimHash fingerprints."""
    return bin(a ^ b).count('1')


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# --------------------------------------------------------------------------- #
# Ensemble decision
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EnsembleResult:
    """Verdict plus the signal readout, for audit + batching."""

    verdict: Verdict
    rule: str
    cosine: float
    hamming: int
    reason: str


def ensemble_decide(seed: Obs, r: Obs, *, sim_seed: int, sim_r: int) -> EnsembleResult:
    """Cost-asymmetric cascade over the cheap signals."""
    base = decide(seed, r)  # typed rules: gives REFUSE (high precision) or ALLOW or ABSTAIN
    cos = _cosine(seed.tag_hist, r.tag_hist)
    ham = hamming(sim_seed, sim_r)

    # 1. trust any high-precision REFUSE rule immediately (fail-closed bias)
    if base.verdict is Verdict.REFUSE:
        return EnsembleResult(Verdict.REFUSE, base.rule, cos, ham, base.reason)

    # 2. confident ALLOW only on MULTI-signal agreement (rules + cosine + simhash)
    if base.verdict is Verdict.ALLOW and cos >= 0.92 and ham <= 12:
        return EnsembleResult(Verdict.ALLOW, 'ensemble_allow', cos, ham, f'rules+cos {cos:.3f}+ham {ham} agree')

    # 3. rules said ALLOW but a corroborating signal disagrees -> demote to abstain
    if base.verdict is Verdict.ALLOW:
        return EnsembleResult(
            Verdict.ABSTAIN, 'allow_unconfirmed', cos, ham, f'rules allow but cos {cos:.3f}/ham {ham} weak -> queue'
        )

    # 4. rules abstained: try to RESCUE into allow if shape is near-identical
    #    (template near-duplicate) AND rows are non-empty/in-band.
    if cos >= 0.95 and ham <= 6 and r.rows > 0:
        hi, lo = max(seed.rows, r.rows), min(seed.rows, r.rows)
        if hi == 0 or lo / hi >= 0.15:
            return EnsembleResult(
                Verdict.ALLOW, 'simhash_rescue', cos, ham, f'near-dup template cos {cos:.3f}/ham {ham}'
            )

    # 5. genuinely uncertain -> batch queue
    return EnsembleResult(Verdict.ABSTAIN, 'queue', cos, ham, base.reason)


# --------------------------------------------------------------------------- #
# Page-class signature — the batching dedup key.
# --------------------------------------------------------------------------- #
def page_class_signature(domain: str, seed: Obs, r: Obs, res: EnsembleResult) -> str:
    """Coarse signature: pages sharing it get ONE batched judgement, cached for all.

    Keyed on the discriminating-but-coarse facts: domain, the body-class kind
    tokens of seed & replay, whether rows collapsed to zero, and a cosine bucket.
    Two reddit /user pages -> same signature -> judged once.
    """

    def kinds(bc: str) -> str:
        toks = sorted(set(bc.split()) - {'top-page', 'hot-page', 'new-page'})
        return ','.join(toks)

    cos_bucket = round(res.cosine, 1)
    return f'{domain}|{kinds(seed.body_class)}->{kinds(r.body_class)}|rows0={r.rows == 0}|cos~{cos_bucket}'


def _obs(p: dict) -> Obs:
    return Obs(
        url=p.get('href', ''),
        title=p.get('title', ''),
        rows=int(p.get('rows', 0) or 0),
        body_class=p.get('bodyClass', '') or '',
        tag_hist=dict(p.get('tagHist', [])),
    )


def main() -> int:
    """Run the ensemble, then report accuracy + batched-judge economics."""
    allow = refuse = abstain = leaks = fa = 0
    abstain_sigs: dict[str, list[str]] = {}
    rescued = 0
    for f in sorted(DOMAINS.glob('*.json')):
        d = json.loads(Path(f).read_text())
        domain = d.get('domain', f.stem)
        pages = [p for p in d['pages'] if not p.get('blocked')]
        seed_p = next((p for p in pages if p['role'] == 'seed'), None)
        if not seed_p:
            continue
        seed = _obs(seed_p)
        sim_seed = simhash(seed.tag_hist)
        for p in pages:
            if p['role'] == 'seed':
                continue
            r = _obs(p)
            res = ensemble_decide(seed, r, sim_seed=sim_seed, sim_r=simhash(r.tag_hist))
            should_allow = p['role'] == 'must-transfer'
            if res.rule == 'simhash_rescue':
                rescued += 1
            if res.verdict is Verdict.ALLOW:
                allow += 1
                if not should_allow:
                    leaks += 1
            elif res.verdict is Verdict.REFUSE:
                refuse += 1
                if should_allow:
                    fa += 1
            else:
                abstain += 1
                sig = page_class_signature(domain, seed, r, res)
                abstain_sigs.setdefault(sig, []).append(f'{domain}:{p["role"]}')

    total = allow + refuse + abstain
    distinct = len(abstain_sigs)
    print('=' * 78)
    print(f'ENSEMBLE + BATCHED JUDGE — {total} samples')
    print('=' * 78)
    print(f'hot-path verdicts: allow={allow} refuse={refuse} abstain(queued)={abstain}')
    print(f'  LEAKS={leaks}  false_alarms={fa}  simhash_rescues={rescued}')
    print(f'  abstain rate = {abstain / total:.0%}')
    print()
    print('BATCHED-JUDGE ECONOMICS (the whole point):')
    print(f'  naive LLM-per-page (hot path):     {total} calls')
    print(
        f'  LLM only on abstains:              {abstain} calls  '
        f'({(total - abstain) / total:.0%} eliminated by the ensemble)'
    )
    print(f'  ... batched & DEDUP by signature:  {distinct} distinct signatures = {distinct} judged items')
    if abstain:
        print(f'  dedup factor within the queue:     {abstain / distinct:.1f}x')
    print(f'  net vs naive:                      {total} -> {distinct} ({1 - distinct / total:.0%} fewer judge calls)')
    print()
    print('Distinct abstain signatures (each = ONE batched judge call, cached for all):')
    for sig, members in sorted(abstain_sigs.items()):
        print(f'  [{len(members)}x] {sig}')
    print()
    print('At scale: signatures recur across pages AND across runs, so the dedup')
    print('factor grows without bound — the batch judge cost per page -> ~0, and every')
    print('batch verdict is a free labeled example to train the custom model later.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
