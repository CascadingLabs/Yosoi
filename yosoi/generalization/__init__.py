"""Structural page observations and shape fingerprints (P1 subset of CAS-85).

Yosoi discovers and replays selectors *per target*. This package supplies the
cheap, capture-time structural view of a page used to recognize *page shape*
independent of the literal URL/domain:

* :class:`PageObservation` — a compact, capture-time snapshot of one page (title,
  matched-row count, body-class tokens, an HTML tag-frequency histogram); holds no
  raw HTML. :func:`observe_html` builds one from an HTML string.
* :func:`page_shape_fp` — a stable coarse *bucket* hash over a page's structural
  skeleton, so mirrors/locales/unseen domains rendering the same template land in
  one shape bucket. (P1 wires this advisory/log-only; it does not yet gate the
  selector cache.)
* :func:`structural_signals` / :func:`tag_cosine` — pairwise similarity between two
  observations, the inputs to the fail-closed reuse recommender (re-introduced in a
  later phase).

Re-exports are **lazy** (PEP 562) per the repo convention so importing one leaf
module does not eagerly pull the parsel/pydantic graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from yosoi._lazy import lazy_exports

if TYPE_CHECKING:
    from yosoi.generalization.capture import observe_html as observe_html
    from yosoi.generalization.fingerprint import ElementObservation as ElementObservation
    from yosoi.generalization.fingerprint import PageObservation as PageObservation
    from yosoi.generalization.fingerprint import StructuralSignals as StructuralSignals
    from yosoi.generalization.fingerprint import observe_element as observe_element
    from yosoi.generalization.fingerprint import page_shape_fp as page_shape_fp
    from yosoi.generalization.fingerprint import structural_signals as structural_signals
    from yosoi.generalization.fingerprint import tag_cosine as tag_cosine

_LAZY = {
    'observe_html': 'yosoi.generalization.capture',
    'ElementObservation': 'yosoi.generalization.fingerprint',
    'PageObservation': 'yosoi.generalization.fingerprint',
    'StructuralSignals': 'yosoi.generalization.fingerprint',
    'observe_element': 'yosoi.generalization.fingerprint',
    'page_shape_fp': 'yosoi.generalization.fingerprint',
    'structural_signals': 'yosoi.generalization.fingerprint',
    'tag_cosine': 'yosoi.generalization.fingerprint',
}
__all__ = sorted(_LAZY)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _LAZY)
