"""A cheap 'world model' for the web: redundant entity fingerprints + ablation.

The vision (user): scaling to millions of contracts/domains/pages, we want to
*understand what an entity is* -- classify and fingerprint it -- even with PARTIAL
or CORRUPTED information. If the contract's own fingerprint is corrupted, we
should still recover its class from the page structure. If the body-class is
missing, the tag shape should carry it. No single signal is load-bearing; the
model degrades gracefully instead of breaking. And it must be CHEAP: hashes and
tiny vectors and nearest-neighbour lookup, never an LLM at query time.

This module makes that concrete and measurable on the 52-sample corpus:

  ENTITY FINGERPRINT (per page) = several REDUNDANT cheap components:
    - struct_vec : normalized tag-frequency vector (the structural skeleton)
    - simhash    : 64-bit locality hash of that skeleton (O(1) compare, ANN-able)
    - kind_tokens: body-class page-kind tokens (the site's own tell)
    - link_density / prose_share / has_rows : interpretable scalars

  WORLD MODEL = the set of fingerprinted entities. Classifying a NEW entity =
  cheap k-NN over the fingerprint (cosine/Hamming/Jaccard) -- no training, no LLM.
  At scale this is an ANN index over millions of vectors; here it is brute force.

  ABLATION (the whole point): drop or corrupt each component and re-measure k-NN
  class accuracy. Graceful degradation = accuracy stays usable with any single
  component knocked out. That is robustness to corruption / missing data, proven.

Run: uv run python experiments/scope_spike/worldmodel.py
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

DOMAINS = Path(__file__).parent / 'fixtures' / 'domains'
_PROSE = ('p', 'cite', 'sup', 'br', 'font', 'pre', 'code', 'blockquote', 'dd', 'dl')
_FLAVOR = frozenset({'top-page', 'hot-page', 'new-page', 'rising-page', 'controversial-page'})


@dataclass(frozen=True)
class Fingerprint:
    """A redundant, cheap, multi-component identity for one web entity (a page)."""

    domain: str
    is_listing: bool  # ground-truth class (for scoring only)
    struct_vec: dict[str, float]  # normalized tag frequencies
    simhash: int
    kind_tokens: frozenset[str]
    link_density: float
    prose_share: float
    has_rows: bool


def _simhash(weights: dict[str, float], bits: int = 64) -> int:
    acc = [0.0] * bits
    for tok, w in weights.items():
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), 'big')
        for i in range(bits):
            acc[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(bits):
        if acc[i] > 0:
            out |= 1 << i
    return out


def _norm(hist: dict[str, int]) -> dict[str, float]:
    tot = sum(hist.values()) or 1
    return {k: v / tot for k, v in hist.items()}


def _share(hist: dict[str, int], tags: tuple[str, ...]) -> float:
    tot = sum(hist.values()) or 1
    return sum(hist.get(t, 0) for t in tags) / tot


def fingerprint(domain: str, is_listing: bool, rows: int, body_class: str, hist: dict[str, int]) -> Fingerprint:
    """Build the redundant fingerprint from the free, captured observation."""
    sv = _norm(hist)
    return Fingerprint(
        domain=domain,
        is_listing=is_listing,
        struct_vec=sv,
        simhash=_simhash(sv),
        kind_tokens=frozenset(body_class.split()) - _FLAVOR,
        link_density=_share(hist, ('a',)),
        prose_share=_share(hist, _PROSE),
        has_rows=rows > 3,
    )


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def similarity(a: Fingerprint, b: Fingerprint, *, use: set[str]) -> float:
    """Composite similarity over ONLY the components named in `use` (for ablation).

    Each available component contributes a [0,1] term; we average the available
    ones. Dropping a component just removes its term -- the model still answers
    from whatever remains. That is the graceful-degradation property.
    """
    terms = []
    if 'struct' in use:
        terms.append(_cos(a.struct_vec, b.struct_vec))
    if 'simhash' in use:
        terms.append(1.0 - bin(a.simhash ^ b.simhash).count('1') / 64.0)
    if 'kind' in use:
        u = a.kind_tokens | b.kind_tokens
        terms.append((len(a.kind_tokens & b.kind_tokens) / len(u)) if u else 1.0)
    if 'scalars' in use:
        d = abs(a.link_density - b.link_density) + abs(a.prose_share - b.prose_share)
        terms.append(max(0.0, 1.0 - d) * (1.0 if a.has_rows == b.has_rows else 0.7))
    return sum(terms) / len(terms) if terms else 0.0


def knn_class_accuracy(fps: list[Fingerprint], *, use: set[str], cross_domain: bool) -> float:
    """1-NN class accuracy using only `use` components. No training, no LLM."""
    correct = 0
    for i, p in enumerate(fps):
        best_j, best_s = -1, -2.0
        for j, q in enumerate(fps):
            if i == j or (cross_domain and q.domain == p.domain):
                continue
            s = similarity(p, q, use=use)
            if s > best_s:
                best_s, best_j = s, j
        if best_j >= 0 and fps[best_j].is_listing == p.is_listing:
            correct += 1
    return correct / len(fps)


def corrupt(fp: Fingerprint, component: str) -> Fingerprint:
    """Simulate corruption of one component (zero it out) -- the failure scenario."""
    if component == 'struct':
        return replace(fp, struct_vec={}, simhash=0)
    if component == 'kind':
        return replace(fp, kind_tokens=frozenset())
    if component == 'scalars':
        return replace(fp, link_density=0.0, prose_share=0.0, has_rows=False)
    return fp


def load_fps() -> list[Fingerprint]:
    """Fingerprint every captured page."""
    fps = []
    for f in sorted(DOMAINS.glob('*.json')):
        d = json.loads(Path(f).read_text())
        for p in d['pages']:
            if p.get('blocked'):
                continue
            fps.append(
                fingerprint(
                    domain=d.get('domain', f.stem),
                    is_listing=p['role'] in ('seed', 'must-transfer'),
                    rows=int(p.get('rows', 0) or 0),
                    body_class=p.get('bodyClass', '') or '',
                    hist=dict(p.get('tagHist', [])),
                )
            )
    return fps


def _report_scope(fps: list[Fingerprint], full: set[str], *, cross: bool) -> None:
    scope = 'cross-domain (entity unseen on its own site)' if cross else 'global'
    print(f'\n[{scope}] 1-NN page-class accuracy:')
    base = knn_class_accuracy(fps, use=full, cross_domain=cross)
    print(f'  FULL fingerprint (all 4 components):      {base:.2f}')
    for comp in ('struct', 'simhash', 'kind', 'scalars'):
        use = full - {comp}
        acc = knn_class_accuracy(fps, use=use, cross_domain=cross)
        print(f'  drop {comp:8s} -> use {sorted(use)!s:38s} {acc:.2f}')
    print('  single-component-only (everything else corrupted):')
    for comp in ('struct', 'kind', 'scalars'):
        acc = knn_class_accuracy(fps, use={comp}, cross_domain=cross)
        print(f'    only {comp:8s}: {acc:.2f}')


def main() -> int:
    """Measure full-fingerprint class accuracy, then ablate each component."""
    fps = load_fps()
    full = {'struct', 'simhash', 'kind', 'scalars'}
    print('=' * 78)
    print(f'CHEAP WORLD MODEL — {len(fps)} entities, k-NN class recovery, no LLM/training')
    print('=' * 78)
    _report_scope(fps, full, cross=False)
    _report_scope(fps, full, cross=True)
    print('\nReading: if dropping any ONE component barely moves accuracy, no signal is')
    print('load-bearing -- the world model classifies entities from PARTIAL/CORRUPTED')
    print('info and degrades gracefully. That is the robustness the vision needs, and')
    print('it is all O(1) hashes + tiny-vector cosine -- cheap enough for millions via ANN.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
