"""Distill the (perfect, expensive) LLM judge into a cheap, typed, no-LLM detector.

The economic problem: the LLM judge scores 1.00 but costs an API call per page —
infeasible per data source at scale. The LLM's plain-text *reasons*, however, name
cheap features ("title 'overview for spez'", "body_class 'profile-page'", "article
headline title", "p/br/font explosion"). So the judgment is distillable: compute
those features for free and fit a tiny model on the judge's labels.

This module:
  1. extracts free features from each (seed, replay) pair,
  2. fits a hand-rolled logistic regression (stdlib only, no sklearn dependency),
  3. evaluates LEAVE-ONE-DOMAIN-OUT — train on N-1 domains, predict the held-out
     one — which is the honest test of "does this generalize to a domain the model
     has never seen?" (the actual economic question: don't pay the LLM per new site),
  4. reports leak-rate as the headline (a leak = wrong data shipped silently),
  5. compares against the single-feature body_class baseline and the structural
     cosine baseline.

Run: uv run python experiments/scope_spike/distill.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from run_multidomain import Page, load_pages  # type: ignore

HERE = Path(__file__).parent
DOMAINS = HERE / 'fixtures' / 'domains'


# --------------------------------------------------------------------------- #
# Feature extraction — every feature is O(1) over already-captured observation.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Features:
    """Cheap, typed features for one (seed, replay) reuse decision."""

    bodyclass_jaccard: float  # token overlap of body classes (site's own page-kind tell)
    bodyclass_kind_match: float  # 1.0 if page-kind tokens match (listing vs comments/profile)
    title_len_ratio: float  # replay title length / seed title length (articles are long)
    title_is_sentence: float  # 1.0 if replay title looks like a headline sentence
    rows_ratio: float  # min(replay,seed)/max(replay,seed) — two-sided cardinality
    rows_zero: float  # 1.0 if replay matched 0 rows
    struct_cosine: float  # tag-histogram cosine seed<->replay
    url_depth_delta: float  # |seed path depth - replay path depth|
    url_has_id: float  # 1.0 if replay path has a numeric/id-ish segment

    def vec(self) -> list[float]:
        """Ordered feature vector (with a leading bias handled by the model)."""
        return [
            self.bodyclass_jaccard,
            self.bodyclass_kind_match,
            self.title_len_ratio,
            self.title_is_sentence,
            self.rows_ratio,
            self.rows_zero,
            self.struct_cosine,
            self.url_depth_delta,
            self.url_has_id,
        ]

    @staticmethod
    def names() -> list[str]:
        """Feature names, aligned with vec()."""
        return [
            'bodyclass_jaccard',
            'bodyclass_kind_match',
            'title_len_ratio',
            'title_is_sentence',
            'rows_ratio',
            'rows_zero',
            'struct_cosine',
            'url_depth_delta',
            'url_has_id',
        ]


_LIST_KIND = ('listing', 'list', 'search', 'results', 'category', 'index', 'ns-14')
_DETAIL_KIND = (
    'comments-page',
    'single-page',
    'profile-page',
    'user',
    'item',
    'article',
    'ns-0',
    'question-page',
    'product-page',
)
_FLAVOR = {'top-page', 'hot-page', 'new-page', 'rising-page', 'controversial-page'}


def _tokens(body_class: str) -> set[str]:
    return set(body_class.split()) - _FLAVOR


def _cosine(a: dict[str, int], b: dict[str, int]) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _depth(url: str) -> int:
    path = url.split('://')[-1].split('/', 1)
    return 0 if len(path) == 1 else len([s for s in path[1].split('?')[0].split('/') if s])


def _has_id(url: str) -> float:
    path = url.split('?')[0]
    return 1.0 if any(c.isdigit() for c in path.split('/')[-1]) else 0.0


def featurize(seed: Page, r: Page) -> Features:
    """Compute the cheap feature set for replaying seed's recipe on r."""
    st, rt = _tokens(seed.body_class), _tokens(r.body_class)
    union = st | rt
    jac = len(st & rt) / len(union) if union else 1.0
    s_list = any(any(k in t for k in _LIST_KIND) for t in st)
    r_detail = any(any(k in t for k in _DETAIL_KIND) for t in rt)
    kind_match = 0.0 if (s_list and r_detail) else (1.0 if st == rt else 0.5)
    slen, rlen = max(1, len(seed.title)), len(r.title)
    title_len_ratio = rlen / slen
    title_is_sentence = 1.0 if (len(r.title.split()) >= 9 and ' : ' not in r.title) else 0.0
    hi, lo = max(seed.rows, r.rows), min(seed.rows, r.rows)
    rows_ratio = (lo / hi) if hi else 1.0
    return Features(
        bodyclass_jaccard=jac,
        bodyclass_kind_match=kind_match,
        title_len_ratio=min(title_len_ratio, 5.0),
        title_is_sentence=title_is_sentence,
        rows_ratio=rows_ratio,
        rows_zero=1.0 if r.rows == 0 else 0.0,
        struct_cosine=_cosine(seed.tag_hist, r.tag_hist),
        url_depth_delta=float(abs(_depth(seed.url) - _depth(r.url))),
        url_has_id=_has_id(r.url),
    )


