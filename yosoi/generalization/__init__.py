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
* :func:`classify_scope` / :class:`ReuseScope` — tag a decision by the
  generalization distance it spans.
* :func:`disposition` / :class:`ReuseProfile` — apply the operator risk profile.
* :func:`build_decision` / :class:`DecisionRecord` — record a reuse decision with
  its trust state and back-fillable outcome, so every reuse becomes an auditable,
  labelled training row.

Re-exports are **lazy** (PEP 562) per the repo convention: importing one leaf
module (or ``import yosoi.generalization``) no longer eagerly pulls the recommender
and the parsel/pydantic graph behind it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.generalization.advise import ReuseHint as ReuseHint
    from yosoi.generalization.advise import SuggestedAction as SuggestedAction
    from yosoi.generalization.advise import advise_reuse as advise_reuse
    from yosoi.generalization.canonicalize import route_template as route_template
    from yosoi.generalization.canonicalize import same_registrable_domain as same_registrable_domain
    from yosoi.generalization.canonicalize import same_route_class as same_route_class
    from yosoi.generalization.capture import observe_html as observe_html
    from yosoi.generalization.fingerprint import PageObservation as PageObservation
    from yosoi.generalization.fingerprint import StructuralSignals as StructuralSignals
    from yosoi.generalization.fingerprint import structural_signals as structural_signals
    from yosoi.generalization.fingerprint import tag_cosine as tag_cosine
    from yosoi.generalization.policy import Disposition as Disposition
    from yosoi.generalization.policy import ReuseProfile as ReuseProfile
    from yosoi.generalization.policy import active_profile as active_profile
    from yosoi.generalization.policy import disposition as disposition
    from yosoi.generalization.recommend import recommend as recommend
    from yosoi.generalization.scope import ReuseScope as ReuseScope
    from yosoi.generalization.scope import classify_scope as classify_scope
    from yosoi.generalization.signals import SCHEMA_VERSION as SCHEMA_VERSION
    from yosoi.generalization.signals import ReuseSignalPanel as ReuseSignalPanel
    from yosoi.generalization.signals import SignalReading as SignalReading
    from yosoi.generalization.signals import Verdict as Verdict
    from yosoi.generalization.store import DecisionStore as DecisionStore
    from yosoi.generalization.trust import DecisionRecord as DecisionRecord
    from yosoi.generalization.trust import Outcome as Outcome
    from yosoi.generalization.trust import Trust as Trust
    from yosoi.generalization.trust import build_decision as build_decision

_LAZY = {
    'SCHEMA_VERSION': 'yosoi.generalization.signals',
    'DecisionRecord': 'yosoi.generalization.trust',
    'DecisionStore': 'yosoi.generalization.store',
    'Disposition': 'yosoi.generalization.policy',
    'Outcome': 'yosoi.generalization.trust',
    'PageObservation': 'yosoi.generalization.fingerprint',
    'ReuseHint': 'yosoi.generalization.advise',
    'ReuseProfile': 'yosoi.generalization.policy',
    'ReuseScope': 'yosoi.generalization.scope',
    'ReuseSignalPanel': 'yosoi.generalization.signals',
    'SignalReading': 'yosoi.generalization.signals',
    'StructuralSignals': 'yosoi.generalization.fingerprint',
    'SuggestedAction': 'yosoi.generalization.advise',
    'Trust': 'yosoi.generalization.trust',
    'Verdict': 'yosoi.generalization.signals',
    'active_profile': 'yosoi.generalization.policy',
    'advise_reuse': 'yosoi.generalization.advise',
    'build_decision': 'yosoi.generalization.trust',
    'classify_scope': 'yosoi.generalization.scope',
    'disposition': 'yosoi.generalization.policy',
    'observe_html': 'yosoi.generalization.capture',
    'recommend': 'yosoi.generalization.recommend',
    'route_template': 'yosoi.generalization.canonicalize',
    'same_registrable_domain': 'yosoi.generalization.canonicalize',
    'same_route_class': 'yosoi.generalization.canonicalize',
    'structural_signals': 'yosoi.generalization.fingerprint',
    'tag_cosine': 'yosoi.generalization.fingerprint',
}

__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
