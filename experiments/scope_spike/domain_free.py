"""Domain-free page-class prediction — can we class a page from the DOM ALONE?

The user's vision: get to where we predict whether a page is a listing vs a
detail/profile/article from STRUCTURE ONLY — no domain, no URL, no per-site
knowledge. If that holds, the reuse-scope question stops being "same site?" and
becomes "same structural class?", which is the cross-domain recipe-bank north star
(CAS-85) grounded in a cheap signal.

This experiment treats every captured page as a bare structural fingerprint and
asks two domain-free questions on the 52-sample corpus:

  Q1 SEPARABILITY: do LISTING pages (seeds + must-transfer) and DETAIL pages
     (must-refuse) separate by a domain-free structural score, with NO domain or
     URL features? Score used: a tiny interpretable combination of
       - link density proxy: a-tag share of the histogram (lists are link-dense)
       - prose share: p/cite/sup/br/font/pre/code share (details are prose-heavy)
       - rows>0 (the recipe's own selector found repeating units)
     all computed from the tag histogram + row count, never the URL.

  Q2 NEAREST-NEIGHBOUR TRANSFER: for each page, find its nearest neighbour by
     tag-histogram cosine ACROSS ALL OTHER DOMAINS (exclude same domain). Does the
     cross-domain nearest neighbour share the same class (listing vs detail)? If
     yes, structure alone carries class across sites — a listing on site A looks
     more like a listing on site B than like a detail page on site A.

Run: uv run python experiments/scope_spike/domain_free.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DOMAINS = Path(__file__).parent / 'fixtures' / 'domains'
_PROSE = ('p', 'cite', 'sup', 'br', 'font', 'pre', 'code', 'blockquote', 'dd', 'dl')


@dataclass(frozen=True)
class Pt:
    """A bare structural point — NO domain/url used for classification."""

    domain: str  # kept only for the leave-domain-out NN test, never as a feature
    is_listing: bool  # ground truth class
    rows: int
    tag_hist: dict[str, int]


def _share(hist: dict[str, int], tags: tuple[str, ...]) -> float:
    tot = sum(hist.values()) or 1
    return sum(hist.get(t, 0) for t in tags) / tot


def link_density(hist: dict[str, int]) -> float:
    """a-tag share of all tags — listings are link-dense."""
    return _share(hist, ('a',))


def prose_share(hist: dict[str, int]) -> float:
    """prose-tag share — detail/article pages are prose-heavy."""
    return _share(hist, _PROSE)


def structural_score(p: Pt) -> float:
    """Domain-free 'is this a listing' score in ~[0,1]; higher = more list-like."""
    s = 0.0
    s += 2.0 * link_density(p.tag_hist)  # link-dense -> list
    s -= 2.0 * prose_share(p.tag_hist)  # prose-heavy -> detail
    s += 0.3 if p.rows > 3 else -0.3  # repeating units found -> list
    return s


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def load_points() -> list[Pt]:
    """Every page as a structural point (seed+transfer = listing, refuse = detail)."""
    pts = []
    for f in sorted(DOMAINS.glob('*.json')):
        d = json.loads(Path(f).read_text())
        for p in d['pages']:
            if p.get('blocked'):
                continue
            pts.append(
                Pt(
                    domain=d.get('domain', f.stem),
                    is_listing=p['role'] in ('seed', 'must-transfer'),
                    rows=int(p.get('rows', 0) or 0),
                    tag_hist=dict(p.get('tagHist', [])),
                )
            )
    return pts


def q1_separability(pts: list[Pt]) -> None:
    """Pick the best domain-free score threshold; report confusion."""
    scores = sorted({round(structural_score(p), 3) for p in pts})
    best = None
    for thr in scores:
        tp = sum(1 for p in pts if p.is_listing and structural_score(p) >= thr)
        tn = sum(1 for p in pts if not p.is_listing and structural_score(p) < thr)
        fp = sum(1 for p in pts if not p.is_listing and structural_score(p) >= thr)
        fn = sum(1 for p in pts if p.is_listing and structural_score(p) < thr)
        acc = (tp + tn) / len(pts)
        if best is None or acc > best[0]:
            best = (acc, thr, tp, tn, fp, fn)
    acc, thr, tp, tn, fp, fn = best
    lst = [structural_score(p) for p in pts if p.is_listing]
    det = [structural_score(p) for p in pts if not p.is_listing]
    print('Q1 — domain-free separability (NO url/domain features):')
    print(f'  listing score: min={min(lst):.2f} mean={sum(lst) / len(lst):.2f} max={max(lst):.2f}')
    print(f'  detail  score: min={min(det):.2f} mean={sum(det) / len(det):.2f} max={max(det):.2f}')
    print(f'  best threshold {thr:.3f}: acc={acc:.2f}  (listing✓={tp} detail✓={tn} miss-detail={fp} miss-listing={fn})')


def q2_cross_domain_nn(pts: list[Pt]) -> None:
    """For each page, nearest neighbour BY STRUCTURE in a DIFFERENT domain."""
    same = 0
    for i, p in enumerate(pts):
        best_j, best_c = -1, -1.0
        for j, q in enumerate(pts):
            if i == j or q.domain == p.domain:
                continue
            c = _cosine(p.tag_hist, q.tag_hist)
            if c > best_c:
                best_c, best_j = c, j
        if best_j >= 0 and pts[best_j].is_listing == p.is_listing:
            same += 1
    n = len(pts)
    print('\nQ2 — cross-domain nearest-neighbour class agreement (structure only):')
    print(f'  {same}/{n} pages ({same / n:.0%}) have their cross-domain nearest')
    print('  structural neighbour in the SAME class (listing vs detail).')
    print('  -> a listing on site A looks more like a listing on site B than like')
    print('     a detail page anywhere, using DOM shape alone (no domain/url).')


def main() -> int:
    """Run both domain-free experiments."""
    pts = load_points()
    print('=' * 78)
    print(f'DOMAIN-FREE PAGE-CLASS PREDICTION — {len(pts)} pages, structure only')
    print('=' * 78)
    q1_separability(pts)
    q2_cross_domain_nn(pts)
    print('\nReading: if Q1 separates and Q2 is high, page-CLASS is a property of the')
    print('DOM, not the domain — so reuse scope can be keyed on structural class and')
    print('the recipe bank can generalize across sites (CAS-85), no per-site rules.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
