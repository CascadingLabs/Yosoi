"""Explicit paging over a reduction's candidate space.

There is a ceiling on indexing, and no amount of better pruning removes it. The HTML Living
Standard reduces to 271,134 addressable candidates; the ECMAScript spec to 166,355; a single
Wikipedia list to 22,976. Those are *correct* reductions — the content really is that large and
mostly unique — and none of them fit in a model's context or in one useful overview.

The previous answer was `candidates[:max_fragments]`, which is not a ceiling but a guillotine:
it kept the first 1,000 candidates in document order and destroyed the rest. On the HTML spec
that meant the index described the masthead and the table of contents, every normative
paragraph went unaddressed, and the reader was told 937 entries were omitted "and still
inspectable by [ordinal]" when 270,134 were inspectable by nothing.

This module replaces that with a page. The candidate space is walked in windows, every window
states the true total, and the ordinals are global so a reference minted on page 40 means the
same thing as one minted on page 1.

Two invariants make paging safe:

* **Ordinals are global.** An entry's ordinal is its position in the whole candidate space,
  never its position within the page. Page-local numbering would make `[0]` ambiguous across
  pages, and an ambiguous handle is worse than a missing one.
* **Pages tile exactly.** `next_offset` is always `offset + returned`, never `offset + limit`,
  so a page that flexed its size neither skips nor repeats a candidate.

The second invariant is what lets a page be FUZZY. A page boundary is not free to fall
anywhere: a repeat region and the exemplar that shows its shape are one unit, and splitting
them leaves a region whose exemplar is on another page and an exemplar whose region is not
visible. Candidates therefore declare when they must stay with the candidate before them, and a
page overshoots its limit by up to `PAGE_SLACK` items to honour that rather than cutting. If an
atomic unit itself exceeds that allowance, the unit wins: it occupies one overlong page rather
than becoming an unpageable loop.

Not solved here, and stated rather than left to be discovered: paging gives *exhaustive* access
to a large reduction, one window at a time. It does not give a MAP of one. A 271-page index is
complete and still not something a reader can orient in, which is why progressive collapse —
describing the whole document at coarser granularity — remains separate future work rather than
something this module pretends to cover.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.models.view import Pagination

DEFAULT_PAGE_LIMIT = 1_000
"""Candidates per page by default.

A working ceiling, not a measured one. It is the value the old truncation used, kept so paging
changes *what happens past the limit* without also changing where the limit falls. A principled
limit would come from a complexity measure over the reduction — how branched and how repetitive
the document is, in the spirit of a cyclomatic score — rather than from a flat count that treats
1,000 near-identical table rows and 1,000 unique paragraphs as the same load. That measure does
not exist yet; see `observations/ROADMAP.md`.
"""

PAGE_SLACK = 8
"""How far a page may overshoot `limit` to avoid separating bound candidates.

Small on purpose. It exists to keep a region with its exemplar, which is a pair, plus a little
room for a modality that binds a short run. A large slack would make page sizes unpredictable
for a caller budgeting on them.
"""

Item = TypeVar('Item')


class PageRequest(BaseModel):
    """One window over a candidate space, requested by the caller."""

    model_config = ConfigDict(frozen=True)

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, gt=0)


def paginate(
    items: Sequence[Item],
    request: PageRequest,
    *,
    bound_to_previous: Callable[[Item], bool] | None = None,
) -> tuple[tuple[Item, ...], Pagination]:
    """Return one window of `items` plus an honest account of the whole space.

    `bound_to_previous` marks an item that must not be separated from the one before it. The
    window rewinds when an arbitrary offset lands inside a bound unit, extends past `limit` by up
    to `PAGE_SLACK` to keep a unit intact, and retracts to before an overlong unit. When that unit
    starts the page, it is returned whole even beyond the allowance: no bounded split can preserve
    atomicity, while returning only its head would make `next_offset` repeat forever. The returned
    `offset` and `returned` describe the actual flexed window.
    """
    total = len(items)
    start = min(request.offset, total)
    if bound_to_previous is not None:
        while 0 < start < total and bound_to_previous(items[start]):
            start -= 1
    end = min(start + request.limit, total)

    if bound_to_previous is not None and end < total and bound_to_previous(items[end]):
        unit_start = end
        while unit_start > start and bound_to_previous(items[unit_start]):
            unit_start -= 1
        unit_end = unit_start + 1
        while unit_end < total and bound_to_previous(items[unit_end]):
            unit_end += 1

        if unit_end <= start + request.limit + PAGE_SLACK:
            end = unit_end
        elif unit_start > start:
            # Exclude the unit head too: every following member is transitively bound to it.
            end = unit_start
        else:
            # The indivisible unit is larger than a bounded page. Returning it whole is the only
            # option that both preserves the relationship and makes the next offset advance.
            end = unit_end

    window = tuple(items[start:end])
    return window, Pagination(offset=start, limit=request.limit, returned=len(window), total=total)


__all__ = ['DEFAULT_PAGE_LIMIT', 'PAGE_SLACK', 'PageRequest', 'Pagination', 'paginate']
