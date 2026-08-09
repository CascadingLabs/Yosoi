"""Progressive collapse: describe a whole oversized document at coarser depth.

Paging made the indexing ceiling honest — a window states its true total and the windows tile
exactly — but a window is not a map. 272 pages of the HTML Living Standard is exhaustive and
still nothing a reader can orient in. Asked "does this page render its navigation correctly", an
agent handed candidates 0-999 of 271,134 has no way to know whether navigation is on page 1 or
page 240.

So there are two different answers to "the reduction does not fit", and they are for two
different questions:

    paging      → exhaustive coverage at full resolution, one window at a time
    collapse    → complete coverage of the whole document at reduced resolution

This module is the second. The walk already records how deep each candidate sits, so choosing a
granularity is choosing the deepest cut whose candidate count fits the budget: keep everything
at or above depth `d`, and tell every retained candidate that still has content below it to say
so. The result covers the document end to end — masthead to final section — at whatever
resolution the budget allows, and every omission sits under an entry that admits it and can be
inspected to descend.

This is the same trade the walk's own depth ceiling already makes, applied as a *measured*
choice instead of a constant. `MAX_DEPTH`/`MAX_BODY_DEPTH` decide resolution before seeing the
document; this decides it after counting what the document actually produced.

What collapse must never do is hide that it happened. A reduction served at depth 6 of a
possible 24 looks exactly like a shallow page unless it says otherwise, so `Granularity` is
carried on the view and stated in the rendering.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Protocol, TypeVar

from yosoi.observations.models.view import Granularity

DESCENT_NOTICE = 'below index depth — inspect to descend'
"""Appended to a retained candidate whose subtree the collapse did not index.

The wording matches the walk's own depth-ceiling disclosure on purpose: to a reader, "the index
stopped here" is one fact, and it should not read as two different conditions depending on
whether a constant or a budget caused it.
"""


class DepthCandidate(Protocol):
    """The two things collapse needs from a candidate, whatever else it carries.

    Read-only properties, not attributes: candidates are frozen value objects, and a protocol
    with settable attributes cannot be satisfied by one.
    """

    @property
    def depth(self) -> int:
        """How deep in the walk this candidate sits."""
        ...

    @property
    def descends(self) -> bool:
        """Whether unindexed content exists below it."""
        ...


Candidate = TypeVar('Candidate', bound=DepthCandidate)


def choose_depth(candidates: Sequence[DepthCandidate], budget: int) -> int:
    """Return the deepest cut whose candidate count fits `budget`.

    Depth 0 is always returned even when it alone exceeds the budget: a document whose root
    level does not fit cannot be described more coarsely, and returning something honest and
    over-budget is better than returning nothing. Paging is the remedy in that case, and the
    two compose — collapse first, then window what remains.
    """
    if budget <= 0:
        raise ValueError('a granularity budget must be positive')
    per_depth = Counter(candidate.depth for candidate in candidates)
    cumulative = 0
    chosen = 0
    for depth in sorted(per_depth):
        cumulative += per_depth[depth]
        if cumulative > budget:
            break
        chosen = depth
    return chosen


def collapse(candidates: Sequence[Candidate], budget: int) -> tuple[tuple[Candidate, ...], Granularity]:
    """Return the candidates at or above the chosen depth, plus the resolution that was chosen.

    Candidates are returned in their original order — collapse removes detail, it never reorders
    evidence, because document order is the only ordering a reader can predict.
    """
    if not candidates:
        return (), Granularity(depth=0, deepest=0, retained=0, proposed=0, undescended=0)
    deepest = max(candidate.depth for candidate in candidates)
    depth = choose_depth(candidates, budget)
    retained = tuple(candidate for candidate in candidates if candidate.depth <= depth)
    # A retained candidate is "undescended" when the collapse stopped above its own content —
    # either because it sits exactly at the cut, or because the walk had already stopped there.
    undescended = sum(1 for candidate in retained if candidate.descends and candidate.depth == depth)
    return retained, Granularity(
        depth=depth,
        deepest=deepest,
        retained=len(retained),
        proposed=len(candidates),
        undescended=undescended,
    )


__all__ = ['DESCENT_NOTICE', 'DepthCandidate', 'Granularity', 'choose_depth', 'collapse']
