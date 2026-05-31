"""Reuse-safety guards: VALIDATION vs TAGGING vs DISCOVERY.

The spike question (from the design thread): when a cached recipe learned on
page A is replayed on page B, *what mechanism decides whether the reuse is
safe* — and which mechanism actually catches the dangerous case?

The dangerous case (CAS-83), proven with real data in SPIKE_REPORT.md: on
old.reddit a listing recipe "succeeds" on a user-profile page and a comments
page — it returns real, well-formed posts from the WRONG page class. Field-shape
validation cannot see it (the rows genuinely are posts).

Three families of mechanism, each a pure function over a ``PageObservation``
captured identically at discovery and replay:

1. DISCOVERY (the naive baseline) — "did the selectors match anything?" This is
   what a cache keyed only on (domain, selectors) effectively does.
2. VALIDATION (the user's preferred direction) — "does the *content* satisfy an
   invariant we learned at discovery?" Semantic, site-knowledge-free.
3. TAGGING (the dumb backstop) — "is this the same page CLASS?" via route
   template or rendered body-class signal. Needs a tell (URL or DOM marker).

Each guard returns a ``Decision`` so the harness (run_comparison.py) can score
them head-to-head on the real fixtures and produce a confusion matrix.

No site-specific knowledge: every guard derives its expectation from the
discovery observation itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PageObservation:
    """A compact, replay-comparable snapshot of one fetched page.

    Field names mirror the real voidcrawl fixture
    (fixtures/reddit_observations.json) so the harness runs on live-captured
    data, not invented numbers.
    """

    role: str
    url: str
    title: str
    rows: int
    body_class: str
    distinct_sub_count: int
    distinct_subs: tuple[str, ...]
    landmarks: dict[str, object] = field(default_factory=dict)
    tag_hist: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def from_fixture(d: dict) -> PageObservation:
        """Build an observation from one voidcrawl fixture record."""
        return PageObservation(
            role=d.get('role', ''),
            url=d['href'],
            title=d['title'],
            rows=d['rows'],
            body_class=d.get('bodyClass', ''),
            distinct_sub_count=d.get('distinctSubCount', 0),
            distinct_subs=tuple(d.get('distinctSubs', [])),
            landmarks=d.get('landmarks', {}),
            tag_hist=dict(d.get('topTags', [])),
        )


@dataclass(frozen=True)
class Decision:
    """The verdict of one guard: allow reuse or refuse, with a human reason."""

    allow: bool
    reason: str

    def __str__(self) -> str:  # pragma: no cover - display only
        """Render as 'ALLOW/REFUSE — reason' for the harness trace."""
        return f'{"ALLOW" if self.allow else "REFUSE"} — {self.reason}'


# --------------------------------------------------------------------------- #
# Family 1 — DISCOVERY (naive baseline): did the selectors match anything?
# --------------------------------------------------------------------------- #
def discovery_matched(seed: PageObservation, replay: PageObservation) -> Decision:
    """The status-quo cache behavior: selectors resolved => reuse.

    This is the CAS-83 bug in pure form — it has no notion of page class or
    content invariant; any non-empty match is "success".
    """
    if replay.rows > 0:
        return Decision(True, f'selectors matched {replay.rows} rows')
    return Decision(False, 'selectors matched nothing')


# --------------------------------------------------------------------------- #
# Family 2 — VALIDATION (semantic, auto-derived invariant; the preferred path)
# --------------------------------------------------------------------------- #
def _derive_homogeneity_expectation(seed: PageObservation) -> bool:
    """Was the discovery collection homogeneous in its source subreddit?

    A subreddit listing is single-sub by construction; that constant-ness is a
    free invariant — no contract annotation, no site knowledge.
    """
    return seed.distinct_sub_count == 1


def validation_homogeneity(seed: PageObservation, replay: PageObservation) -> Decision:
    """Require an invariant that held at discovery to keep holding.

    Requires *constant*, not *equal-to-seed-value* — so /r/ted (one sub) → /r/python
    (one sub, different value) passes, while /user/spez (many subs) is refused.
    Known blind spot (the spike's key finding): a comments page is also single-sub,
    so this guard CANNOT catch it. That gap is the whole argument for layering.
    """
    if not _derive_homogeneity_expectation(seed):
        return Decision(True, 'no single-sub invariant at discovery (abstains)')
    if replay.distinct_sub_count <= 1:
        return Decision(True, f'single-sub invariant holds ({replay.distinct_subs})')
    return Decision(
        False,
        f'single-sub invariant broken: {replay.distinct_sub_count} subs {replay.distinct_subs}',
    )


def validation_cardinality(seed: PageObservation, replay: PageObservation, *, ratio: float = 0.2) -> Decision:
    """Replay row count must be in a sane band relative to discovery.

    Catches the comments page (1 row vs a 25-row seed) that homogeneity misses.
    The band is generous (>=20% of seed) so a slow-week listing (5 rows) still
    passes — proving cardinality is a coarse structural smell, not a hard count.
    """
    if seed.rows == 0:
        return Decision(True, 'seed had no rows (abstains)')
    floor = max(1, int(seed.rows * ratio))
    if replay.rows < floor:
        return Decision(False, f'row count {replay.rows} far below discovery {seed.rows} (floor {floor})')
    return Decision(True, f'row count {replay.rows} within band of {seed.rows}')


# --------------------------------------------------------------------------- #
# Family 3 — TAGGING (page-class identity; the backstop)
# --------------------------------------------------------------------------- #
_NUM = re.compile(r'\d')


def route_template(url: str) -> str:
    """Generic URL -> route template. Collapses ID-ish segments only.

    Deliberately does NOT guess slugs (that would be a per-site adapter): /r/ted
    and /r/python stay distinct *values* but share arity+verbs. It still cleanly
    separates /r/{sub}/{sort} from /r/{sub}/comments/{id} and /user/{name}.
    """
    path = re.sub(r'https?://[^/]+', '', url).split('?')[0].rstrip('/')
    out = []
    for seg in path.split('/'):
        if not seg:
            continue
        if _NUM.search(seg) or len(seg) >= 20:
            out.append('{id}')
        else:
            out.append(seg)
    return '/' + '/'.join(out)


def tagging_route(seed: PageObservation, replay: PageObservation) -> Decision:
    """Same normalized route template => same page class.

    Strong when URLs are meaningful (Reddit). Useless when URLs are garbage
    (Google Maps) — that's why TAGGING also needs a DOM-signal variant below.
    """
    st, rt = route_template(seed.url), route_template(replay.url)
    # Slug-insensitive comparison: compare the structural shape (verbs + arity),
    # treating the known-varying first value segment as a slot. We approximate
    # "structural shape" by masking any segment that differs in a single
    # position while arity is equal — but to stay site-agnostic we simply
    # compare templates with the leading /r/<value> value masked to /r/{slug}.
    st_n = _mask_known_slug(st)
    rt_n = _mask_known_slug(rt)
    if st_n != rt_n:
        return Decision(False, f'route class differs: {st_n} vs {rt_n}')
    return Decision(True, f'same route class {st_n}')


def _mask_known_slug(template: str) -> str:
    """Mask the value segment that follows a collection segment.

    Generic heuristic, NOT a Reddit rule: in /<collection>/<value>/... the
    second segment is the instance id of that collection. We mask exactly one
    such value so /r/ted/top and /r/python/top collapse, while /r/{sub}/comments
    and /user/{name} stay distinct by their trailing structure.
    """
    parts = template.strip('/').split('/')
    if len(parts) >= 2:
        parts[1] = '{slug}'
    return '/' + '/'.join(parts)


def tagging_bodyclass(seed: PageObservation, replay: PageObservation) -> Decision:
    """DOM-signal class tag: the rendered body-class page-kind tokens.

    The URL-free fallback (works when the URL is hash garbage). old.reddit emits
    'listing-page'/'comments-page'/'profile-page' tokens; we compare the page-kind
    token set, ignoring instance tokens like 'top-page'/'hot-page'.
    """

    def kind(bc: str) -> frozenset[str]:
        toks = set(bc.split())
        # keep structural page-kind tokens, drop sort/instance flavor tokens
        flavor = {'top-page', 'hot-page', 'new-page', 'rising-page', 'controversial-page'}
        return frozenset(toks - flavor)

    sk, rk = kind(seed.body_class), kind(replay.body_class)
    if sk != rk:
        return Decision(False, f'body-class kind differs: {sorted(sk)} vs {sorted(rk)}')
    return Decision(True, f'same body-class kind {sorted(sk)}')


# --------------------------------------------------------------------------- #
# Layered policies — combine families, fail-closed
# --------------------------------------------------------------------------- #
Guard = Callable[[PageObservation, PageObservation], Decision]

APPROACHES: dict[str, list[tuple[str, Guard]]] = {
    'discovery_only': [('matched', discovery_matched)],
    'validation_only': [
        ('homogeneity', validation_homogeneity),
        ('cardinality', validation_cardinality),
    ],
    'tagging_only': [
        ('route', tagging_route),
        ('bodyclass', tagging_bodyclass),
    ],
    'validation+tagging': [
        ('route', tagging_route),
        ('bodyclass', tagging_bodyclass),
        ('homogeneity', validation_homogeneity),
        ('cardinality', validation_cardinality),
    ],
}


def evaluate(approach: str, seed: PageObservation, replay: PageObservation) -> tuple[bool, str]:
    """Run an approach (fail-closed: first refusal wins) and return (allow, why)."""
    for name, guard in APPROACHES[approach]:
        d = guard(seed, replay)
        if not d.allow:
            return False, f'[{name}] {d.reason}'
    return True, 'all guards allowed'


def load_observations(path: str | Path) -> list[PageObservation]:
    """Load the fixture array into PageObservation records."""
    data = json.loads(Path(path).read_text())
    return [PageObservation.from_fixture(d) for d in data]
