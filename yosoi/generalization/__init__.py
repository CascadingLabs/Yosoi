"""Cross-target selector generalization: when is a cached recipe reusable?

Yosoi discovers and replays selectors *per target*. This package answers the
higher-altitude question — given a recipe discovered on one page, is it safe to
**reuse** it on a page we have not discovered yet (same domain, a sibling
sub-path, or a different domain entirely)?

The public surface is deterministic and fail-closed:

* :func:`recommend` — combine route-template ("tagging") and structural signals
  into a versioned :class:`ReuseSignalPanel` with an ALLOW / REFUSE / ABSTAIN
  recommendation (never ALLOW on a bare match).
* :class:`PageObservation` — the cheap, capture-time page snapshot the
  recommender consumes (no raw HTML); :func:`observe_html` builds one from HTML.
* :func:`build_decision` / :class:`DecisionRecord` — record a reuse decision with
  its trust state and back-fillable outcome, so every reuse becomes an auditable,
  labelled training row.
* :func:`route_template` — the generic URL → page-class canonicalizer.

The module is dependency-light (pydantic + parsel + stdlib); importing it does
not pull the heavier discovery/fetch stack.
"""

from __future__ import annotations

from yosoi.generalization.advise import ReuseHint, SuggestedAction, advise_reuse
from yosoi.generalization.canonicalize import (
    route_template,
    same_registrable_domain,
    same_route_class,
)
from yosoi.generalization.capture import observe_html
from yosoi.generalization.fingerprint import (
    PageObservation,
    StructuralSignals,
    structural_signals,
    tag_cosine,
)
from yosoi.generalization.recommend import recommend
from yosoi.generalization.signals import (
    SCHEMA_VERSION,
    ReuseSignalPanel,
    SignalReading,
    Verdict,
)
from yosoi.generalization.store import DecisionStore
from yosoi.generalization.trust import (
    DecisionRecord,
    Outcome,
    Trust,
    build_decision,
)

__all__ = [
    'SCHEMA_VERSION',
    'DecisionRecord',
    'DecisionStore',
    'Outcome',
    'PageObservation',
    'ReuseHint',
    'ReuseSignalPanel',
    'SignalReading',
    'StructuralSignals',
    'SuggestedAction',
    'Trust',
    'Verdict',
    'advise_reuse',
    'build_decision',
    'observe_html',
    'recommend',
    'route_template',
    'same_registrable_domain',
    'same_route_class',
    'structural_signals',
    'tag_cosine',
]