# --------------------------------------------------------------------------- #
# Hand-rolled logistic regression (stdlib only — no runtime ML dependency).
# label convention: y=1 means ALLOW (same kind), y=0 means REFUSE (different).
# --------------------------------------------------------------------------- #
@dataclass
class LogReg:
    """Tiny logistic regression with z-score standardization, fit by GD."""

    w: list[float]
    b: float
    mu: list[float]
    sd: list[float]

    @staticmethod
    def fit(x: list[list[float]], y: list[int], *, epochs: int = 4000, lr: float = 0.1) -> LogReg:
        """Fit on standardized features via full-batch gradient descent."""
        n, d = len(x), len(x[0])
        mu = [sum(row[j] for row in x) / n for j in range(d)]
        sd = [math.sqrt(sum((row[j] - mu[j]) ** 2 for row in x) / n) or 1.0 for j in range(d)]
        xs = [[(row[j] - mu[j]) / sd[j] for j in range(d)] for row in x]
        w = [0.0] * d
        b = 0.0
        for _ in range(epochs):
            gw = [0.0] * d
            gb = 0.0
            for xi, yi in zip(xs, y, strict=True):
                z = b + sum(w[j] * xi[j] for j in range(d))
                p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
                err = p - yi
                for j in range(d):
                    gw[j] += err * xi[j]
                gb += err
            for j in range(d):
                w[j] -= lr * (gw[j] / n + 1e-3 * w[j])  # tiny L2
            b -= lr * gb / n
        return LogReg(w=w, b=b, mu=mu, sd=sd)

    def prob_allow(self, feat: list[float]) -> float:
        """P(allow) for one feature vector."""
        xs = [(feat[j] - self.mu[j]) / self.sd[j] for j in range(len(feat))]
        z = self.b + sum(self.w[j] * xs[j] for j in range(len(feat)))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
@dataclass
class Sample:
    """One labeled reuse decision with its domain and cheap features."""

    domain: str
    feat: Features
    allow: bool  # ground truth


def build_samples() -> list[Sample]:
    """Featurize every replay decision across all domain fixtures."""
    out: list[Sample] = []
    for f in sorted(DOMAINS.glob('*.json')):
        domain, pages = load_pages(f)
        seed = next((p for p in pages if p.role == 'seed'), None)
        if not seed:
            continue
        for p in pages:
            if p.role == 'seed':
                continue
            out.append(
                Sample(
                    domain=domain,
                    feat=featurize(seed, p),
                    allow=p.role in ('seed', 'must-transfer'),
                )
            )
    return out


def confusion(preds: list[tuple[bool, bool]]) -> dict:
    """Preds = [(pred_allow, true_allow)]; positive event = a blocked-bad-reuse."""
    tp = tn = fp = fn = 0
    for pred_allow, true_allow in preds:
        if true_allow and pred_allow:
            tp += 1
        elif true_allow and not pred_allow:
            fp += 1  # false alarm
        elif not true_allow and not pred_allow:
            tn += 1
        else:
            fn += 1  # LEAK
    total = tp + tn + fp + fn
    return {
        'good': tp,
        'bad': tn,
        'leaks': fn,
        'false_alarms': fp,
        'acc': (tp + tn) / max(1, total),
    }


def leave_one_domain_out(samples: list[Sample], *, decision_thr: float = 0.5) -> dict:
    """Train on N-1 domains, predict the held-out domain. Honest generalization."""
    domains = sorted({s.domain for s in samples})
    preds: list[tuple[bool, bool]] = []
    for held in domains:
        train = [s for s in samples if s.domain != held]
        test = [s for s in samples if s.domain == held]
        model = LogReg.fit([s.feat.vec() for s in train], [int(s.allow) for s in train])
        for s in test:
            p = model.prob_allow(s.feat.vec())
            preds.append((p >= decision_thr, s.allow))
    return confusion(preds)


def baseline_single_feature(samples: list[Sample], idx: int, thr: float) -> dict:
    """Allow iff feature[idx] >= thr — the cheapest possible detector."""
    preds = [(s.feat.vec()[idx] >= thr, s.allow) for s in samples]
    return confusion(preds)


def main() -> int:
    """Fit + evaluate the distilled detector and the cheap baselines."""
    samples = build_samples()
    print('=' * 78)
    print(
        f'DISTILLED DETECTOR — {len(samples)} samples, {len({s.domain for s in samples})} domains, leave-one-domain-out'
    )
    print('=' * 78)

    names = Features.names()

    # cheapest baselines (single free feature)
    print('\nSingle-feature baselines (whole set, best threshold by hand):')
    bc = baseline_single_feature(samples, names.index('bodyclass_kind_match'), 1.0)
    print(f'  body_class kind-match==1  -> {bc}')
    cos = baseline_single_feature(samples, names.index('struct_cosine'), 0.90)
    print(f'  struct_cosine>=0.90       -> {cos}')

    # the distilled model, honest CV
    for thr in (0.5, 0.6, 0.7):
        res = leave_one_domain_out(samples, decision_thr=thr)
        print(f'\nLogReg distilled (leave-one-domain-out, allow-thr={thr}):')
        print(f'  {res}')

    # full-fit weights for interpretability (which free features matter)
    full = LogReg.fit([s.feat.vec() for s in samples], [int(s.allow) for s in samples])
    print('\nLearned weights (full fit, standardized — sign/magnitude = importance):')
    for nm, wt in sorted(zip(names, full.w, strict=True), key=lambda kv: -abs(kv[1])):
        arrow = 'allow' if wt > 0 else 'refuse'
        print(f'  {nm:22s} {wt:+.3f}  (pushes -> {arrow})')

    print('\nNote: leak = wrong data shipped silently (the cardinal sin).')
    print('Headline metric is LEAKS at a threshold that keeps false_alarms tolerable,')
    print('NOT raw accuracy.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
